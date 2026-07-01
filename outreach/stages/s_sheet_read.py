"""
Standalone script: read all rows from the outreach Google Sheet and print them.
Nothing is written. No other files are touched.

Run from the repo root:
    python outreach/stages/s_sheet_read.py
"""

from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
KEY_PATH = Path(__file__).parents[2] / "secrets" / "legendary-parts-203a804edea2.json"
SHEET_ID = "1uZobVjIeSdAUE0QLuruuSwyC7hF5QEOH02ATYhDA9j0"


def read_sheet() -> list[list[str]]:
    if not KEY_PATH.exists():
        raise FileNotFoundError(
            f"Service account key not found at: {KEY_PATH}\n"
            "Check that the file exists and the path is correct."
        )

    creds = service_account.Credentials.from_service_account_file(
        str(KEY_PATH), scopes=SCOPES
    )

    try:
        service = build("sheets", "v4", credentials=creds)
        result = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=SHEET_ID, range="A:ZZ")
            .execute()
        )
    except HttpError as e:
        status = e.resp.status
        if status == 403:
            raise PermissionError(
                "Access denied (HTTP 403).\n"
                "Confirm the sheet is shared with: seo-forge-writer@legendary-parts.iam.gserviceaccount.com\n"
                f"Raw error: {e}"
            ) from e
        if status == 404:
            raise FileNotFoundError(
                f"Sheet not found (HTTP 404). Check that SHEET_ID is correct: {SHEET_ID}\n"
                f"Raw error: {e}"
            ) from e
        raise RuntimeError(
            f"Google Sheets API error (HTTP {status}): {e.reason}\nRaw error: {e}"
        ) from e

    rows = result.get("values")
    if not rows:
        raise RuntimeError(
            "Sheet returned no data.\n"
            "Possible causes:\n"
            "  • The sheet is empty\n"
            "  • The service account was not granted access (share with seo-forge-writer@legendary-parts.iam.gserviceaccount.com)\n"
            f"  • Wrong sheet ID: {SHEET_ID}"
        )

    return rows


def main() -> None:
    rows = read_sheet()

    header, *data_rows = rows

    print(f"HEADER: {header}")
    print()

    for i, row in enumerate(data_rows, start=1):
        print(f"ROW {i}: {row}")

    print()
    print(f"Read {len(data_rows)} rows from sheet.")


if __name__ == "__main__":
    main()
