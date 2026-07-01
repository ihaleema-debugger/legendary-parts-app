#!/usr/bin/env python3
"""
One-time Gmail OAuth consent script.
Run once per sender to mint a token file.

Usage (defaults resolve relative to this script's own directory):
    python outreach/mint_token.py

Override paths explicitly:
    python outreach/mint_token.py \
        --client-secret outreach/secrets/client_secret.json \
        --token-out     outreach/secrets/token_haleema.json
"""
import argparse
import json
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.readonly",
]

SCRIPT_DIR     = Path(__file__).resolve().parent          # outreach/
DEFAULT_SECRET = SCRIPT_DIR / "secrets" / "client_secret.json"
DEFAULT_TOKEN  = SCRIPT_DIR / "secrets" / "token_haleema.json"


def main():
    parser = argparse.ArgumentParser(description="Mint a Gmail OAuth token.")
    parser.add_argument(
        "--client-secret",
        default=str(DEFAULT_SECRET),
        help="Path to client_secret.json (default: outreach/secrets/client_secret.json)",
    )
    parser.add_argument(
        "--token-out",
        default=str(DEFAULT_TOKEN),
        help="Where to write the token JSON (default: outreach/secrets/token_haleema.json)",
    )
    args = parser.parse_args()

    secret_path = Path(args.client_secret)
    token_path  = Path(args.token_out)

    if not secret_path.exists():
        raise FileNotFoundError(f"Client secret not found: {secret_path}")

    flow  = InstalledAppFlow.from_client_secrets_file(str(secret_path), SCOPES)
    creds = flow.run_local_server(port=0)

    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_data = json.loads(creds.to_json())
    token_path.write_text(json.dumps(token_data, indent=2))
    print(f"\nToken written to: {token_path}")

    service = build("gmail", "v1", credentials=creds)
    profile = service.users().getProfile(userId="me").execute()
    print(f"Authenticated as:  {profile['emailAddress']}")
    print("OAuth flow complete.")


if __name__ == "__main__":
    main()
