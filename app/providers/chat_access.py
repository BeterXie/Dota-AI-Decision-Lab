"""Shared access classification for user-scoped chat transports.

Legacy chat commands still render public match data and local-only behavior, while
user-scoped transports must intercept premium AI queries and per-user notification
preference changes before those commands can reach the legacy store.
"""


def is_ai_decision_query(text: str) -> bool:
    normalized = text.strip().casefold()
    return "为什么" in normalized or "buy" in normalized


def is_notification_pause_command(text: str) -> bool:
    normalized = text.strip().casefold()
    return "暂停" in normalized and "通知" in normalized


def is_notification_resume_command(text: str) -> bool:
    normalized = text.strip().casefold()
    return ("恢复" in normalized or "开启" in normalized) and "通知" in normalized
