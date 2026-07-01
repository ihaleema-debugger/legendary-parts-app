"""
Swap seam for the outreach pipeline.
Call get_gmail_service() to get an authenticated Gmail API client.
Which mailbox it acts on is determined entirely by which token file is loaded.
"""
import json
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.readonly",
]

_DIR = Path(__file__).resolve().parent
_DEFAULT_TOKEN  = _DIR / "secrets" / "token_haleema.json"
_DEFAULT_SECRET = _DIR / "secrets" / "client_secret.json"


def get_gmail_service(
    token_path=_DEFAULT_TOKEN,
    client_secret_path=_DEFAULT_SECRET,
):
    token_path = Path(token_path)

    if not token_path.exists():
        raise FileNotFoundError(
            f"Token file not found: {token_path}\n"
            "Run mint_token.py first to authorise this mailbox."
        )

    creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_data = json.loads(creds.to_json())
        token_path.write_text(json.dumps(token_data, indent=2))

    return build("gmail", "v1", credentials=creds)


if __name__ == "__main__":
    service = get_gmail_service()
    profile = service.users().getProfile(userId="me").execute()
    print(f"Authenticated as: {profile['emailAddress']}")
    print("gmail_client seam OK.")
