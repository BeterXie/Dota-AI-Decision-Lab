import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from app.providers.local_state import LocalStateStore
from app.providers.wechat_clawbot.models import WeChatAccount


class WeChatClawBotStore(LocalStateStore):
    """Local credential and cursor storage for the WeChat ClawBot channel.

    Mirrors the official plugin's approach: the QR-confirmed bot token and
    server-assigned base URL are persisted next to the runtime, never logged,
    and never committed (the state directory is gitignored).
    """

    def __init__(self, root: str | Path) -> None:
        super().__init__(root)
        self._accounts_path = self._root / "accounts.json"
        self._preferences_path = self._root / "preferences.json"
        self._cursor_dir = self._root / "cursors"
        self._ensure_private_directory(self._cursor_dir, force=True)
        # Existing plaintext stores from before the permission hardening still
        # need to be locked down once at startup, not only on next write.
        self._restrict_file_permissions(self._accounts_path)
        self._restrict_file_permissions(self._preferences_path)
        for path in self._cursor_dir.glob("*.json"):
            self._restrict_file_permissions(path)

    def accounts(self) -> list[WeChatAccount]:
        result = []
        for raw in self.read_json_list(self._accounts_path):
            try:
                result.append(WeChatAccount.model_validate(raw))
            except Exception:
                continue
        return result

    def account_count(self) -> int:
        return len(self.accounts())

    def save_account(self, account: WeChatAccount) -> None:
        rows = [item.model_dump(mode="json") for item in self.accounts()]
        for index, item in enumerate(rows):
            if item["account_id"] == account.account_id:
                rows[index] = account.model_dump(mode="json")
                break
        else:
            rows.append(account.model_dump(mode="json"))
        self.write_json(self._accounts_path, rows)

    def remove_account(self, account_id: str) -> None:
        self.write_json(
            self._accounts_path,
            [
                item.model_dump(mode="json")
                for item in self.accounts()
                if item.account_id != account_id
            ],
        )
        for path in self._cursor_dir.glob("*.json"):
            try:
                if path.read_text(encoding="utf-8").find(f'"{account_id}"') >= 0:
                    path.unlink()
            except Exception:
                pass

    def cursor(self, account_id: str) -> str:
        path = self._cursor_path(account_id)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return ""
        value = raw.get("get_updates_buf")
        return value if isinstance(value, str) else ""

    def save_cursor(
        self, account_id: str, cursor: str, *, updated_at: datetime | None = None
    ) -> None:
        self.write_json(
            self._cursor_path(account_id),
            {
                "account_id": account_id,
                "get_updates_buf": cursor,
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
