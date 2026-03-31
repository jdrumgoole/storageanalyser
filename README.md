# storageanalyser

Storage Analyzer & Cleanup Recommender for **macOS** and **Windows**.

Scans your home directory (and optionally other paths) to find large files, stale files,
junk directories, build artifacts, duplicates, and old downloads. Outputs a prioritised
list of cleanup recommendations with estimated space savings.

Platform-aware: automatically detects OS-specific cache locations, system directories,
and generates the appropriate cleanup script (bash on macOS, PowerShell on Windows).

## Installation

```bash
pip install storageanalyser
```

## Usage

```bash
storageanalyser                           # Scan home directory
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

Scan a specific drive or folder:

```bash
# macOS
storageanalyser /Volumes/ExternalDrive

# Windows
storageanalyser D:\Data
```

## Platform Support

| Feature | macOS | Windows |
|---------|-------|---------|
| CLI scanner | Yes | Yes |
| Web interface | Yes | Yes |
| OS-specific caches | Library/Caches, .Trash, Xcode, etc. | AppData/Local/Temp, CrashDumps, etc. |
| Cloud storage skip | iCloud, Google Drive, OneDrive, Dropbox | Google Drive, OneDrive, Dropbox |
| System dir skip | .Spotlight-V100, .fseventsd, Photos Library | $Recycle.Bin, System Volume Information |
| Cleanup script | Bash (.sh) | PowerShell (.ps1) |
| Duplicate detection | Yes | Yes |
| Google Drive integration | Yes | Yes |

## Web Interface

Launch the web UI with `storageanalyser --web`. Features include:

- Live scan progress with cancel support
- Duplicate hashing progress bar
- Disk usage pie chart and summary cards
- Category breakdown bar chart
- Clickable treemap (click to jump to the recommendation)
- Recommendations organized by category tabs with per-tab sorting
- Short/full path toggle for readability
- Duplicate detection with full path listing and wasted space calculation
- Configurable skipped directories (override defaults to include cloud storage, etc.)
- Cleanup script download for selected items (bash or PowerShell)
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

By default, certain directories are skipped during scans. The list is platform-specific
(cloud storage, OS system directories, managed libraries, etc.). Use `--list-skipped`
to see the defaults for your OS and `--includedir` to override:

```bash
storageanalyser --list-skipped
storageanalyser --includedir Music --includedir Movies
```

## Documentation

Full documentation is available at [storageanalyser.readthedocs.io](https://storageanalyser.readthedocs.io/).
