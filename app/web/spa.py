from pathlib import Path

from fastapi.responses import FileResponse


def spa_file_response(frontend_dist: Path, full_path: str) -> FileResponse:
    """Serve only files physically contained by the built frontend directory.

    ``Path.resolve`` closes both ``..`` traversal and symlink escape. Backslashes
    are normalized before resolution so the same rule holds on Windows. Unknown
    or escaping paths fall back to the SPA index instead of touching the host FS.
    """
    root = frontend_dist.resolve()
    requested = full_path.replace("\\", "/")
    candidate = (root / requested).resolve()
    if full_path and candidate.is_relative_to(root) and candidate.is_file():
        return FileResponse(candidate)
    return FileResponse(root / "index.html")
