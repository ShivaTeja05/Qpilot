"""Regenerate ``validation_table.md`` and ``validation.json`` next to this script.

Same as ``qpilot validate --out validation``; extra arguments are passed through.
"""

import sys
from pathlib import Path

from qpilot.cli import main

if __name__ == "__main__":
    sys.exit(main(["validate", "--out", str(Path(__file__).parent), *sys.argv[1:]]))
