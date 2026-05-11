from __future__ import annotations

import os
from typing import Any, IO


def flush_csv_row(handle: IO[Any]) -> None:
    """Flush a CSV row so in-progress logs are recoverable across run modes.

    ``flush()`` makes the row visible to other readers immediately during a run.
    ``fsync()`` asks the operating system to commit the file data as well, which
    reduces data loss if the Python process or host fails shortly after a sample.
    Some file-like objects used by tests or wrappers do not expose a real file
    descriptor; in those cases the best available flush has already happened.
    """
    handle.flush()
    try:
        os.fsync(handle.fileno())
    except (AttributeError, OSError, ValueError):
        return
