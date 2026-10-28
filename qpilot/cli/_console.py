"""Console text: qPilot writes Unicode (ΔΔCq, ×, →, “quotes”); a Windows pipe is not Unicode.

On Windows a console shows Unicode, but output that goes through a pipe or into a file (``qpilot
--help | more``, ``qpilot trace … > out.txt``, a CI log) is written in the ANSI code page (cp1252),
and the first character that page lacks (Δ, →) raises ``UnicodeEncodeError``. The command line
therefore writes UTF-8 whatever the code page says.
"""

import sys


def ensure_utf8_output() -> None:
    """Make standard output and error UTF-8, replacing (never raising on) what cannot be shown."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)  # a TextIOWrapper; None in a test double
        if reconfigure is None:
            continue
        encoding = (
            (getattr(stream, "encoding", None) or "").lower().replace("-", "").replace("_", "")
        )
        if encoding == "utf8":
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):  # a closed or detached stream: leave it as it is
            continue
