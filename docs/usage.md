# Usage

## Command-Line Options

| Option | Description |
|--------|-------------|
| `path` | Root directory to scan (default: `~/`) |
| `--top, -n` | Number of recommendations to show (default: 20) |
| `--duplicates, -d` | Enable duplicate file detection (slower) |
| `--threshold, -t` | Large file threshold in MB (default: 100) |
| `--json, -j` | Output results as JSON |
| `--no-color` | Disable coloured output |
| `--workers, -w` | Thread pool size for parallel I/O (default: 8) |
| `--ignoredir` | Directory to skip (repeatable) |
| `--includedir` | Override a default-skipped directory so it gets scanned (repeatable) |
| `--list-skipped` | Print directories skipped by default and exit |
| `--web` | Launch the web interface in a browser |
| `--port` | Port for the web server (default: 8888, used with `--web`) |

## Categories

storageanalyser classifies findings into these categories:

- **Cache/Junk** - Known cache and junk directories (Library/Caches, .Trash, etc.)
- **Build Artifact** - Build and dependency artifacts (node_modules, __pycache__, etc.)
- **Large File** - Files exceeding the threshold size
- **Stale File** - Files not accessed in over a year
- **Duplicate** - Files with identical content (shows copy count, per-file size, and total wasted space)
- **Old Download** - Items in ~/Downloads older than 6 months

## Priority Score

Recommendations are ranked by a priority score that combines file size with category-based multipliers:

- **Base**: file size in MB
- **3x** for caches/junk and build artifacts (almost always safe to delete)
- **2x** for duplicates
- **1.5x** if the file hasn't been accessed in over a year

Higher score = safer and more impactful to clean up.

## Skipped Directories

Certain directories are skipped by default to avoid scanning cloud-synced storage,
macOS system directories, and managed libraries. Use `--list-skipped` to see the
full list:

```bash
storageanalyser --list-skipped
```

Output:

```
Directories skipped by default (use --includedir NAME to override):

  .DocumentRevisions-V100                  macOS document versioning data
  .Spotlight-V100                          Spotlight index data
  .fseventsd                               macOS filesystem event logs
  CloudStorage                             Cloud-synced storage (Google Drive, iCloud, OneDrive, Dropbox)
  Movies                                   macOS Movies folder
  Music                                    macOS Music library
  Photos Library.photoslibrary             macOS Photos library (managed by Photos.app)
```

To include a skipped directory in a scan:

```bash
storageanalyser --includedir CloudStorage --includedir Music
```

**Note**: Files under `~/Library/CloudStorage/` (Google Drive, iCloud Drive, OneDrive, Dropbox)
are managed by cloud sync. Even when they appear local, deleting them may also delete the cloud
copy. In stream mode, files may show large apparent sizes but consume little actual disk space.

## JSON Output

Use `--json` to get machine-readable output suitable for piping to other tools:

```bash
storageanalyser --json | jq '.recommendations[:5]'
```
