"""
AnySpecs CLI - Code is Cheap, Show me Any Specs

A unified CLI tool for exporting chat history from multiple AI assistants.
Supports Cursor AI, Claude Code, Codex CLI, Augment, Kiro Records and OpenCode.
"""

__version__ = "0.0.5"
__author__ = "AnySpecs Team"


def main():
    """Run the CLI entrypoint without importing heavy dependencies eagerly."""
    from .cli import main as cli_main

    return cli_main()


__all__ = ["main"]
