# storageanalyser

macOS Storage Analyzer & Cleanup Recommender.

Scans your home directory (and optionally other paths) to find large files, stale files,
junk directories, build artifacts, duplicates, and old downloads. Outputs a prioritised
list of cleanup recommendations with estimated space savings.

## Installation

```bash
uv pip install -e ".[dev]"
```

## Usage

```bash
storageanalyser                           # Scan home directory
storageanalyser /Volumes/Data             # Scan a specific path
storageanalyser --top 30                  # Show top 30 recommendations
storageanalyser --duplicates              # Include duplicate detection
storageanalyser --json                    # JSON output
storageanalyser --threshold 50            # Flag files over 50 MB
storageanalyser --ignoredir node_modules  # Skip directories
storageanalyser --includedir CloudStorage # Override a default-skipped directory
storageanalyser --list-skipped            # Show directories skipped by default
storageanalyser --web                     # Launch the web interface
storageanalyser --web --port 9000         # Web interface on a custom port
```

## Web Interface

Launch the web UI with `storageanalyser --web`. Features include:

- Live scan progress with cancel support
- Disk usage pie chart and summary cards
- Category breakdown bar chart
- Clickable treemap (click to jump to the recommendation)
- Recommendations organized by category tabs with per-tab sorting
- Short/full path toggle for readability
- Duplicate detection with full path listing and wasted space calculation
- Configurable skipped directories (override defaults to include cloud storage, etc.)
- Cleanup script download for selected items
- Google Drive integration and cross-environment deduplication

### Screenshots

**Scan form** with configurable skipped directories:

![Scan Form](https://raw.githubusercontent.com/jdrumgoole/storageanalyser/main/docs/screenshot-scan-form.png)

**Results summary** with disk usage pie chart and summary cards:

![Results Summary](https://raw.githubusercontent.com/jdrumgoole/storageanalyser/main/docs/screenshot-results-summary.png)

**Category breakdown** and clickable **treemap**:

![Category & Treemap](https://raw.githubusercontent.com/jdrumgoole/storageanalyser/main/docs/screenshot-category-treemap.png)

**Recommendations** organized by category tabs:

![Recommendations](https://raw.githubusercontent.com/jdrumgoole/storageanalyser/main/docs/screenshot-recommendations.png)

**Duplicate detection** with copy count and wasted space:

![Duplicates](https://raw.githubusercontent.com/jdrumgoole/storageanalyser/main/docs/screenshot-duplicates.png)

## Skipped Directories

By default, certain directories are skipped during scans (cloud storage, macOS system
directories, Photos library, etc.). Use `--list-skipped` to see them and `--includedir`
to override:

```bash
storageanalyser --list-skipped
storageanalyser --includedir Music --includedir Movies
```

## Development

```bash
uv sync --extra dev
uv run python -m invoke test.run
uv run python -m invoke docs.build
```

## Documentation

Full documentation is in the `docs/` directory. Build with Sphinx:

```bash
uv run python -m invoke docs.build
```
