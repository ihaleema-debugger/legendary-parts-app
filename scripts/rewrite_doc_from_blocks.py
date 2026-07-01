import json
import sys
from pathlib import Path

# Add project root to path so we can import app.services
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / ".env")

from app.services.docs_client import write_structured_doc

DOC_ID = "1P0GcldGUdvKRQfvcvo_TdpJ4jSdBg71AGedOi_fyrxQ"
BLOCKS_PATH = Path.home() / "Desktop/seo-forge/2026-04-20_thunderbike_france/clusters/cluster_07_harley_chicano_style/blog_blocks.json"

def main():
    print(f"Loading blocks from: {BLOCKS_PATH}")
    with open(BLOCKS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
        blocks = data["blocks"] if isinstance(data, dict) else data

    print(f"Loaded {len(blocks)} blocks")
    print(f"First block: {blocks[0].get('text', '')[:80]}...")
    print(f"Second block: {blocks[1].get('text', '')[:80]}...")

    confirm = input(f"\nRewrite doc {DOC_ID} with these blocks? (yes/no): ")
    if confirm.lower() != "yes":
        print("Aborted.")
        return

    print(f"Rewriting doc {DOC_ID}...")
    write_structured_doc(DOC_ID, blocks)
    print("Done. Verify the Drive doc now shows META DESCRIPTION and META TITLE above the H1.")

if __name__ == "__main__":
    main()
