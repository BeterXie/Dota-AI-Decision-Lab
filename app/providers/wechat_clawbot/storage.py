import getpass
import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from app.providers.wechat_clawbot.models import WeChatAccount


class WeChatClawBotStore:
    """Local credential and cursor storage for the WeChat ClawBot channel.

    Mirrors the official plugin's approach: the QR-confirmed bot token and
    server-assigned base URL are persisted next to the runtime, never logged,
    and never committed (the state directory is gitignored).
    """

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        self._accounts_path = self._root / "accounts.json"
        self._preferences_path = self._root / "preferences.json"
        self._cursor_dir = self._root / "cursors"
        self._ensure_private_directory(self._root, force=True)
        self._ensure_private_directory(self._cursor_dir, force=True)
        # Existing plaintext stores from before the permission hardening still
        # need to be locked down once at startup, not only on next write.
        self._restrict_file_permissions(self._accounts_path)
        self._restrict_file_permissions(self._preferences_path)
        for path in self._cursor_dir.glob("*.json"):
            self._restrict_file_permissions(path)

    def accounts(self) -> list[WeChatAccount]:
        result = []
        for raw in self._read_json_list(self._accounts_path):
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
        self._write_json(self._accounts_path, rows)

    def remove_account(self, account_id: str) -> None:
        self._write_json(
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
        self._write_json(
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
        self._write_json(self._preferences_path, preferences)

    def _preferences(self) -> dict:
        try:
            raw = json.loads(self._preferences_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return raw if isinstance(raw, dict) else {}

    def _cursor_path(self, account_id: str) -> Path:
        digest = hashlib.sha1(account_id.encode("utf-8")).hexdigest()[:16]
        return self._cursor_dir / f"{digest}.json"

    def _read_json_list(self, path: Path) -> list[dict]:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []
        return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []

    def _write_json(self, path: Path, value: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_private_directory(path.parent)
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(
            json.dumps(value, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if os.name != "nt":
            self._restrict_file_permissions(temp)
        os.replace(temp, path)
        if os.name != "nt":
            self._restrict_file_permissions(path)

    @staticmethod
    def _ensure_private_directory(path: Path, *, force: bool = False) -> None:
        """Best-effort owner-only directory permissions, platform by platform.

        On Windows ``icacls`` is a process spawn, so it is used only when the
        directory is first created (or ``force`` is requested at startup).
        POSIX ``chmod`` is cheap enough to reassert on every write.
        """
        existed = path.exists()
        path.mkdir(parents=True, exist_ok=True)
        if existed and os.name == "nt" and not force:
            return
        try:
            if os.name == "nt":
                WeChatClawBotStore._restrict_windows_path(path, directory=True)
            else:
                os.chmod(path, 0o700)
        except Exception:
            # State storage must not become unavailable because a platform
            # cannot express POSIX-style permissions.
            pass

    @staticmethod
    def _restrict_file_permissions(path: Path) -> None:
        """Keep token material readable/writable only by the current user.

        POSIX uses ``0600``. Windows has no equivalent in ``os.chmod`` (it only
        toggles the read-only bit), so the file DACL is replaced with the
        current user as a best-effort security boundary.
        """
        if not path.exists():
            return
        try:
            if os.name == "nt":
                WeChatClawBotStore._restrict_windows_path(path, directory=False)
            else:
                os.chmod(path, 0o600)
        except Exception:
            pass

    @staticmethod
    def _restrict_windows_path(path: Path, *, directory: bool) -> None:
        if os.name != "nt":
            return
        user = os.environ.get("USERNAME") or getpass.getuser()
        permission = "(OI)(CI)F" if directory else "(F)"
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.run(
            ["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:{permission}"],
            check=False,
            capture_output=True,
            creationflags=creation_flags,
        )
