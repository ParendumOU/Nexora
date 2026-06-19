"""Rich console singleton for all CLI output."""

from rich.console import Console

console = Console()
err_console = Console(stderr=True)
