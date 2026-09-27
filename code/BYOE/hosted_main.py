"""Local Responses server; deploy with explicit --host 0.0.0.0 behind platform auth."""

import argparse
import asyncio
import sys

from byoe.hosting import serve


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8090, type=int)
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    try:
        asyncio.run(serve(host=args.host, port=args.port))
    except KeyboardInterrupt:
        return 0
    except Exception:
        # Provider errors may contain tokens, URLs or user prompts. Do not echo them.
        print("Hosting failed; check model configuration, credentials and instructions.",
              file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())