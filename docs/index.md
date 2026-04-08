# storageanalyser

Storage Analyzer & Cleanup Recommender for **macOS** and **Windows**.

Scans your home directory (and optionally other paths) to find:

- Large files hogging space
- Stale files you haven't touched in ages
- Known junk directories (caches, logs, build artifacts, node_modules, etc.)
- Duplicate files (by size + hash) with wasted space calculation
- Old downloads sitting in ~/Downloads

Outputs a prioritised list of cleanup recommendations with estimated space savings.

## Installation

```bash
pip install storageanalyser
```

For the desktop app (runs in its own window):

```bash
pip install storageanalyser[desktop]
```

## Quick Start

```bash
# Scan home directory
storageanalyser

# Launch the web interface in your browser
storageanalyser --web

# Launch as a desktop app
storageanalyser --desktop

# Include duplicate detection
storageanalyser --duplicates

# Show which directories are skipped by default
storageanalyser --list-skipped
```

## Contents

```{toctree}
:maxdepth: 2

usage
web
```
