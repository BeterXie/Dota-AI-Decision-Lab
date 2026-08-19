from __future__ import annotations

import argparse

from app.production_origin import verify_origin


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify the public DotaScope production origin")
    parser.add_argument(
        "--base-url",
        default="https://dotascope.com",
        help="Canonical HTTPS origin (default: https://dotascope.com)",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    checks = verify_origin(args.base_url)
    for check in checks:
        marker = "PASS" if check.passed else "FAIL"
        print(f"[{marker}] {check.name}: {check.detail}")
    failed = [check for check in checks if not check.passed]
    print(f"\n{len(checks) - len(failed)}/{len(checks)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
