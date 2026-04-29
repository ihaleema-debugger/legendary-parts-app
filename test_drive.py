import os
from dotenv import load_dotenv

load_dotenv()

from app.services.drive_uploader import upload_blog_to_drive

SAMPLE_CONTENT = """\
# Test Upload

This is a test blog post uploaded via the Drive uploader module.

If you can read this in Google Docs, the service account auth is working correctly.
"""

if __name__ == "__main__":
    print("Uploading test document to Google Drive...")
    result = upload_blog_to_drive(title="[TEST] Drive Uploader Check", content=SAMPLE_CONTENT)
    print("Success!")
    print(f"  File ID  : {result['id']}")
    print(f"  Name     : {result['name']}")
    print(f"  View URL : {result['webViewLink']}")
