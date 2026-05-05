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


def upload_blog_to_drive(title: str, content: str, folder_id: Optional[str] = None) -> dict:
    """Upload text content as a Google Doc. Returns the created file metadata."""
    service = _get_service()
    folder_id = folder_id or os.environ.get("GOOGLE_DRIVE_FOLDER_ID", "")
    shared_drive_id = os.environ.get("GOOGLE_SHARED_DRIVE_ID", "")

    file_metadata = {
        "name": title,
        "mimeType": "application/vnd.google-apps.document",
    }
    if folder_id:
        file_metadata["parents"] = [folder_id]

    # Drive API imports content via multipart upload with plain-text body;
    # the conversion to Google Doc format happens server-side.
    from googleapiclient.http import MediaInMemoryUpload

    media = MediaInMemoryUpload(content.encode("utf-8"), mimetype="text/plain", resumable=False)

    try:
        file = (
            service.files()
            .create(body=file_metadata, media_body=media, fields="id, name, webViewLink", supportsAllDrives=True)
            .execute()
        )
        return file
    except HttpError as e:
        raise RuntimeError(f"Drive upload failed: {e}") from e
