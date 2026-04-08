"""Tests for the desktop application module."""

from __future__ import annotations

import sys
from unittest.mock import patch

import pytest


class TestDesktopModule:
    def test_desktop_module_importable(self) -> None:
        """The desktop module should be importable even without pywebview."""
        from storageanalyser import desktop
        assert hasattr(desktop, "run_desktop")
        assert hasattr(desktop, "main")

    def test_run_desktop_exits_without_pywebview(self) -> None:
        """run_desktop should exit with an error if pywebview is not installed."""
        with patch.dict("sys.modules", {"webview": None}):
            # Re-import to pick up the patched module
            import importlib
            from storageanalyser import desktop
            importlib.reload(desktop)

            with pytest.raises(SystemExit) as exc_info:
                desktop.run_desktop()
            assert exc_info.value.code == 1

    def test_server_process_function_exists(self) -> None:
        """The _run_server function should be importable for multiprocessing."""
        from storageanalyser.desktop import _run_server
        assert callable(_run_server)

    def test_cli_desktop_flag_exists(self) -> None:
        """The --desktop flag should be accepted by the CLI parser."""
        from storageanalyser.cli import main
        import argparse
        # Just verify the flag is recognized by checking help text
        import io
        from contextlib import redirect_stdout
        f = io.StringIO()
        with pytest.raises(SystemExit):
            with redirect_stdout(f):
                sys.argv = ["storageanalyser", "--help"]
                main()
        assert "--desktop" in f.getvalue()
