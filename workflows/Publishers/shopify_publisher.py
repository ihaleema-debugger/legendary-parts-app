"""Push seo-forge blog output to Shopify as a hidden draft article."""
import os
import re
import sys
import requests
import markdown
from dotenv import load_dotenv
from pathlib import Path
from shopify_auth import get_access_token
from gdoc_reader import read_blog_gdoc

# Make the project root importable so we can `from app.services...`
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

env_path = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(env_path)

STORE = os.getenv("SHOPIFY_STORE")
VERSION = os.getenv("SHOPIFY_API_VERSION", "2025-01")
BLOG_ID = os.getenv("SHOPIFY_BLOG_ID")

BASE = f"https://{STORE}/admin/api/{VERSION}"


def list_blogs():
    """Run once to find your blog_id. Add it to .env."""
    headers = {"X-Shopify-Access-Token": get_access_token(), "Content-Type": "application/json"}
    r = requests.get(f"{BASE}/blogs.json", headers=headers)
    r.raise_for_status()
    for b in r.json()["blogs"]:
        print(f"{b['id']}\t{b['title']}\t{b['handle']}")


def slugify(text):
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"[\s_-]+", "-", text)


def md_to_html(md_body):
    """Convert markdown to HTML, wrapped in a justified content div.

    JSON-LD <script> blocks written as fenced ```html code blocks are extracted
    before markdown conversion so they render as invisible schema markup rather
    than visible <pre><code> blocks in the article body.
    """
    # Pull out any fenced ```html blocks that contain a JSON-LD <script> tag
    jsonld_re = re.compile(
        r"```html\s*(<script\s+type=[\"']application/ld\+json[\"'].*?</script>)\s*```",
        re.DOTALL,
    )
    jsonld_blocks = jsonld_re.findall(md_body)
    cleaned_md = jsonld_re.sub("", md_body).strip()

    html = markdown.markdown(
        cleaned_md,
        extensions=["extra", "fenced_code", "tables", "sane_lists"],
    )
    body = f'<div style="text-align: justify;" class="content">\n{html}\n</div>'
    if jsonld_blocks:
        body += "\n" + "\n".join(jsonld_blocks)
    return body


def publish_blog_post(doc_id):
    """Read a Google Doc blog post via Drive, push to Shopify as hidden draft."""
    doc = read_blog_gdoc(doc_id)

    if doc["locale"] != "fr":
        raise RuntimeError(
            f"[publish] REFUSING to draft non-French primary article. "
            f"doc_id={doc_id!r} resolved to locale={doc['locale']!r}. "
            f"The primary article must be the French translation."
        )

    article_payload = {
        "title": doc["title"],
        "author": os.getenv("SHOPIFY_ARTICLE_AUTHOR", "Haleema"),
        "body_html": doc["body_html"],
        "handle": doc["handle"],
        "tags": ", ".join(doc["tags"]),
        "summary_html": doc["meta_description"] or doc["summary"],
        "published": False,
    }

    payload = {"article": article_payload}

    url = f"{BASE}/blogs/{BLOG_ID}/articles.json"
    headers = {"X-Shopify-Access-Token": get_access_token(), "Content-Type": "application/json"}
    r = requests.post(url, headers=headers, json=payload)

    if r.status_code >= 400:
        print(f"Shopify error {r.status_code}: {r.text}")
        r.raise_for_status()

    article = r.json()["article"]
    admin_url = f"https://{STORE}/admin/articles/{article['id']}"
    print(f"✓ Draft created: {article['title']}")
    print(f"  Admin URL: {admin_url}")
    return article, doc["locale"]


# ─────────────────────────────────────────────────────────────────────
# Translations
# ─────────────────────────────────────────────────────────────────────

# Locales in the Drive folder that are NOT target translations
# (fr is the source — already published as the article itself)
SOURCE_LOCALES = {"fr"}


