from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib.parse import unquote, urlparse

from app.providers.liquipedia.models import (
    LiquipediaSeriesObservation,
    LiquipediaTournamentObservation,
)

_PARSER_VERSION = "liquipedia-mediawiki-v1"
_BEST_OF_PATTERN = re.compile(r"\bBo\s*(\d+)\b", re.IGNORECASE)
_SCORE_PATTERN = re.compile(r"\b\d+\s*[-:]\s*\d+\b")


def parser_version() -> str:
    return _PARSER_VERSION


@dataclass(slots=True)
class _Node:
    tag: str
    attrs: dict[str, str]
    parent: _Node | None = None
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
    _VOID_TAGS = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("document", {})
        self._stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = _Node(
            tag=tag,
            attrs={name: value or "" for name, value in attrs},
            parent=self._stack[-1],
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
    current_phase: str | None = None
    observations: list[LiquipediaTournamentObservation] = []
    seen: set[tuple[str, str]] = set()

    for node in _walk(root):
        if "tournaments-list-heading" in node.classes:
            current_phase = _phase_from_heading(node.text())
            continue
        if "tournaments-list-name" not in node.classes or current_phase is None:
            continue
        anchor = _first_anchor(node)
        if anchor is None:
            continue
        href = anchor.attrs.get("href", "")
        page_name = _dota_page_name(href)
        name = anchor.text() or node.text()
        if page_name is None or not name:
            continue
        key = (current_phase, page_name)
        if key in seen:
            continue
        seen.add(key)
        item = _nearest_ancestor(node, "li") or node.parent or node
        tier_node = _first_descendant_with_class(item, "tournament-badge__text")
        if tier_node is None:
            tier_node = _first_descendant_with_class(item, "tournament-badge")
        dates_node = _first_descendant_with_class(item, "tournaments-list-dates")
        observations.append(
            LiquipediaTournamentObservation(
                page_name=page_name,
                name=name,
                phase=current_phase,
                tier=_clean_optional(tier_node.text() if tier_node is not None else None),
                date_label=_clean_optional(dates_node.text() if dates_node is not None else None),
                source_href=href,
            )
        )
    return observations


def parse_series(html: str) -> list[LiquipediaSeriesObservation]:
    root = _parse_tree(html)
    observations: list[LiquipediaSeriesObservation] = []
    seen: set[str] = set()

    for table in _nodes_with_class(root, "infobox_matches_content"):
        team_a_node = _first_descendant_with_class(table, "team-left")
        team_b_node = _first_descendant_with_class(table, "team-right")
        versus_node = _first_descendant_with_class(table, "versus")
        if team_a_node is None or team_b_node is None or versus_node is None:
            continue
        team_a_name, team_a_page = _team_identity(team_a_node)
        team_b_name, team_b_page = _team_identity(team_b_node)
        if not team_a_name or not team_b_name:
            continue

        filler = _first_descendant_with_class(table, "match-filler")
        tournament_name, tournament_page = _tournament_identity(
            filler,
            excluded_pages={page for page in (team_a_page, team_b_page) if page},
        )
        versus_text = versus_node.text()
        best_of_match = _BEST_OF_PATTERN.search(versus_text)
        best_of = int(best_of_match.group(1)) if best_of_match else None
        scheduled_at = _machine_timestamp(table)
        state = _match_state(versus_text)
        stage = _stage_text(filler, tournament_name)
        provider_key = _series_key(
            team_a_page or team_a_name,
            team_b_page or team_b_name,
            tournament_page or tournament_name or "unknown-event",
            scheduled_at,
            best_of,
            stage,
        )
        if provider_key in seen:
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


def _nearest_ancestor(node: _Node, tag: str) -> _Node | None:
    current = node.parent
    while current is not None:
        if current.tag == tag:
            return current
        current = current.parent
    return None


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
    path = urlparse(href).path
    marker = "/dota2/"
    if marker not in path:
        return None
    page = unquote(path.split(marker, 1)[1]).strip("/")
    if not page or page.startswith("Liquipedia:"):
        return None
    return page.replace("_", " ")


def _team_identity(node: _Node) -> tuple[str, str | None]:
    anchor = _first_anchor(node)
    if anchor is None:
        return node.text().strip(), None
    return (anchor.text() or node.text()).strip(), _dota_page_name(anchor.attrs.get("href", ""))


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
        except (OverflowError, OSError, ValueError):
            return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _match_state(versus_text: str) -> str:
    normalized = versus_text.casefold()
    if "vs" in normalized:
        return "UPCOMING"
    if _SCORE_PATTERN.search(versus_text):
        return "COMPLETED"
    return "UNKNOWN"


def _stage_text(node: _Node | None, tournament_name: str | None) -> str | None:
    if node is None:
        return None
    text = node.text()
    if tournament_name:
        text = text.replace(tournament_name, "", 1)
    text = re.sub(r"\s+", " ", text).strip(" -|·")
    return text or None


def _series_key(
    team_a: str,
    team_b: str,
    tournament: str,
    scheduled_at: datetime | None,
    best_of: int | None,
    stage: str | None,
) -> str:
    teams = sorted((team_a.casefold().strip(), team_b.casefold().strip()))
    timestamp = scheduled_at.isoformat() if scheduled_at is not None else "unknown-time"
    raw = "|".join((tournament.casefold().strip(), *teams, timestamp, str(best_of), stage or ""))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(value.split()).strip()
    return cleaned or None
