"""Command-line interface for storageanalyser."""

from __future__ import annotations

import argparse
import os
import signal
import sys
from pathlib import Path

from storageanalyser.analyzer import DiskAnalyzer
from storageanalyser.constants import ONE_MB
from storageanalyser.helpers import Colour
from storageanalyser.report import print_json, print_report

# Module-level reference so the signal handler can cancel an active scan.
_active_analyzer: DiskAnalyzer | None = None


def _handle_sigint(signum: int, frame: object) -> None:
    """Handle Ctrl-C gracefully.

    First press: cancel the running scan so partial results can be shown.
    Second press: force-exit immediately.
    """
    global _active_analyzer
    if _active_analyzer is not None and not _active_analyzer.cancelled:
        _active_analyzer.cancelled = True
        print("\nInterrupted — finishing up…", file=sys.stderr)
        # Re-register so a second Ctrl-C force-exits
        signal.signal(signal.SIGINT, _force_exit)
    else:
        _force_exit(signum, frame)


def _force_exit(signum: int, frame: object) -> None:
    """Force-exit on second Ctrl-C."""
    print("\nForce quit.", file=sys.stderr)
    os._exit(130)


def main() -> None:
    signal.signal(signal.SIGINT, _handle_sigint)

    parser = argparse.ArgumentParser(
        description="macOS Storage Analyzer — find what's eating your disk",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  %(prog)s                           Scan home directory
  %(prog)s /Volumes/ExternalDrive    Scan a specific path
  %(prog)s --top 50 --duplicates     Deep scan with dupe detection
  %(prog)s --json | jq '.recommendations[:5]'
  %(prog)s --threshold 50            Flag files over 50 MB (default: 100)
  %(prog)s --ignoredir node_modules --ignoredir ~/Photos
""",
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=str(Path.home()),
        help="Root directory to scan (default: ~/)",
    )
    parser.add_argument(
        "--top", "-n",
        type=int,
        default=20,
        help="Number of recommendations to show (default: 20)",
    )
    parser.add_argument(
        "--duplicates", "-d",
        action="store_true",
        help="Enable duplicate file detection (slower — hashes file heads)",
    )
    parser.add_argument(
        "--threshold", "-t",
        type=int,
        default=100,
        help="Large file threshold in MB (default: 100)",
    )
    parser.add_argument(
        "--json", "-j",
        action="store_true",
        help="Output results as JSON",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable coloured output",
    )
    parser.add_argument(
        "--workers", "-w",
        type=int,
        default=8,
        help="Thread pool size for parallel I/O (default: 8)",
    )
    parser.add_argument(
        "--ignoredir",
        action="append",
        default=[],
        metavar="DIR",
        help="Directory to skip (repeatable). Absolute path or bare name "
             "matched anywhere, e.g. --ignoredir node_modules --ignoredir ~/Photos",
    )
    parser.add_argument(
        "--includedir",
        action="append",
        default=[],
        metavar="DIR",
        help="Override a default-skipped directory so it gets scanned "
             "(repeatable). Use --list-skipped to see the defaults, "
             "e.g. --includedir CloudStorage --includedir Music",
    )
    parser.add_argument(
        "--list-skipped",
        action="store_true",
        help="Print the directories that are skipped by default and exit",
    )
    parser.add_argument(
        "--web",
        action="store_true",
        help="Launch the web interface in a browser",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8888,
        help="Port for the web server (default: 8888, used with --web)",
    )

    args = parser.parse_args()

    if args.list_skipped:
        from storageanalyser.constants import DEFAULT_SKIP_DIRS
        print("Directories skipped by default (use --includedir NAME to override):\n")
        for name, reason in sorted(DEFAULT_SKIP_DIRS.items()):
            print(f"  {name:40s} {reason}")
        return

    if args.web:
        from storageanalyser.web.server import run as run_web
        run_web(open_browser=True, port=args.port)
        return

    if args.no_color:
        Colour.enabled = False

    root = Path(args.path)
    if not root.exists():
        print(f"Error: {root} does not exist", file=sys.stderr)
        sys.exit(1)

    # Merge remembered ignore dirs with any explicitly provided ones
    from storageanalyser.cache import IgnoreDirsCache
    ignore_cache = IgnoreDirsCache()
    root_str = str(root.expanduser().resolve())
    ignore_dirs = args.ignoredir
    if not ignore_dirs:
        ignore_dirs = ignore_cache.get(root_str)
        if ignore_dirs and not args.json:
            print(Colour.cyan(
                f"Using remembered ignore dirs: {', '.join(ignore_dirs)}"
            ))

    global _active_analyzer
    analyzer = DiskAnalyzer(
        root,
        top_n=args.top,
        find_duplicates=args.duplicates,
        large_threshold=args.threshold * ONE_MB,
        progress=not args.json,
        workers=args.workers,
        ignore_dirs=ignore_dirs,
        include_dirs=args.includedir,
    )
    _active_analyzer = analyzer

    result = analyzer.scan()
    _active_analyzer = None

    # Remember ignore dirs for next run
    ignore_cache.update(root_str, ignore_dirs)

    if analyzer.cancelled:
        if not args.json:
            print(Colour.yellow("Scan interrupted — showing partial results.\n"))
    if args.json:
        print_json(result, args.top)
    else:
        print_report(result, args.top)

    if analyzer.cancelled:
        sys.exit(130)


if __name__ == "__main__":
    main()
