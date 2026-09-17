"""``python -m netpulse`` dispatches to the GUI or the terminal interface."""

from __future__ import annotations

import sys


def main() -> int:
    argv = sys.argv[1:]
    if argv and argv[0] in ("--cli", "cli"):
        from .cli import main as cli_main

        return cli_main(argv[1:])

    from .app import main as gui_main

    return gui_main()


if __name__ == "__main__":
    raise SystemExit(main())
