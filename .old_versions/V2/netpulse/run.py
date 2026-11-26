#!/usr/bin/env python3
"""Convenience launcher: ``python run.py`` opens the desktop app."""

import sys

from netpulse.app import main

if __name__ == "__main__":
    sys.exit(main())
