"""Reporting and output formatting."""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

from storageanalyser.helpers import Colour, human_size
from storageanalyser.models import Category, ScanResult


CATEGORY_LABELS: dict[Category, str] = {
    Category.JUNK_DIR: "🗑  Cache/Junk",
    Category.ARTIFACT: "📦 Build Artifact",
    Category.LARGE_FILE: "💾 Large File",
    Category.STALE_FILE: "🕸  Stale File",
    Category.DUPLICATE: "♊ Duplicate",
    Category.DOWNLOAD: "⬇️  Old Download",
}

CATEGORY_COMMANDS: dict[Category, str] = {
    Category.JUNK_DIR: "rm -rf '{path}'",
    Category.ARTIFACT: "rm -rf '{path}'",
    Category.LARGE_FILE: "rm '{path}'",
    Category.STALE_FILE: "rm '{path}'",
    Category.DUPLICATE: "rm '{path}'",
    Category.DOWNLOAD: "rm -rf '{path}'",
}


def print_report(result: ScanResult, top_n: int) -> None:
    """Pretty-print the analysis to the terminal."""
    print()
    print(Colour.bold("═" * 72))
    print(Colour.bold("  macOS Storage Analyzer — Report"))
    print(Colour.bold("═" * 72))
    print()
    print(f"  Scanned root:    {result.root}")
    print(f"  Files scanned:   {result.total_scanned:,}")
    print(f"  Total size:      {human_size(result.total_size)}")
    print(f"  Scan time:       {result.scan_seconds:.1f}s")
    print(f"  Read errors:     {result.errors:,}")
    print()

    recs = result.recommendations[:top_n]
    if not recs:
        print(Colour.green("  ✓ No significant cleanup recommendations found. Tidy disk!"))
        return

    print(Colour.bold(f"  Top {len(recs)} Cleanup Recommendations"))
    print(Colour.bold(f"  (sorted by impact — estimated reclaimable: "
                      f"{Colour.red(human_size(result.reclaimable))})"))
    print()

    by_cat: dict[Category, int] = defaultdict(int)
    for r in result.recommendations:
        by_cat[r.category] += r.size

    print(Colour.bold("  Breakdown by category:"))
    for cat in Category:
        if cat in by_cat:
            label = CATEGORY_LABELS[cat]
            print(f"    {label:<22} {human_size(by_cat[cat]):>10}")
    print()

    print(Colour.bold("  ─" * 36))
    for i, r in enumerate(recs, 1):
        label = CATEGORY_LABELS[r.category]
        age_str = f" (age: {r.age_days}d)" if r.age_days else ""
        size_str = human_size(r.size)

        display_path = r.path.replace(str(Path.home()), "~")

        print(f"  {Colour.bold(f'{i:>3}.')}  {label}")
        print(f"       {Colour.yellow(display_path)}")
        print(f"       {size_str}{age_str} — {r.reason}")
        print(f"       {Colour.dim(CATEGORY_COMMANDS[r.category].format(path=r.path))}")
        print()

    if result.duplicates:
        print(Colour.bold("  Duplicate Groups Found:"))
        for group in result.duplicates[:10]:
            print(f"    • {group[0].replace(str(Path.home()), '~')}")
            for dup in group[1:]:
                print(f"      ≡ {dup.replace(str(Path.home()), '~')}")
            print()

    print(Colour.bold("  ─" * 36))
    print(Colour.bold("  Quick Cleanup Script"))
    print(Colour.dim("  (Review carefully before running!)"))
    print()
    print(Colour.dim("  # Save this to cleanup.sh, review, then: bash cleanup.sh"))
    for r in recs[:15]:
        cmd = CATEGORY_COMMANDS[r.category].format(path=r.path)
        print(f"  {cmd}  # {human_size(r.size)} — {r.reason}")

    print()
    print(Colour.bold("═" * 72))
    print(Colour.dim("  ⚠  Always review before deleting! Use Finder's Quick Look (Space bar)"))
    print(Colour.dim("     to inspect files. Move to Trash first if unsure: mv <file> ~/.Trash/"))
    print(Colour.bold("═" * 72))
    print()


def print_json(result: ScanResult, top_n: int) -> None:
    """Dump the result as JSON for piping to other tools."""
    output = {
        "root": result.root,
        "total_scanned": result.total_scanned,
        "total_size": result.total_size,
        "total_size_human": human_size(result.total_size),
        "reclaimable": result.reclaimable,
        "reclaimable_human": human_size(result.reclaimable),
        "scan_seconds": round(result.scan_seconds, 2),
        "errors": result.errors,
        "recommendations": [
            {
                "path": r.path,
                "size": r.size,
                "size_human": human_size(r.size),
                "category": r.category.value,
                "reason": r.reason,
                "age_days": r.age_days,
                "priority_score": round(r.priority_score, 2),
            }
            for r in result.recommendations[:top_n]
        ],
        "duplicate_groups": result.duplicates[:20],
    }
    json.dump(output, sys.stdout, indent=2)
    print()