def _parse_translated_doc(html: str) -> dict:
    """Parse an exported Google Doc HTML into title / meta_description / body_html.

    Google Docs export wraps everything in <html><body>...</body></html>.
    The doc structure is:
      - First paragraph contains "META DESCRIPTION:" prefix (bold) + the description
      - Then an <h1> with the translated title
      - Then the body (paragraphs, h2/h3, lists, etc.)

    Returns dict: {title, meta_description, body_html}
    """
    # Strip outer html/body wrappers if present, keep inner content
    body_match = re.search(r"<body[^>]*>(.*)</body>", html, re.DOTALL | re.IGNORECASE)
    inner = body_match.group(1) if body_match else html

    # --- Extract META DESCRIPTION ---
    # Look for "META DESCRIPTION:" anywhere, capture text until end of that paragraph.
    meta_description = ""
    meta_match = re.search(
        r"META\s*DESCRIPTION\s*:\s*(.*?)</p>",
        inner,
        re.IGNORECASE | re.DOTALL,
    )
    if meta_match:
        raw = meta_match.group(1)
        # strip any remaining HTML tags from the captured snippet
        meta_description = re.sub(r"<[^>]+>", "", raw).strip()
        # remove the whole paragraph containing META DESCRIPTION from inner
        inner = re.sub(
            r"<p[^>]*>[^<]*META\s*DESCRIPTION\s*:.*?</p>\s*",
            "",
            inner,
            count=1,
            flags=re.IGNORECASE | re.DOTALL,
        )

    # --- Extract H1 title ---
    title = ""
    h1_match = re.search(r"<h1[^>]*>(.*?)</h1>", inner, re.IGNORECASE | re.DOTALL)
    if h1_match:
        raw_title = h1_match.group(1)
        title = re.sub(r"<[^>]+>", "", raw_title).strip()
        # strip the H1 from the body
        inner = re.sub(r"<h1[^>]*>.*?</h1>\s*", "", inner, count=1, flags=re.IGNORECASE | re.DOTALL)

    # --- Wrap body in justified div, same as md_to_html ---
    body_html = f'<div style="text-align: justify;" class="content">\n{inner.strip()}\n</div>'

    return {
        "title": title,
        "meta_description": meta_description,
        "body_html": body_html,
    }


def _get_translatable_content_digests(article_id: int) -> dict:
    """Fetch translatableResource digests for the article's translatable fields.

    Shopify requires a `translatableContentDigest` for each field being translated.
    Returns a dict keyed by field key: {title: digest, body_html: digest, ...}
    """
    gid = f"gid://shopify/Article/{article_id}"
    query = """
    query getTranslatable($resourceId: ID!) {
      translatableResource(resourceId: $resourceId) {
        resourceId
        translatableContent {
          key
          value
          digest
          locale
        }
      }
    }
    """
    payload = {"query": query, "variables": {"resourceId": gid}}
    url = f"{BASE}/graphql.json"
    headers = {"X-Shopify-Access-Token": get_access_token(), "Content-Type": "application/json"}
    r = requests.post(url, headers=headers, json=payload)
    if r.status_code >= 400:
        print(f"GraphQL HTTP error {r.status_code} (response body redacted)")
        r.raise_for_status()

    data = r.json()
    if "errors" in data:
        raise RuntimeError(f"GraphQL errors: {data['errors']}")

    resource = data["data"].get("translatableResource")
    if not resource:
        raise RuntimeError(
            f"No translatableResource found for {gid}. "
            f"Confirm the article ID is correct and the article exists."
        )

    digests = {item["key"]: item["digest"] for item in resource["translatableContent"]}
    print(f"[DEBUG] translatable fields available: {list(digests.keys())}")
    return digests


def _register_translation_for_locale(
    article_id: int, locale: str, parsed: dict, digests: dict
) -> dict:
    """Send a translationsRegister mutation for one locale."""
    gid = f"gid://shopify/Article/{article_id}"

    translations = []

    # Map our parsed fields to Shopify's translatable keys
    field_map = {
        "title": parsed["title"],
        "body_html": parsed["body_html"],
        "meta_description": parsed["meta_description"],
        # Shopify's SEO title key is "title_tag" if present; reuse the title
        "title_tag": parsed["title"],
    }

    for key, value in field_map.items():
        if not value:
            continue
        if key not in digests:
            # Field isn't translatable on this resource — skip silently
            continue
        translations.append({
            "locale": locale,
            "key": key,
            "value": value,
            "translatableContentDigest": digests[key],
        })

    if not translations:
        return {"locale": locale, "status": "skipped", "reason": "no fields to translate"}

    mutation = """
    mutation registerTranslations($resourceId: ID!, $translations: [TranslationInput!]!) {
      translationsRegister(resourceId: $resourceId, translations: $translations) {
        userErrors { field message code }
        translations { locale key value }
      }
    }
    """
    payload = {
        "query": mutation,
        "variables": {"resourceId": gid, "translations": translations},
    }
    url = f"{BASE}/graphql.json"
    headers = {"X-Shopify-Access-Token": get_access_token(), "Content-Type": "application/json"}
    r = requests.post(url, headers=headers, json=payload)
    if r.status_code >= 400:
        print(f"GraphQL HTTP error {r.status_code} for {locale} (response body redacted)")
        return {"locale": locale, "status": "failed", "reason": f"HTTP {r.status_code}"}

    data = r.json()
    if "errors" in data:
        return {"locale": locale, "status": "failed", "reason": str(data["errors"])}

    result = data["data"]["translationsRegister"]
    if result["userErrors"]:
        return {"locale": locale, "status": "failed", "reason": str(result["userErrors"])}

    saved_keys = [t["key"] for t in result["translations"]]
    return {"locale": locale, "status": "saved", "fields": saved_keys}


