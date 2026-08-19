from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib.parse import parse_qs, unquote, urlparse

from app.providers.liquipedia.models import (
    LiquipediaSeriesObservation,
    LiquipediaTournamentObservation,
)

_PARSER_VERSION = "liquipedia-mediawiki-v2"
_BEST_OF_PATTERN = re.compile(r"\bBo\s*(\d+)\b", re.IGNORECASE)
_SCORE_PATTERN = re.compile(r"\b\d+\s*[-:]\s*\d+\b")


def parser_version() -> str:
    return _PARSER_VERSION


@dataclass(slots=True)
class _Node:
    tag: str
    attrs: dict[str, str]
    children: list[_Node | str] = field(default_factory=list)

    @property
    def classes(self) -> set[str]:
        return set(self.attrs.get("class", "").split())

    def text(self) -> str:
        parts: list[str] = []
        for child in self.children:
            if isinstance(child, str):
                parts.append(child)
            else:
                parts.append(child.text())
        return " ".join(" ".join(parts).split())


class _TreeParser(HTMLParser):
    _VOID_TAGS = frozenset(
        {
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "param",
            "source",
            "track",
            "wbr",
        }
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("document", {})
        self._stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = _Node(
            tag=tag,
            attrs={name: value or "" for name, value in attrs},
        )
        self._stack[-1].children.append(node)
        if tag not in self._VOID_TAGS:
            self._stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in self._VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index].tag == tag:
                del self._stack[index:]
                return

    def handle_data(self, data: str) -> None:
        if data:
            self._stack[-1].children.append(data)


def parse_tournaments(html: str) -> list[LiquipediaTournamentObservation]:
    root = _parse_tree(html)
    observations: list[LiquipediaTournamentObservation] = []
    seen: set[tuple[str, str]] = set()

    for node in _walk(root):
        if node.tag != "li":
            continue
        phase = _phase_from_heading(_direct_text(node))
        if phase is None:
            continue
        for child in node.children:
            if not isinstance(child, _Node) or child.tag != "ul":
                continue
            for item in child.children:
                if not isinstance(item, _Node) or item.tag != "li":
                    continue
                fields = [field.strip() for field in item.text().split("|")]
                if len(fields) < 2 or not fields[0] or not fields[1]:
                    continue
                page_name = fields[0].replace("_", " ")
                name, page_name, _stage = _event_identity(fields[1], page_name)
                if name is None or page_name is None:
                    continue
                key = (phase, page_name)
                if key in seen:
                    continue
                seen.add(key)
                metadata = _key_value_fields(fields[2:])
                date_label = _date_range(
                    metadata.get("startdate"),
                    metadata.get("enddate"),
                )
                observations.append(
                    LiquipediaTournamentObservation(
                        page_name=page_name,
                        name=name,
                        phase=phase,
                        tier=None,
                        date_label=date_label,
                        source_href=f"/dota2/{fields[0]}",
                    )
                )
    return observations


def parse_series(html: str) -> list[LiquipediaSeriesObservation]:
    root = _parse_tree(html)
    observations: list[LiquipediaSeriesObservation] = []
    seen: set[str] = set()

    for card in _nodes_with_class(root, "match-info"):
        header = _first_descendant_with_class(card, "match-info-header")
        if header is None:
            continue
        opponents = [
            node
            for node in _walk(header)
            if "match-info-header-opponent" in node.classes
        ]
        if len(opponents) != 2:
            continue
        team_a_name, team_a_page = _team_identity(
            _first_descendant_with_class(opponents[0], "name") or opponents[0]
        )
        team_b_name, team_b_page = _team_identity(
            _first_descendant_with_class(opponents[1], "name") or opponents[1]
        )
        if not team_a_name or not team_b_name:
            continue

        tournament = _first_descendant_with_class(card, "match-info-tournament-name")
        tournament_name, tournament_page = _tournament_identity(
            tournament,
            excluded_pages={page for page in (team_a_page, team_b_page) if page},
        )
        tournament_name, tournament_page, stage = _event_identity(
            tournament_name,
            tournament_page,
        )
        scoreholder = _first_descendant_with_class(card, "match-info-header-scoreholder")
        score_text = scoreholder.text() if scoreholder is not None else ""
        best_of_match = _BEST_OF_PATTERN.search(score_text)
        best_of = int(best_of_match.group(1)) if best_of_match else None
        scheduled_at = _machine_timestamp(card)
        state = _match_state(score_text, header)
        provider_key = _match_page_id(card)
        if provider_key is None or provider_key in seen:
            continue
        seen.add(provider_key)
        observations.append(
            LiquipediaSeriesObservation(
                team_a_name=team_a_name,
                team_a_page=team_a_page,
                team_b_name=team_b_name,
                team_b_page=team_b_page,
                tournament_name=tournament_name,
                tournament_page=tournament_page,
                stage=stage,
                best_of=best_of,
                scheduled_at=scheduled_at,
                state=state,
                provider_key=provider_key,
            )
        )
    return observations


def _parse_tree(html: str) -> _Node:
    parser = _TreeParser()
    parser.feed(html)
    parser.close()
    return parser.root


