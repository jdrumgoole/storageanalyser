"""Google Drive scanner — OAuth2 auth and file listing."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from storageanalyser.helpers import human_size
from storageanalyser.platform import config_dir

SCOPES = ["https://www.googleapis.com/auth/drive.metadata.readonly"]
CONFIG_DIR = config_dir()
CREDENTIALS_FILE = CONFIG_DIR / "google_credentials.json"
TOKEN_FILE = CONFIG_DIR / "google_token.json"


def is_configured() -> bool:
    """Check if Google Drive credentials file exists."""
    return CREDENTIALS_FILE.exists()


def has_token() -> bool:
    """Check if we have a saved auth token."""
    return TOKEN_FILE.exists()


def save_credentials(credentials_json: dict) -> None:
    """Save the OAuth2 client credentials JSON."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CREDENTIALS_FILE.write_text(json.dumps(credentials_json, indent=2))


def authenticate(port: int = 0) -> Any:
    """Run the OAuth2 installed-app flow and return an authenticated Drive service.

    Opens a browser for consent on first run, saves token for reuse.
    """
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_FILE.exists():
                raise FileNotFoundError(
                    "Google credentials not configured. "
                    "Upload your OAuth2 credentials JSON via the web UI."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_FILE), SCOPES
            )
            creds = flow.run_local_server(port=port)

        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(creds.to_json())

    return build("drive", "v3", credentials=creds)


def get_storage_quota(service: Any) -> dict:
    """Get the account's storage quota info."""
    about = service.about().get(fields="storageQuota, user").execute()
    quota = about.get("storageQuota", {})
    user = about.get("user", {})
    limit = int(quota.get("limit", 0))
    usage = int(quota.get("usage", 0))
    usage_in_drive = int(quota.get("usageInDrive", 0))
    usage_in_trash = int(quota.get("usageInDriveTrash", 0))
    free = max(0, limit - usage) if limit else 0

    return {
        "email": user.get("emailAddress", ""),
        "limit": limit,
        "limit_human": human_size(limit) if limit else "Unlimited",
        "usage": usage,
        "usage_human": human_size(usage),
        "usage_in_drive": usage_in_drive,
        "usage_in_drive_human": human_size(usage_in_drive),
        "usage_in_trash": usage_in_trash,
        "usage_in_trash_human": human_size(usage_in_trash),
        "free": free,
        "free_human": human_size(free) if limit else "Unlimited",
    }


def scan_drive(
    service: Any,
    *,
    find_duplicates: bool = False,
    progress_callback: Any | None = None,
) -> dict:
    """Scan Google Drive and return a size breakdown with file details.

    Returns a dict with quota info, files sorted by size, and type breakdown.
    """
    quota = get_storage_quota(service)

    files: list[dict] = []
    page_count = 0
    total_files = 0

    request = service.files().list(
        pageSize=1000,
        q="trashed = false",
        fields=(
            "nextPageToken, "
            "files(id, name, mimeType, size, quotaBytesUsed, "
            "modifiedTime, webViewLink, parents, md5Checksum)"
        ),
    )

    while request is not None:
        response = request.execute()
        page_count += 1
        batch = response.get("files", [])
        total_files += len(batch)

        for f in batch:
            size = int(f.get("quotaBytesUsed", 0) or f.get("size", 0) or 0)
            files.append({
                "id": f["id"],
                "name": f.get("name", ""),
                "mime_type": f.get("mimeType", ""),
                "md5": f.get("md5Checksum"),
                "size": size,
                "size_human": human_size(size),
                "modified_time": f.get("modifiedTime", ""),
                "web_view_link": f.get("webViewLink", ""),
            })

        if progress_callback:
            progress_callback(
                "gdrive", f"Scanned {total_files:,} files from Google Drive...",
                total_files, 0,
            )

        request = service.files().list_next(request, response)

    # Sort by size descending
    files.sort(key=lambda f: f["size"], reverse=True)

    # Build type breakdown
    type_breakdown: dict[str, int] = {}
    TYPE_LABELS = {
        "application/vnd.google-apps.document": "Google Docs",
        "application/vnd.google-apps.spreadsheet": "Google Sheets",
        "application/vnd.google-apps.presentation": "Google Slides",
        "application/vnd.google-apps.form": "Google Forms",
        "application/vnd.google-apps.drawing": "Google Drawings",
        "application/vnd.google-apps.folder": "Folders",
        "application/pdf": "PDFs",
        "image/jpeg": "Images (JPEG)",
        "image/png": "Images (PNG)",
        "video/mp4": "Videos (MP4)",
        "application/zip": "Archives (ZIP)",
    }

    for f in files:
        mime = f["mime_type"]
        label = TYPE_LABELS.get(mime)
        if not label:
            if mime.startswith("image/"):
                label = "Images (other)"
            elif mime.startswith("video/"):
                label = "Videos (other)"
            elif mime.startswith("audio/"):
                label = "Audio"
            elif mime.startswith("application/vnd.google-apps."):
                label = "Google Workspace (other)"
            else:
                label = "Other"
        type_breakdown[label] = type_breakdown.get(label, 0) + f["size"]

    total_size = sum(f["size"] for f in files)

    # Duplicate detection by MD5
    duplicates: list[dict] = []
    duplicate_savings = 0
    if find_duplicates:
        from collections import defaultdict
        md5_groups: dict[str, list[dict]] = defaultdict(list)
        for f in files:
            if f.get("md5") and f["size"] > 0:
                md5_groups[f["md5"]].append(f)

        for md5, group in sorted(
            md5_groups.items(), key=lambda x: x[1][0]["size"], reverse=True
        ):
            if len(group) < 2:
                continue
            savings = group[0]["size"] * (len(group) - 1)
            duplicate_savings += savings
            duplicates.append({
                "md5": md5,
                "size": group[0]["size"],
                "size_human": group[0]["size_human"],
                "count": len(group),
                "savings": savings,
                "savings_human": human_size(savings),
                "files": group,
            })

    return {
        "quota": quota,
        "total_files": total_files,
        "total_size": total_size,
        "total_size_human": human_size(total_size),
        "type_breakdown": dict(
            sorted(type_breakdown.items(), key=lambda x: x[1], reverse=True)
        ),
        "files": files,
        "duplicates": duplicates[:100],
        "duplicate_count": len(duplicates),
        "duplicate_savings": duplicate_savings,
        "duplicate_savings_human": human_size(duplicate_savings),
    }


def disconnect() -> None:
    """Remove saved token and credentials."""
    TOKEN_FILE.unlink(missing_ok=True)
