"""Show validated fact coverage without changing source documents or facts."""

from __future__ import annotations

import argparse
import json

from myfinance_agent_docs.coverage import auto_validated_coverage


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return a non-zero exit code if one core report/metric cell is missing.",
    )
    args = parser.parse_args()
    summary = auto_validated_coverage()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if args.strict and summary["gaps"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