def _walk(node: _Node):
    yield node
    for child in node.children:
        if isinstance(child, _Node):
            yield from _walk(child)


def _nodes_with_class(root: _Node, class_name: str) -> list[_Node]:
    return [node for node in _walk(root) if class_name in node.classes]


def _first_descendant_with_class(node: _Node, class_name: str) -> _Node | None:
    return next((item for item in _walk(node) if class_name in item.classes), None)


def _first_anchor(node: _Node) -> _Node | None:
    return next((item for item in _walk(node) if item.tag == "a"), None)


def _phase_from_heading(value: str) -> str | None:
    normalized = value.casefold()
    if "upcoming" in normalized:
        return "UPCOMING"
    if "ongoing" in normalized:
        return "ONGOING"
    if "concluded" in normalized or "completed" in normalized or "finished" in normalized:
        return "COMPLETED"
    return None


def _dota_page_name(href: str) -> str | None:
    parsed = urlparse(href)
    path = parsed.path
    marker = "/dota2/"
    if marker not in path:
        return None
    page = unquote(path.split(marker, 1)[1]).strip("/")
    if page == "index.php":
        titles = parse_qs(parsed.query).get("title", [])
        page = titles[0] if titles else ""
    if not page or page.startswith("Liquipedia:"):
        return None
    return page.replace("_", " ")


def _team_identity(node: _Node) -> tuple[str, str | None]:
    anchor = _first_anchor(node)
    if anchor is None:
        return node.text().strip(), None
    name = anchor.attrs.get("title") or anchor.text() or node.text()
    name = re.sub(r"\s*\(page does not exist\)\s*$", "", name, flags=re.IGNORECASE)
    return name.strip(), _dota_page_name(anchor.attrs.get("href", ""))


def _tournament_identity(
    node: _Node | None,
    *,
    excluded_pages: set[str],
) -> tuple[str | None, str | None]:
    if node is None:
        return None, None
    for item in _walk(node):
        if item.tag != "a":
            continue
        page_name = _dota_page_name(item.attrs.get("href", ""))
        if page_name is None or page_name in excluded_pages:
            continue
        name = item.text().strip()
        if name:
            return name, page_name
    return None, None


def _machine_timestamp(node: _Node) -> datetime | None:
    attribute_names = ("data-timestamp", "data-unix", "data-time", "datetime")
    for item in _walk(node):
        for attribute_name in attribute_names:
            raw = item.attrs.get(attribute_name)
            if not raw:
                continue
            parsed = _parse_timestamp(raw)
            if parsed is not None:
                return parsed
    return None


def _parse_timestamp(raw: str) -> datetime | None:
    value = raw.strip()
    if value.isdigit():
        timestamp = int(value)
        if timestamp > 10_000_000_000:
            timestamp //= 1000
        try:
            return datetime.fromtimestamp(timestamp, tz=UTC)
        except OverflowError, OSError, ValueError:
            return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _match_state(score_text: str, header: _Node) -> str:
    if any(
        "match-info-header-winner" in node.classes
        or "match-info-header-loser" in node.classes
        for node in _walk(header)
    ):
        return "COMPLETED"
    normalized = score_text.casefold()
    if "vs" in normalized:
        return "UPCOMING"
    if _SCORE_PATTERN.search(score_text):
        return "COMPLETED"
    return "UNKNOWN"


def _event_identity(
    tournament_name: str | None,
    tournament_page: str | None,
) -> tuple[str | None, str | None, str | None]:
    if tournament_name is None:
        return None, tournament_page, None
    parts = re.split(r"\s+[-–—]\s+", tournament_name, maxsplit=1)
    event_name = parts[0].strip()
    stage = parts[1].strip() if len(parts) == 2 and parts[1].strip() else None
    event_page = tournament_page
    if event_page is not None and stage is not None:
        page_parts = event_page.split("/")
        if page_parts and _identity_token(page_parts[-1]) == _identity_token(stage):
            event_page = "/".join(page_parts[:-1])
    if (
        re.fullmatch(r"ti\s*2026", event_name, re.IGNORECASE)
        or (event_page or "").casefold().startswith("the international/2026")
    ):
        event_name = "The International 2026"
        event_page = "The International/2026"
    return event_name or None, event_page, stage


def _identity_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _match_page_id(node: _Node) -> str | None:
    for item in _walk(node):
        if item.tag != "a":
            continue
        href = item.attrs.get("href", "")
        parsed = urlparse(href)
        for title in parse_qs(parsed.query).get("title", []):
            if title.startswith("Match:") and len(title) <= 128:
                return title
        page_name = _dota_page_name(href)
        if page_name is not None and page_name.startswith("Match:") and len(page_name) <= 128:
            return page_name
    return None


def _direct_text(node: _Node) -> str:
    return " ".join(" ".join(child.split()) for child in node.children if isinstance(child, str))


def _key_value_fields(fields: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for field in fields:
        key, separator, value = field.partition("=")
        if separator:
            values[key.strip().casefold()] = value.strip()
    return values


def _date_range(start: str | None, end: str | None) -> str | None:
    parts = [value for value in (start, end) if value]
    return " - ".join(parts) if parts else None