def register_translations(article_id: int, folder_id: str, name_prefix: str):
    """Register all translations for an article from a Drive folder.

    Reads sibling Google Docs in `folder_id` matching `name_prefix`,
    parses each (META DESCRIPTION + H1 + body), and registers them
    as translations on the given article via Shopify's GraphQL API.
    """
    # Import here to avoid forcing drive deps on the basic publish path
    try:
        from drive_uploader import find_files_in_folder, export_doc_as_html
    except ImportError:
        # Try the service path used elsewhere in the project
        from app.services.drive_uploader import find_files_in_folder, export_doc_as_html

    print(f"\n→ Fetching translatable digests for article {article_id}...")
    digests = _get_translatable_content_digests(article_id)

    print(f"\n→ Listing files in folder {folder_id} with prefix {name_prefix!r}...")
    files = find_files_in_folder(folder_id, name_prefix)
    if not files:
        print(f"✗ No files found in folder {folder_id} matching {name_prefix!r}")
        return

    print(f"  Found {len(files)} file(s): {[f['locale'] for f in files]}")

    LOCALE_OVERRIDES = {"pt": "pt-PT"}

    results = []
    for f in files:
        locale = LOCALE_OVERRIDES.get(f["locale"], f["locale"])
        if locale in SOURCE_LOCALES:
            print(f"\n[{locale}] skipped (source locale)")
            results.append({"locale": locale, "status": "skipped", "reason": "source locale"})
            continue

        print(f"\n[{locale}] reading {f['name']}...")
        try:
            html = export_doc_as_html(f["id"])
            parsed = _parse_translated_doc(html)
            if not parsed["title"]:
                print(f"  ✗ No H1 title found")
                results.append({"locale": locale, "status": "failed", "reason": "no H1 title"})
                continue
            print(f"  Title: {parsed['title'][:60]}...")
            print(f"  Meta:  {parsed['meta_description'][:60]}...")

            result = _register_translation_for_locale(article_id, locale, parsed, digests)
            if result["status"] == "saved":
                print(f"  ✓ saved fields: {result['fields']}")
            else:
                print(f"  ✗ {result['status']}: {result.get('reason')}")
            results.append(result)
        except Exception as e:
            print(f"  ✗ error: {e}")
            results.append({"locale": locale, "status": "failed", "reason": str(e)})

    # Summary
    print("\n" + "=" * 50)
    print("Translation summary:")
    for r in results:
        line = f"  {r['locale']}: {r['status']}"
        if r["status"] != "saved":
            line += f" ({r.get('reason', '')})"
        print(line)
    saved = sum(1 for r in results if r["status"] == "saved")
    failed = sum(1 for r in results if r["status"] == "failed")
    skipped = sum(1 for r in results if r["status"] == "skipped")
    print(f"\nTotal: {saved} saved, {failed} failed, {skipped} skipped (of {len(results)})")
    return results


