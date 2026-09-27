"""BYOE CLI: 0 pass, 1 quality/fixture gate failure, 2 configuration/runtime error."""

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    evaluate_parser = commands.add_parser("evaluate")
    verify_parser = commands.add_parser("verify")
    for child in (evaluate_parser, verify_parser):
        child.add_argument("--suite", required=True, type=Path)
        child.add_argument("--output", type=Path, default=Path("results"))
    evaluate_parser.add_argument("--data", required=True, type=Path)
    evaluate_parser.add_argument("--collect", action="store_true")
    verify_parser.add_argument("--fixtures", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "verify":
            from byoe.verify import verify_suite

            path, passed = verify_suite(args.suite, args.fixtures, args.output)
        else:
            from byoe.runner import run_suite

            path, passed = run_suite(args.suite, args.data, args.output, args.collect)
        print(f"Report: {path}")
        print("Gate: PASS" if passed else "Gate: FAIL")
        return 0 if passed else 1
    except Exception:
        print("BYOE configuration or runtime error; details withheld to protect secrets.",
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())