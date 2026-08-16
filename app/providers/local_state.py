"""Shared local state primitives for provider channels.

Chat-channel credentials, cursors and preferences are runtime-local state,
never database facts.  They live in gitignored directories with best-effort
owner-only permissions.  This module centralizes the JSON and permission
handling used by both the WeChat ClawBot and QQ Bot stores.
"""

import getpass
import json
import os
import subprocess
from pathlib import Path
from typing import Any


class LocalStateStore:
    """Owner-only JSON state directory.

    Subclasses own their file layout; this base only provides atomic JSON
    writes and platform-specific private permission handling.
    """

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        self._ensure_private_directory(self._root, force=True)

    @property
    def root(self) -> Path:
        return self._root

    def read_json(self, path: Path) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def read_json_list(self, path: Path) -> list[dict[str, Any]]:
        raw = self.read_json(path)
        return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []

    def write_json(self, path: Path, value: object) -> None:
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

    def ensure_private_directory(self, path: Path, *, force: bool = False) -> None:
        self._ensure_private_directory(path, force=force)

    def restrict_file_permissions(self, path: Path) -> None:
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
                LocalStateStore._restrict_windows_path(path, directory=True)
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
                LocalStateStore._restrict_windows_path(path, directory=False)
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
