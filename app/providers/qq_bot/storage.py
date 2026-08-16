"""Local state storage for the QQ Bot channel.

AppID/AppSecret live in the gitignored runtime state directory with
owner-only permissions, matching the WeChat ClawBot credential store.
"""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from app.providers.local_state import LocalStateStore
from app.providers.qq_bot.models import QQBotAccount, QQContact


class QQBotStore(LocalStateStore):
    def __init__(self, root: str | Path) -> None:
        super().__init__(root)
        self._accounts_path = self._root / "accounts.json"
        self._contacts_path = self._root / "contacts.json"
        self._preferences_path = self._root / "preferences.json"
        self._cursor_dir = self._root / "cursors"
        self.ensure_private_directory(self._cursor_dir, force=True)
        for path in (
            self._accounts_path,
            self._contacts_path,
            self._preferences_path,
        ):
            self.restrict_file_permissions(path)
        for path in self._cursor_dir.glob("*.json"):
            self.restrict_file_permissions(path)

    def accounts(self) -> list[QQBotAccount]:
        result = []
        for raw in self.read_json_list(self._accounts_path):
            try:
                result.append(QQBotAccount.model_validate(raw))
            except Exception:
                continue
        return result

    def account_count(self) -> int:
        return len(self.accounts())

    def save_account(self, account: QQBotAccount) -> None:
        rows = [item.model_dump(mode="json") for item in self.accounts()]
        for index, item in enumerate(rows):
            if item["app_id"] == account.app_id:
                rows[index] = account.model_dump(mode="json")
                break
        else:
            rows.append(account.model_dump(mode="json"))
        self.write_json(self._accounts_path, rows)

    def remove_account(self, app_id: str) -> None:
        self.write_json(
            self._accounts_path,
            [item.model_dump(mode="json") for item in self.accounts() if item.app_id != app_id],
        )
        for path in self._cursor_dir.glob("*.json"):
            try:
                if path.read_text(encoding="utf-8").find(f'"{app_id}"') >= 0:
                    path.unlink()
            except Exception:
                pass

    def contacts(self) -> list[QQContact]:
        result = []
        for raw in self.read_json_list(self._contacts_path):
            try:
                result.append(QQContact.model_validate(raw))
            except Exception:
                continue
        return result

    def contact(self, scope: str, target_id: str) -> QQContact | None:
        for item in self.contacts():
            if item.scope == scope and item.target_id == target_id:
                return item
        return None

    def save_contact(self, contact: QQContact) -> None:
        rows = [item.model_dump(mode="json") for item in self.contacts()]
        for index, item in enumerate(rows):
            if item["scope"] == contact.scope and item["target_id"] == contact.target_id:
                rows[index] = contact.model_dump(mode="json")
                break
        else:
            rows.append(contact.model_dump(mode="json"))
        self.write_json(self._contacts_path, rows)

    def set_contact_subscribed(self, scope: str, target_id: str, enabled: bool) -> None:
        now = datetime.now(UTC)
        existing = self.contact(scope, target_id)
        contact = existing or QQContact(
            scope=scope,  # type: ignore[arg-type]
            target_id=target_id,
            subscribed=enabled,
            first_seen_at=now,
            last_seen_at=now,
        )
        self.save_contact(contact.model_copy(update={"subscribed": enabled, "last_seen_at": now}))

    def subscribed_contacts(self) -> list[QQContact]:
        return [item for item in self.contacts() if item.subscribed]

    def cursor(self, account_id: str) -> int:
        path = self._cursor_path(account_id)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return 0
        value = raw.get("event_cursor")
        return value if isinstance(value, int) and value >= 0 else 0

    def save_cursor(
        self, account_id: str, cursor: int, *, updated_at: datetime | None = None
    ) -> None:
        self.write_json(
            self._cursor_path(account_id),
            {
                "account_id": account_id,
                "event_cursor": cursor,
                "updated_at": (updated_at or datetime.now(UTC)).isoformat(),
            },
        )

    def decision_notifications_enabled(self) -> bool:
        return self._preferences().get("decision_notifications", True)

    def set_decision_notifications(self, enabled: bool) -> None:
        preferences = self._preferences()
        preferences["decision_notifications"] = bool(enabled)
        self.write_json(self._preferences_path, preferences)

    def _preferences(self) -> dict:
        raw = self.read_json(self._preferences_path)
        return raw if isinstance(raw, dict) else {}

    def _cursor_path(self, account_id: str) -> Path:
        digest = hashlib.sha1(account_id.encode("utf-8")).hexdigest()[:16]
        return self._cursor_dir / f"{digest}.json"
