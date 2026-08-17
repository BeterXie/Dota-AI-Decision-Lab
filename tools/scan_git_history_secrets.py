import re
import shutil
import subprocess
from dataclasses import dataclass

_SCANNER_PATH = "tools/scan_git_history_secrets.py"
_PATTERNS: tuple[tuple[str, re.Pattern[bytes]], ...] = (
    ("private-key", re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("openai-key", re.compile(rb"\bsk-(?:proj-)?[A-Za-z0-9_-]{24,}\b")),
    ("anthropic-key", re.compile(rb"\bsk-ant-[A-Za-z0-9_-]{24,}\b")),
    ("github-token", re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("aws-access-key", re.compile(rb"\bAKIA[A-Z0-9]{16}\b")),
    ("google-api-key", re.compile(rb"\bAIza[A-Za-z0-9_-]{30,}\b")),
    ("stripe-live-key", re.compile(rb"\bsk_live_[A-Za-z0-9]{20,}\b")),
    ("resend-key", re.compile(rb"\bre_[A-Za-z0-9]{24,}\b")),
)


@dataclass(frozen=True, slots=True)
class Finding:
    commit: str
    path: str
    rule: str


def main() -> None:
    git = shutil.which("git")
    if git is None:
        raise SystemExit("git executable is required for history secret scanning")
    result = subprocess.run(  # noqa: S603 - executable path is resolved by shutil.which
        [
            git,
            "log",
            "--all",
            "--patch",
            "--format=commit %H",
            "--no-ext-diff",
            "--unified=0",
            "--",
            ".",
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    findings = _scan_patch_stream(result.stdout)
    if findings:
        for item in sorted(findings, key=lambda value: (value.commit, value.path, value.rule)):
            print(
                "potential secret in git history: "
                f"commit={item.commit[:12]} path={item.path} rule={item.rule}"
            )
        raise SystemExit(
            "Git history contains high-confidence secret-like material. "
            "Rotate/revoke the credential before rewriting history."
        )
    print("Git history secret scan: no high-confidence matches")


def _scan_patch_stream(raw: bytes) -> set[Finding]:
    findings: set[Finding] = set()
    commit = "unknown"
    path = "unknown"
    old_path = "unknown"
    for line in raw.splitlines():
        if line.startswith(b"commit "):
            commit = line[7:].decode("ascii", errors="replace")
            path = "unknown"
            old_path = "unknown"
            continue
        if line.startswith(b"--- a/"):
            old_path = line[6:].decode("utf-8", errors="replace")
            path = old_path
            continue
        if line.startswith(b"+++ b/"):
            path = line[6:].decode("utf-8", errors="replace")
            continue
        if line == b"+++ /dev/null":
            path = old_path
            continue
        if path == _SCANNER_PATH or not line.startswith((b"+", b"-")):
            continue
        content = line[1:]
        for rule, pattern in _PATTERNS:
            if pattern.search(content):
                findings.add(Finding(commit=commit, path=path, rule=rule))
    return findings


if __name__ == "__main__":
    main()
