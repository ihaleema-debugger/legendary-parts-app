import os
from typing import Optional
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2 import service_account

SCOPES = ["https://www.googleapis.com/auth/drive"]


def _get_service():
    key_path = os.environ["GOOGLE_SERVICE_ACCOUNT_PATH"]
    creds = service_account.Credentials.from_service_account_file(key_path, scopes=SCOPES)
    return build("drive", "v3", credentials=creds)


def get_doc_folder_id(doc_id: str) -> Optional[str]:
    """Return the Drive folder ID of the doc's first parent, or None."""
    service = _get_service()
    try:
        meta = service.files().get(
            fileId=doc_id, fields="parents", supportsAllDrives=True
        ).execute()
    except HttpError as e:
        raise RuntimeError(f"Could not fetch parents for doc {doc_id!r}: {e}") from e
    parents = meta.get("parents", [])
    return parents[0] if parents else None


def find_files_in_folder(folder_id: str, name_prefix: str) -> list:
    """List Google Docs in `folder_id` whose name starts with `name_prefix`.

    Returns a list of dicts: [{id, name, locale}, ...] where locale is the
    suffix after the last '--' (e.g. 'de' for 'blog-name--de').
    Skips files whose names don't match the `--XX` pattern.
    """
    service = _get_service()
    query = (
        f"'{folder_id}' in parents "
        f"and name contains '{name_prefix}' "
        f"and mimeType = 'application/vnd.google-apps.document' "
        f"and trashed = false"
    )
    try:
        results = service.files().list(
            q=query,
            fields="files(id, name)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
            corpora="allDrives",
            pageSize=100,
        ).execute()
    except HttpError as e:
        raise RuntimeError(f"Drive list failed for folder {folder_id!r}: {e}") from e

    matches = []
    for f in results.get("files", []):
        name = f["name"]
        if not name.startswith(name_prefix):
            continue
        # extract locale from the trailing --XX
        if "--" not in name:
            continue
        locale = name.rsplit("--", 1)[-1].strip().lower()
        # accept only short locale codes (2 chars, possibly with region like pt-br)
        if not (2 <= len(locale) <= 5):
            continue
        matches.append({"id": f["id"], "name": name, "locale": locale})
    return matches


def export_doc_as_html(doc_id: str) -> str:
    """Export a Google Doc as HTML. Returns the raw HTML string."""
    service = _get_service()
    try:
        data = service.files().export(
            fileId=doc_id, mimeType="text/html"
        ).execute()
    except HttpError as e:
        raise RuntimeError(f"Drive export failed for doc {doc_id!r}: {e}") from e
    # export() returns bytes
    if isinstance(data, bytes):
        return data.decode("utf-8")
    return data


def upload_json_to_drive(filename: str, data: dict, folder_id: Optional[str] = None) -> dict:
    """Upload a dict as a raw JSON file to Drive. Returns created file metadata.

    Unlike upload_blog_to_drive, this does NOT convert to a Google Doc — it
    stores a plain application/json file so the bundle remains machine-readable.
    """
    import json
    from googleapiclient.http import MediaInMemoryUpload

    service = _get_service()
    folder_id = folder_id or os.environ.get("GOOGLE_DRIVE_FOLDER_ID", "")
    shared_drive_id = os.environ.get("GOOGLE_SHARED_DRIVE_ID", "")

    file_metadata: dict = {
        "name": filename,
        "mimeType": "application/json",
    }
    if folder_id:
        file_metadata["parents"] = [folder_id]

    content_bytes = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    media = MediaInMemoryUpload(content_bytes, mimetype="application/json", resumable=False)

    try:
        file = (
            service.files()
            .create(
                body=file_metadata,
                media_body=media,
                fields="id, name, webViewLink",
                supportsAllDrives=True,
            )
            .execute()
        )
        return file
    except HttpError as e:
        raise RuntimeError(f"Drive JSON upload failed: {e}") from e


def create_doc(title: str, folder_id: Optional[str] = None) -> dict:
    """Create an empty Google Doc with the given title. Returns file metadata dict.

    Returns dict with keys: id, name, webViewLink.
    Raises RuntimeError on Drive API error.
    """
    service = _get_service()
    folder_id = folder_id or os.environ.get("GOOGLE_DRIVE_FOLDER_ID", "")

    file_metadata: dict = {
        "name": title,
        "mimeType": "application/vnd.google-apps.document",
    }
    if folder_id:
        file_metadata["parents"] = [folder_id]

    try:
        file = service.files().create(
            body=file_metadata,
            fields="id, name, webViewLink",
            supportsAllDrives=True,
        ).execute()
        return file
    except HttpError as e:
        raise RuntimeError(f"Drive doc creation failed: {e}") from e


def _blocks_to_html(blocks: list) -> str:
    """Convert JSON blocks (from seo-blog-writer) to HTML for Drive import."""
    import html as html_lib
    parts = ["<html><body>"]
    for block in blocks:
        level = block.get("level", "p")
        text = block.get("text", "")
        links = block.get("links", [])

        # Embed hyperlinks: replace each anchor text with <a href> in order
        for link in links:
            anchor = link.get("anchor", "")
            url = link.get("url", "")
            if anchor and url and anchor in text:
                escaped_anchor = html_lib.escape(anchor)
                escaped_url = html_lib.escape(url)
                text = text.replace(anchor, f'<a href="{escaped_url}">{escaped_anchor}</a>', 1)
        # Escape any remaining bare ampersands / angle brackets not inside tags
        # (simple approach: only escape text outside existing <a> tags is tricky,
        #  so we rely on anchor/url values being clean URLs)

        tag_map = {"title": "h1", "h2": "h2", "h3": "h3", "h4": "h4", "p": "p"}
        tag = tag_map.get(level, "p")
        parts.append(f"<{tag}>{text}</{tag}>")

    parts.append("</body></html>")
    return "\n".join(parts)


def upload_blog_to_drive(title: str, content: str, folder_id: Optional[str] = None) -> dict:
    """Upload blog content as a Google Doc. Accepts raw text or JSON blocks format."""
    import json as _json
    service = _get_service()
    folder_id = folder_id or os.environ.get("GOOGLE_DRIVE_FOLDER_ID", "")

    # Detect JSON blocks format produced by seo-blog-writer and convert to HTML
    # so Drive preserves heading styles (h1/h3/h4) instead of showing raw JSON.
    try:
        parsed = _json.loads(content)
        if isinstance(parsed, dict) and "blocks" in parsed:
            content = _blocks_to_html(parsed["blocks"])
            mimetype = "text/html"
        else:
            mimetype = "text/plain"
    except (_json.JSONDecodeError, ValueError):
        mimetype = "text/plain"

    file_metadata = {
        "name": title,
        "mimeType": "application/vnd.google-apps.document",
    }
    if folder_id:
        file_metadata["parents"] = [folder_id]

    from googleapiclient.http import MediaInMemoryUpload
    media = MediaInMemoryUpload(content.encode("utf-8"), mimetype=mimetype, resumable=False)

    try:
        file = (
            service.files()
            .create(body=file_metadata, media_body=media, fields="id, name, webViewLink", supportsAllDrives=True)
            .execute()
        )
        # Grant "anyone with link" read access so the doc is openable without
        # individual email permissions being set up per recipient.
        service.permissions().create(
            fileId=file["id"],
            body={"type": "anyone", "role": "reader"},
            supportsAllDrives=True,
        ).execute()
        return file
    except HttpError as e:
        raise RuntimeError(f"Drive upload failed: {e}") from e
