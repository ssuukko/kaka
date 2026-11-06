"""Execute the engine's public CLI; message bodies arrive on stdin, not argv.

This file runs in a separate process with a pinned engine checkout as cwd.
It deliberately does not import private engine Reader/Sender implementations.
"""

import json
import runpy
import sys
from pathlib import Path


def main() -> None:
    root = Path(sys.argv[1]).resolve()
    request = json.load(sys.stdin)
    args = request["args"]
    if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
        raise ValueError("Invalid arguments")
    if not args or args[0] not in {"status", "rooms", "messages", "send"}:
        raise ValueError("Unsupported engine operation")
    sys.path.insert(0, str(root))
    sys.argv = ["nichirin", *args]
    runpy.run_module("nichirin", run_name="__main__")


if __name__ == "__main__":
    main()
