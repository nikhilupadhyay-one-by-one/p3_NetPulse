"""Subprocess plumbing shared by every diagnostic tool.

Two things matter here:

1. On Windows, launching a console program from a GUI process flashes a black
   console window. ``CREATE_NO_WINDOW`` suppresses it.
2. ``ping``/``tracert`` output is localised and not always UTF-8, so decoding is
   forgiving rather than strict.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import sys
import threading
from collections.abc import Iterator

IS_WINDOWS = sys.platform.startswith("win")
IS_MACOS = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")

_NO_WINDOW = 0x08000000 if IS_WINDOWS else 0


def _popen_kwargs() -> dict:
    kwargs: dict = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "stdin": subprocess.DEVNULL,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "bufsize": 1,
    }
    if IS_WINDOWS:
        kwargs["creationflags"] = _NO_WINDOW
    else:
        # Put the child in its own process group so terminating the worker does
        # not take the whole app down with it.
        kwargs["start_new_session"] = True
    return kwargs


def which(program: str) -> str | None:
    """Return the resolved path to ``program``, or ``None`` if it is missing."""
    return shutil.which(program)


def run(command: list[str], timeout: float = 30.0) -> tuple[int, str]:
    """Run a command to completion and return ``(returncode, combined_output)``."""
    try:
        completed = subprocess.run(command, timeout=timeout, **_popen_kwargs())
    except FileNotFoundError:
        return 127, f"{command[0]}: command not found"
    except subprocess.TimeoutExpired as exc:
        partial = exc.output or ""
        if isinstance(partial, bytes):
            partial = partial.decode("utf-8", "replace")
        return 124, partial
    except OSError as exc:  # permissions, exec format, ...
        return 126, str(exc)
    return completed.returncode, completed.stdout or ""


def stream(
    command: list[str],
    stop: threading.Event | None = None,
    timeout: float | None = None,
) -> Iterator[str]:
    """Yield output lines as the command produces them.

    Setting ``stop`` terminates the child process at the next line boundary,
    which is what makes the Stop button in the UI feel immediate.
    """
    try:
        process = subprocess.Popen(command, **_popen_kwargs())
    except FileNotFoundError:
        yield f"{command[0]}: command not found"
        return
    except OSError as exc:
        yield str(exc)
        return

    timer: threading.Timer | None = None
    if timeout:
        timer = threading.Timer(timeout, _terminate, args=(process,))
        timer.daemon = True
        timer.start()

    try:
        assert process.stdout is not None
        for line in process.stdout:
            yield line.rstrip("\r\n")
            if stop is not None and stop.is_set():
                _terminate(process)
                break
    finally:
        if timer is not None:
            timer.cancel()
        if process.poll() is None:
            _terminate(process)
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()


def _terminate(process: subprocess.Popen) -> None:
    try:
        if IS_WINDOWS:
            process.terminate()
        else:
            os.killpg(os.getpgid(process.pid), 15)
    except (ProcessLookupError, PermissionError, OSError):
        # The process group call can fail if the child already exited; fall
        # back to a plain terminate, and accept that it may also be too late.
        with contextlib.suppress(OSError):
            process.terminate()
