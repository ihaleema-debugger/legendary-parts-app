"""Locate blog files in Google Drive without downloading them.

Reuses the service-account auth from app.services.drive_uploader._get_service.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.drive_uploader import _get_service  # noqa: E402


def fetch_blog_files(
    blog_stem: str,
    drive_folder_path: str,
    shared_drive_name: str,
) -> list[dict]:
    """Find Google Doc files matching blog_stem in a shared drive folder.

    Args:
        blog_stem: filename prefix, e.g.
            "harley-davidson-vrsc-v-rod-complete-buyers-and-owners-guide"
        drive_folder_path: slash-separated path relative to shared drive root,
            e.g. "12. Claude Blogs / Approved Blogs"
        shared_drive_name: case-insensitive shared drive name,
            e.g. "shared drive with Claude"

    Returns:
        List of {file_id, locale, name} dicts, sorted by locale.
    """
    service = _get_service()
    drive_id = _resolve_shared_drive(service, shared_drive_name)
    folder_id = _resolve_folder_path(service, drive_id, drive_folder_path)
    files = _list_docs(service, folder_id, drive_id)

    results = []
    for f in files:
        name = f["name"]
        if not name.startswith(blog_stem):
            continue
        suffix = name[len(blog_stem):]
        if not suffix.startswith("--"):
            continue
        locale = suffix[2:].split(".")[0].strip().lower()
        if not (2 <= len(locale) <= 5):
            continue
        results.append({"file_id": f["id"], "locale": locale, "name": name})

    return sorted(results, key=lambda x: x["locale"])


def fetch_blog_files_by_id(
    blog_stem: str,
    folder_id: str,
) -> list[dict]:
    """Find Google Doc files matching blog_stem using a direct Drive folder ID.

    Bypasses path traversal — useful when the folder ID is already known.
    Reads GOOGLE_SHARED_DRIVE_ID from the environment to satisfy the Drive API's
    corpora=drive requirement.
    """
    drive_id = os.environ.get("GOOGLE_SHARED_DRIVE_ID", "")
    if not drive_id:
        raise RuntimeError(
            "GOOGLE_SHARED_DRIVE_ID is not set. Add it to .env."
        )
    service = _get_service()
    files = _list_docs(service, folder_id, drive_id)

    results = []
    for f in files:
        name = f["name"]
        if not name.startswith(blog_stem):
            continue
        suffix = name[len(blog_stem):]
        if not suffix.startswith("--"):
            continue
        locale = suffix[2:].split(".")[0].strip().lower()
        if not (2 <= len(locale) <= 5):
            continue
        results.append({"file_id": f["id"], "locale": locale, "name": name})

    return sorted(results, key=lambda x: x["locale"])


# ── private helpers ───────────────────────────────────────────────────────────

def _resolve_shared_drive(service, name: str) -> str:
    result = service.drives().list(pageSize=50).execute()
    for d in result.get("drives", []):
        if d["name"].lower() == name.lower():
            return d["id"]
    available = [d["name"] for d in result.get("drives", [])]
    raise RuntimeError(
        f"Shared drive {name!r} not found. Available: {available}"
    )


def _resolve_folder_path(service, drive_id: str, folder_path: str) -> str:
    """Traverse slash-separated folder path within a shared drive."""
    segments = [s.strip() for s in folder_path.split("/") if s.strip()]
    current_id = drive_id
    for segment in segments:
        current_id = _find_subfolder(service, current_id, segment, drive_id)
    return current_id


def _find_subfolder(service, parent_id: str, name: str, drive_id: str) -> str:
    """List all subfolders of parent and return the one with exact name.

    Uses a full listing rather than a name= query filter — the Drive API's
    name= filter is unreliable for nested shared-drive folders.
    """
    q = (
        f"'{parent_id}' in parents "
        f"and mimeType = 'application/vnd.google-apps.folder' "
        f"and trashed = false"
    )
    r = service.files().list(
        q=q,
        fields="files(id, name)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
        corpora="drive",
        driveId=drive_id,
        pageSize=200,
    ).execute()
    folders = r.get("files", [])
    match = next((f for f in folders if f["name"].strip() == name.strip()), None)
    if not match:
        available = sorted(f["name"] for f in folders)
        raise RuntimeError(
            f"Folder {name!r} not found under {parent_id!r}. "
            f"Available subfolders: {available}"
        )
    return match["id"]


def _list_docs(service, folder_id: str, drive_id: str) -> list[dict]:
    """List all non-trashed Google Docs directly inside folder_id."""
    q = (
        f"'{folder_id}' in parents "
        f"and mimeType = 'application/vnd.google-apps.document' "
        f"and trashed = false"
    )
    r = service.files().list(
        q=q,
        fields="files(id, name)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
        corpora="drive",
        driveId=drive_id,
        pageSize=200,
    ).execute()
    return r.get("files", [])