def _find_fr_doc_by_slug(english_doc_id: str):
    """Search TRANSLATIONS_FOLDER_ID for the --fr doc matching an English doc's slug.

    Uses drive_reader._slugify (strips apostrophes before slugifying) so the
    computed slug matches the exact filename saved by save_translated_doc.
    """
    _pub_root = Path(__file__).resolve().parents[2]
    if str(_pub_root) not in sys.path:
        sys.path.insert(0, str(_pub_root))
    from dotenv import load_dotenv as _lde
    _lde(_pub_root / ".env")
    from app.services.drive_uploader import _get_service
    from app.services.drive_reader import _slugify
    service = _get_service()
    meta = service.files().get(
        fileId=english_doc_id, fields="name", supportsAllDrives=True
    ).execute()
    slug = _slugify(meta["name"])
    folder_id = os.getenv("TRANSLATIONS_FOLDER_ID", "")
    drive_id = os.getenv("GOOGLE_SHARED_DRIVE_ID", "")
    if not folder_id:
        raise RuntimeError("TRANSLATIONS_FOLDER_ID is not set in .env")
    q = (
        f"'{folder_id}' in parents "
        f"and mimeType='application/vnd.google-apps.document' "
        f"and name='{slug}--fr' "
        f"and trashed=false"
    )
    kwargs = dict(
        q=q, fields="files(id,name)", supportsAllDrives=True,
        includeItemsFromAllDrives=True, pageSize=10,
    )
    if drive_id:
        kwargs["corpora"] = "drive"
        kwargs["driveId"] = drive_id
    r = service.files().list(**kwargs).execute()
    files = r.get("files", [])
    return files[0]["id"] if files else None


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "list-blogs":
        list_blogs()
    elif len(sys.argv) > 1 and sys.argv[1] == "translate":
        if len(sys.argv) < 5:
            print("Usage: python publishers/shopify_publisher.py translate <article_id> <folder_id> <name_prefix>")
            sys.exit(1)
        article_id = int(sys.argv[2])
        folder_id = sys.argv[3]
        name_prefix = sys.argv[4]
        register_translations(article_id, folder_id, name_prefix)
    elif len(sys.argv) > 1 and sys.argv[1] == "find-fr":
        if len(sys.argv) < 3:
            print("Usage: python shopify_publisher.py find-fr <english_doc_id>")
            sys.exit(1)
        _fr_id = _find_fr_doc_by_slug(sys.argv[2])
        if _fr_id:
            print(f"Found fr_doc_id: {_fr_id}")
            print(f"To seed the DB run: python shopify_publisher.py save-fr {sys.argv[2]} {_fr_id}")
        else:
            print(f"No --fr doc found in translations folder for {sys.argv[2]!r}")
            sys.exit(1)
    elif len(sys.argv) > 1 and sys.argv[1] == "save-fr":
        if len(sys.argv) < 4:
            print("Usage: python shopify_publisher.py save-fr <english_doc_id> <fr_doc_id>")
            sys.exit(1)
        _pub_root = Path(__file__).resolve().parents[2]
        if str(_pub_root) not in sys.path:
            sys.path.insert(0, str(_pub_root))
        from app.services.trello_state import TrelloState as _TrelloState
        _TrelloState().save_fr_doc_id(sys.argv[2], sys.argv[3])
        print(f"Saved fr_doc_id={sys.argv[3]!r} for doc_id={sys.argv[2]!r}")
    elif len(sys.argv) > 1:
        _cli_doc_id = sys.argv[1]
        _pub_root = Path(__file__).resolve().parents[2]
        if str(_pub_root) not in sys.path:
            sys.path.insert(0, str(_pub_root))
        from app.services.trello_state import TrelloState as _TrelloState
        _row = _TrelloState().get_by_doc_id(_cli_doc_id)
        if _row is None:
            print(f"[CLI] Error: doc_id {_cli_doc_id!r} not found in trello_state.db.")
            sys.exit(1)
        if not _row.get("fr_doc_id"):
            print(
                f"[CLI] Error: No French doc ID stored for doc_id={_cli_doc_id!r}.\n"
                f"       Run: python shopify_publisher.py find-fr {_cli_doc_id}\n"
                f"       Then: python shopify_publisher.py save-fr {_cli_doc_id} <fr_doc_id>"
            )
            sys.exit(1)
        _publish_id = _row["fr_doc_id"]
        print(f"[CLI] Resolved fr_doc_id={_publish_id!r} from DB")
        print(f"[CLI] publish_blog_post → doc_id={_publish_id!r}")
        _cli_article, _cli_locale = publish_blog_post(_publish_id)
        print(f"[CLI] Published locale={_cli_locale!r} article_id={_cli_article['id']}")
    else:
        print("Usage: python shopify_publisher.py <english_doc_id>")
        print("       python shopify_publisher.py list-blogs")
        print("       python shopify_publisher.py translate <article_id> <folder_id> <name_prefix>")
        print("       python shopify_publisher.py find-fr <english_doc_id>")
        print("       python shopify_publisher.py save-fr <english_doc_id> <fr_doc_id>")
