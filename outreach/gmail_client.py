"""
Swap seam for the outreach pipeline.
Call get_gmail_service() to get an authenticated Gmail API client.
Which mailbox it acts on is determined entirely by which token file is loaded.

LIVE-GMAIL GATE: get_gmail_service() refuses to authenticate unless
OUTREACH_ALLOW_LIVE_GMAIL is set to the exact value below in the process's
real environment. Added after a missed test mock silently created a live
Gmail draft (2026-07-09). Every test-reachable path in this codebase either
patches get_gmail_service directly or injects a fake service object
(outreach/poller.py's run_poll(_service=...) pattern) and so never executes
this check — it only fires when a mock is missing.

This value must NEVER be set via .env. hook_poller.py calls load_dotenv()
at import time, before it even checks for --test, so anything in .env is
live during that file's own test runs too. hook_poller.py strips this exact
variable back out immediately after load_dotenv() if .env (not the real
environment) is what set it — see the comment there. Any other future
caller that both loads .env and sits upstream of get_gmail_service() must
apply the same stripping, or this gate is only cosmetic for that path.
"""
import json
import os
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

LIVE_GATE_VAR   = "OUTREACH_ALLOW_LIVE_GMAIL"
LIVE_GATE_VALUE = "i-know-this-hits-live-gmail"


def get_gmail_service(
    token_path=_DEFAULT_TOKEN,
    client_secret_path=_DEFAULT_SECRET,
):
    if os.environ.get(LIVE_GATE_VAR) != LIVE_GATE_VALUE:
        raise RuntimeError(
            "get_gmail_service() refused: no live Gmail client will be created.\n"
            "\n"
            "This codebase requires explicit opt-in before authenticating to a "
            "real Gmail account — a missed test mock has silently created "
            "live drafts before.\n"
            "\n"
            "Running a real pipeline (run_poller.sh, hook_poller.py by hand, or "
            "`python3 outreach/run_outreach.py`)? Set exactly:\n"
            "\n"
            f"    {LIVE_GATE_VAR}={LIVE_GATE_VALUE}\n"
            "\n"
            "in the environment that invokes this process — inline, or "
            "inside run_poller.sh's own script body (next to its PYTHONPATH= "
            "line). Do NOT put this in .env — hook_poller.py loads .env "
            "automatically, including during its own test runs, which would "
            "silently defeat this gate.\n"
            "\n"
            "Running a test? This error means a mock is missing — patch "
            "get_gmail_service, or inject a fake _service (see "
            "outreach/poller.py's run_poll(_service=...) pattern), instead of "
            "setting this variable."
        )

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
