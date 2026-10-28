"""Console text: qPilot writes Unicode (ΔΔCq, ×, →, “quotes”); a Windows pipe is not Unicode.

On Windows a console shows Unicode, but output that goes through a pipe or into a file (``qpilot
--help | more``, ``qpilot trace … > out.txt``, a CI log) is written in the ANSI code page (cp1252),
and the first character that page lacks (Δ, →) raises ``UnicodeEncodeError``. The command line
therefore writes UTF-8 whatever the code page says.
"""

import os
import sys


def ensure_utf8_output() -> None:
    """Make standard output and error UTF-8, replacing (never raising on) what cannot be shown.

    A stream that is not a terminal (a pipe, a file) also ends its lines with LF alone, so
    ``--json`` output is byte-identical on every system.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)  # a TextIOWrapper; None in a test double
        if reconfigure is None:
            continue
        options: dict[str, str] = {}
        encoding = str(getattr(stream, "encoding", None) or "").lower()
        if encoding.replace("-", "").replace("_", "") != "utf8":
            options.update(encoding="utf-8", errors="replace")
        try:
            if os.name == "nt" and not stream.isatty():
                options["newline"] = "\n"
            if options:
                reconfigure(**options)
        except (OSError, ValueError):  # a closed or detached stream: leave it as it is
            continue
