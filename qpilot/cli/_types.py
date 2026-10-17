"""Shared type for CLI command registrations. FROZEN at T0."""

import argparse
from collections.abc import Callable

Command = tuple[str, str, Callable[[argparse.ArgumentParser], None], Callable[..., int]]
