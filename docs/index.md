# storageanalyser

macOS Storage Analyzer & Cleanup Recommender.

Scans your home directory (and optionally other paths) to find:

- Large files hogging space
- Stale files you haven't touched in ages
- Known junk directories (caches, logs, build artifacts, node_modules, etc.)
- Duplicate files (by size + hash) with wasted space calculation
- Old downloads sitting in ~/Downloads

Outputs a prioritised list of cleanup recommendations with estimated space savings.

## Installation

```bash
uv pip install -e ".[dev]"
```

## Quick Start

```bash
# Scan home directory
storageanalyser

# Scan a specific path
storageanalyser /Volumes/Data

# Show top 30 recommendations
storageanalyser --top 30

# Include duplicate detection (slower)
storageanalyser --duplicates

# JSON output
storageanalyser --json

# Lower the large file threshold to 50 MB
storageanalyser --threshold 50

# Ignore specific directories
storageanalyser --ignoredir node_modules --ignoredir ~/Photos

# Include a default-skipped directory
storageanalyser --includedir CloudStorage

# Show which directories are skipped by default
storageanalyser --list-skipped

# Launch the web interface
storageanalyser --web
```

## Contents

```{toctree}
:maxdepth: 2

usage
web
```
