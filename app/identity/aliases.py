import unicodedata

_TEAM_ALIAS_GROUPS = (
    frozenset(("aurora", "aurora gaming", "aurora.1xbet")),
    frozenset(("level up", "level up esports")),
    frozenset(("lgd", "lgd gaming")),
    frozenset(("liquid", "team liquid")),
    frozenset(("spirit", "team spirit")),
    frozenset(("vg", "vici gaming")),
)


def normalize_alias(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(normalized.split())


def equivalent_team_aliases(value: str) -> frozenset[str]:
    normalized = normalize_alias(value)
    for aliases in _TEAM_ALIAS_GROUPS:
        if normalized in aliases:
            return aliases
    return frozenset((normalized,))
