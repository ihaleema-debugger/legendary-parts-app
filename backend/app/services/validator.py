"""
SEO Validator — 18-rule compliance engine.

Returns a scored, graded scorecard for SEO content quality.
No API calls; purely deterministic analysis.
"""

import re
from typing import Optional

from bs4 import BeautifulSoup
import textstat

# ─── Configuration ────────────────────────────────────────────────────────────

KEYWORD_DENSITY_MIN = 1.0
KEYWORD_DENSITY_MAX = 3.0
KEYWORD_DENSITY_WARN_MIN = 0.5
KEYWORD_DENSITY_WARN_MAX = 4.0

META_TITLE_MIN = 50
META_TITLE_MAX = 60
META_TITLE_WARN_MIN = 45
META_TITLE_WARN_MAX = 65

META_DESC_MIN = 150
META_DESC_MAX = 160
META_DESC_WARN_MIN = 140
META_DESC_WARN_MAX = 170

MIN_WORD_COUNT = 300
GOOD_WORD_COUNT = 600
READABILITY_TARGET = 60
READABILITY_WARN = 40
MAX_PARAGRAPH_WORDS = 300

GRADE_THRESHOLDS = {"A": 90, "B": 75, "C": 60, "D": 40}

AUTHORITATIVE_DOMAINS = {
    "wikipedia.org", "gov", "edu", "nytimes.com", "bbc.com",
    "reuters.com", "forbes.com", "wsj.com", "harvard.edu",
    "nih.gov", "cdc.gov", "who.int", "nature.com", "sciencedirect.com",
}


# ─── Scoring helpers ──────────────────────────────────────────────────────────

def _result(rule_id: str, name: str, status: str, value, expected: str,
            weight: int, message: str) -> dict:
    return {
        "id": rule_id,
        "name": name,
        "status": status,
        "value": value,
        "expected": expected,
        "weight": weight,
        "message": message,
    }


def _compute_score(rules: list) -> tuple:
    total_weight = sum(r["weight"] for r in rules)
    earned = sum(r["weight"] for r in rules if r["status"] == "pass") + \
             sum(r["weight"] * 0.5 for r in rules if r["status"] == "warning")
    score = round((earned / total_weight) * 100) if total_weight else 0

    if score >= GRADE_THRESHOLDS["A"]:
        grade = "A"
    elif score >= GRADE_THRESHOLDS["B"]:
        grade = "B"
    elif score >= GRADE_THRESHOLDS["C"]:
        grade = "C"
    elif score >= GRADE_THRESHOLDS["D"]:
        grade = "D"
    else:
        grade = "F"

    return score, grade


# ─── Individual rule functions ────────────────────────────────────────────────

def _rule_keyword_density(plain_text: str, keyword: str, word_count: int) -> dict:
    if word_count == 0:
        return _result("keyword_density", "Keyword Density", "fail", 0.0,
                       "1-3%", 15, "No content to analyze")

    pattern = r'\b' + re.escape(keyword) + r'\b'
    kw_count = len(re.findall(pattern, plain_text, re.IGNORECASE))
    density = round((kw_count / word_count) * 100, 2)

    if KEYWORD_DENSITY_MIN <= density <= KEYWORD_DENSITY_MAX:
        status, msg = "pass", f"Good keyword density at {density}%"
    elif KEYWORD_DENSITY_WARN_MIN <= density < KEYWORD_DENSITY_MIN or \
         KEYWORD_DENSITY_MAX < density <= KEYWORD_DENSITY_WARN_MAX:
        status, msg = "warning", f"Keyword density {density}% is outside ideal range (1-3%)"
    elif density > KEYWORD_DENSITY_WARN_MAX:
        status, msg = "fail", f"Keyword stuffing detected: {density}% density"
    else:
        status, msg = "fail", f"Keyword density too low at {density}% (min: {KEYWORD_DENSITY_WARN_MIN}%)"

    return _result("keyword_density", "Keyword Density", status, density,
                   "1-3%", 15, msg)


def _rule_keyword_in_title(soup: BeautifulSoup, keyword: str) -> dict:
    h1 = soup.find("h1")
    if not h1:
        return _result("keyword_in_title", "Keyword in H1 Title", "fail", "",
                       "Keyword present", 12, "No H1 tag found")
    h1_text = h1.get_text().strip()
    if keyword in h1_text.lower():
        return _result("keyword_in_title", "Keyword in H1 Title", "pass", h1_text,
                       "Keyword present", 12, "Keyword found in H1")
    return _result("keyword_in_title", "Keyword in H1 Title", "fail", h1_text,
                   "Keyword present", 12, "Keyword not found in H1")


def _rule_keyword_in_first_100(plain_words: list, keyword: str) -> dict:
    first_100 = " ".join(plain_words[:100]).lower()
    pattern = r'\b' + re.escape(keyword) + r'\b'
    found = bool(re.search(pattern, first_100, re.IGNORECASE))
    if found:
        return _result("keyword_in_first_100_words", "Keyword in First 100 Words", "pass",
                       True, "Present", 10, "Keyword appears in the opening paragraph")
    return _result("keyword_in_first_100_words", "Keyword in First 100 Words", "fail",
                   False, "Present", 10, "Keyword not found in first 100 words")


def _rule_keyword_in_meta_title(meta_title: str, keyword: str) -> dict:
    if not meta_title:
        return _result("keyword_in_meta_title", "Keyword in Meta Title", "fail", "",
                       "Present", 12, "Meta title not provided")
    if keyword in meta_title.lower():
        return _result("keyword_in_meta_title", "Keyword in Meta Title", "pass", meta_title,
                       "Present", 12, "Keyword found in meta title")
    return _result("keyword_in_meta_title", "Keyword in Meta Title", "fail", meta_title,
                   "Present", 12, "Keyword not found in meta title")


def _rule_keyword_in_meta_description(meta_description: str, keyword: str) -> dict:
    if not meta_description:
        return _result("keyword_in_meta_description", "Keyword in Meta Description", "fail", "",
                       "Present", 8, "Meta description not provided")
    if keyword in meta_description.lower():
        return _result("keyword_in_meta_description", "Keyword in Meta Description", "pass",
                       meta_description, "Present", 8, "Keyword found in meta description")
    return _result("keyword_in_meta_description", "Keyword in Meta Description", "fail",
                   meta_description, "Present", 8, "Keyword not found in meta description")


def _rule_meta_title_length(meta_title: str) -> dict:
    length = len(meta_title.strip()) if meta_title else 0
    if not meta_title:
        return _result("meta_title_length", "Meta Title Length", "fail", 0,
                       "50-60 chars", 10, "Meta title not provided")
    if META_TITLE_MIN <= length <= META_TITLE_MAX:
        status, msg = "pass", f"Meta title length {length} chars is optimal"
    elif META_TITLE_WARN_MIN <= length < META_TITLE_MIN or META_TITLE_MAX < length <= META_TITLE_WARN_MAX:
        status, msg = "warning", f"Meta title length {length} chars is slightly outside 50-60"
    else:
        status, msg = "fail", f"Meta title length {length} chars is too {'short' if length < META_TITLE_WARN_MIN else 'long'}"
    return _result("meta_title_length", "Meta Title Length", status, length,
                   "50-60 chars", 10, msg)


def _rule_meta_description_length(meta_description: str) -> dict:
    length = len(meta_description.strip()) if meta_description else 0
    if not meta_description:
        return _result("meta_description_length", "Meta Description Length", "fail", 0,
                       "150-160 chars", 8, "Meta description not provided")
    if META_DESC_MIN <= length <= META_DESC_MAX:
        status, msg = "pass", f"Meta description length {length} chars is optimal"
    elif META_DESC_WARN_MIN <= length < META_DESC_MIN or META_DESC_MAX < length <= META_DESC_WARN_MAX:
        status, msg = "warning", f"Meta description length {length} chars is slightly outside 150-160"
    else:
        status, msg = "fail", f"Meta description length {length} chars is too {'short' if length < META_DESC_WARN_MIN else 'long'}"
    return _result("meta_description_length", "Meta Description Length", status, length,
                   "150-160 chars", 8, msg)


def _rule_h1_count(soup: BeautifulSoup) -> dict:
    count = len(soup.find_all("h1"))
    if count == 1:
        return _result("h1_count", "H1 Tag Count", "pass", count, "Exactly 1", 12, "One H1 tag found")
    if count == 0:
        return _result("h1_count", "H1 Tag Count", "fail", count, "Exactly 1", 12, "No H1 tag found")
    return _result("h1_count", "H1 Tag Count", "fail", count, "Exactly 1", 12,
                   f"Multiple H1 tags found ({count}) — only one allowed")


def _rule_h2_count(soup: BeautifulSoup) -> dict:
    count = len(soup.find_all("h2"))
    if count >= 2:
        return _result("h2_count", "H2 Tag Count", "pass", count, "≥2", 8,
                       f"{count} H2 tags provide good content structure")
    if count == 1:
        return _result("h2_count", "H2 Tag Count", "warning", count, "≥2", 8,
                       "Only 1 H2 tag — add more subheadings for structure")
    return _result("h2_count", "H2 Tag Count", "fail", count, "≥2", 8,
                   "No H2 tags found — content lacks structure")


def _rule_h3_structure(soup: BeautifulSoup, word_count: int) -> dict:
    if word_count < GOOD_WORD_COUNT:
        return _result("h3_structure", "H3 Tag Structure", "pass", 0,
                       "≥1 (for 600+ word content)", 5,
                       f"H3 not required for content under {GOOD_WORD_COUNT} words")
    count = len(soup.find_all("h3"))
    if count >= 1:
        return _result("h3_structure", "H3 Tag Structure", "pass", count,
                       "≥1 (for 600+ word content)", 5,
                       f"{count} H3 tag(s) provide good sub-structure")
    return _result("h3_structure", "H3 Tag Structure", "warning", count,
                   "≥1 (for 600+ word content)", 5,
                   "No H3 tags — consider adding sub-sections for long content")


def _rule_word_count(word_count: int) -> dict:
    if word_count >= GOOD_WORD_COUNT:
        return _result("word_count", "Word Count", "pass", word_count,
                       f"≥{GOOD_WORD_COUNT}", 10, f"{word_count} words — good content depth")
    if word_count >= MIN_WORD_COUNT:
        return _result("word_count", "Word Count", "warning", word_count,
                       f"≥{GOOD_WORD_COUNT}", 10,
                       f"{word_count} words — consider expanding to {GOOD_WORD_COUNT}+")
    return _result("word_count", "Word Count", "fail", word_count,
                   f"≥{GOOD_WORD_COUNT}", 10,
                   f"{word_count} words is below the minimum of {MIN_WORD_COUNT}")


def _rule_internal_links(soup: BeautifulSoup) -> dict:
    links = soup.find_all("a", href=True)
    internal = [a for a in links
                if not a["href"].startswith("http") and not a["href"].startswith("//")]
    count = len(internal)
    if count >= 1:
        return _result("internal_links", "Internal Links", "pass", count,
                       "≥1", 8, f"{count} internal link(s) found")
    return _result("internal_links", "Internal Links", "fail", count,
                   "≥1", 8, "No internal links — add links to related content")


def _rule_external_links_authoritative(soup: BeautifulSoup) -> dict:
    links = soup.find_all("a", href=True)
    external = [a for a in links if a["href"].startswith("http")]

    def is_authoritative(url: str) -> bool:
        return any(domain in url for domain in AUTHORITATIVE_DOMAINS)

    auth_links = [a for a in external if is_authoritative(a["href"])]
    auth_count = len(auth_links)

    if auth_count >= 1:
        return _result("external_links_authoritative", "Authoritative External Links", "pass",
                       auth_count, "≥1 authoritative", 6,
                       f"{auth_count} authoritative external link(s) found")
    if external:
        return _result("external_links_authoritative", "Authoritative External Links", "warning",
                       len(external), "≥1 authoritative", 6,
                       "External links present but none link to authoritative sources")
    return _result("external_links_authoritative", "Authoritative External Links", "fail",
                   0, "≥1 authoritative", 6, "No external links found")


def _rule_image_alt_coverage(soup: BeautifulSoup) -> dict:
    images = soup.find_all("img")
    if not images:
        return _result("image_alt_coverage", "Image Alt Text Coverage", "pass",
                       "N/A", "100%", 7, "No images found (rule not applicable)")
    missing = [img for img in images if not img.get("alt", "").strip()]
    coverage = round(((len(images) - len(missing)) / len(images)) * 100, 1)
    if not missing:
        return _result("image_alt_coverage", "Image Alt Text Coverage", "pass",
                       "100%", "100%", 7, f"All {len(images)} image(s) have alt text")
    if len(missing) <= 1 or coverage >= 80:
        return _result("image_alt_coverage", "Image Alt Text Coverage", "warning",
                       f"{coverage}%", "100%", 7,
                       f"{len(missing)} image(s) missing alt text")
    return _result("image_alt_coverage", "Image Alt Text Coverage", "fail",
                   f"{coverage}%", "100%", 7,
                   f"{len(missing)} of {len(images)} images missing alt text")


def _rule_keyword_in_url_slug(url_slug: str, keyword: str) -> dict:
    if not url_slug:
        return _result("keyword_in_url_slug", "Keyword in URL Slug", "warning", "",
                       "Present", 8, "URL slug not provided")
    cleaned = url_slug.replace("-", " ").replace("_", " ").lower().strip()
    if keyword in cleaned:
        return _result("keyword_in_url_slug", "Keyword in URL Slug", "pass", url_slug,
                       "Present", 8, "Keyword found in URL slug")
    return _result("keyword_in_url_slug", "Keyword in URL Slug", "fail", url_slug,
                   "Present", 8, "Keyword not found in URL slug")


def _rule_readability_score(plain_text: str) -> dict:
    try:
        score = round(textstat.flesch_reading_ease(plain_text), 1)
    except ZeroDivisionError:
        return _result("readability_score", "Readability Score (Flesch)", "warning",
                       0.0, f"≥{READABILITY_TARGET}", 8,
                       "Content too short to calculate readability")

    if score >= READABILITY_TARGET:
        label = "Easy" if score >= 70 else "Fairly Easy"
        return _result("readability_score", "Readability Score (Flesch)", "pass",
                       score, f"≥{READABILITY_TARGET}", 8,
                       f"{label} to read (score: {score})")
    if score >= READABILITY_WARN:
        return _result("readability_score", "Readability Score (Flesch)", "warning",
                       score, f"≥{READABILITY_TARGET}", 8,
                       f"Fairly difficult to read (score: {score}) — simplify sentences")
    return _result("readability_score", "Readability Score (Flesch)", "fail",
                   score, f"≥{READABILITY_TARGET}", 8,
                   f"Difficult to read (score: {score}) — content is too complex")


def _rule_paragraph_length(soup: BeautifulSoup, plain_text: str) -> dict:
    p_tags = soup.find_all("p")
    if p_tags:
        paragraphs = [p.get_text() for p in p_tags]
    else:
        paragraphs = [chunk.strip() for chunk in plain_text.split("\n\n") if chunk.strip()]

    long_paras = [p for p in paragraphs if len(p.split()) > MAX_PARAGRAPH_WORDS]
    if not long_paras:
        return _result("paragraph_length", "Paragraph Length", "pass",
                       0, f"≤{MAX_PARAGRAPH_WORDS} words", 6,
                       "All paragraphs are within the recommended length")
    if len(long_paras) == 1:
        return _result("paragraph_length", "Paragraph Length", "warning",
                       len(long_paras), f"≤{MAX_PARAGRAPH_WORDS} words", 6,
                       f"1 paragraph exceeds {MAX_PARAGRAPH_WORDS} words — consider splitting")
    return _result("paragraph_length", "Paragraph Length", "fail",
                   len(long_paras), f"≤{MAX_PARAGRAPH_WORDS} words", 6,
                   f"{len(long_paras)} paragraphs exceed {MAX_PARAGRAPH_WORDS} words")


def _rule_duplicate_headings(soup: BeautifulSoup) -> dict:
    headings = soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])
    texts = [h.get_text().strip().lower() for h in headings]
    seen, duplicates = set(), set()
    for t in texts:
        if t in seen:
            duplicates.add(t)
        seen.add(t)

    if not duplicates:
        return _result("duplicate_headings", "Duplicate Headings", "pass",
                       0, "No duplicates", 5, "All heading text is unique")
    if len(duplicates) == 1:
        return _result("duplicate_headings", "Duplicate Headings", "warning",
                       len(duplicates), "No duplicates", 5,
                       f"1 duplicate heading found: '{next(iter(duplicates))}'")
    return _result("duplicate_headings", "Duplicate Headings", "fail",
                   len(duplicates), "No duplicates", 5,
                   f"{len(duplicates)} duplicate headings found")


# ─── Public API ───────────────────────────────────────────────────────────────

def validate(
    content: str,
    keyword: str,
    meta_title: str = "",
    meta_description: str = "",
    url_slug: str = "",
    html: str = "",
) -> dict:
    """
    Run the 18-rule SEO validation engine and return a compliance scorecard.

    Args:
        content:          Plain-text content body
        keyword:          Primary target keyword
        meta_title:       Page meta title tag
        meta_description: Page meta description tag
        url_slug:         URL slug (e.g. "harley-davidson-parts")
        html:             Optional full HTML — enables link/image/heading analysis

    Returns:
        Scorecard dict with overall_score, grade, and per-rule results
    """
    # Parse HTML or create an empty soup for fallback
    if html:
        soup = BeautifulSoup(html, "lxml")
        plain_text = soup.get_text(separator=" ")
    else:
        soup = BeautifulSoup("", "lxml")
        plain_text = content

    # Normalize plain text and split into words
    plain_text = re.sub(r"\s+", " ", plain_text).strip()
    plain_words = plain_text.split()
    word_count = len(plain_words)
    keyword_norm = keyword.lower().strip()

    # Run all 18 rules
    rules = [
        _rule_keyword_density(plain_text, keyword_norm, word_count),
        _rule_keyword_in_title(soup, keyword_norm),
        _rule_keyword_in_first_100(plain_words, keyword_norm),
        _rule_keyword_in_meta_title(meta_title, keyword_norm),
        _rule_keyword_in_meta_description(meta_description, keyword_norm),
        _rule_meta_title_length(meta_title),
        _rule_meta_description_length(meta_description),
        _rule_h1_count(soup),
        _rule_h2_count(soup),
        _rule_h3_structure(soup, word_count),
        _rule_word_count(word_count),
        _rule_internal_links(soup),
        _rule_external_links_authoritative(soup),
        _rule_image_alt_coverage(soup),
        _rule_keyword_in_url_slug(url_slug, keyword_norm),
        _rule_readability_score(plain_text),
        _rule_paragraph_length(soup, plain_text),
        _rule_duplicate_headings(soup),
    ]

    overall_score, grade = _compute_score(rules)
    passed = sum(1 for r in rules if r["status"] == "pass")
    warnings = sum(1 for r in rules if r["status"] == "warning")
    failed = sum(1 for r in rules if r["status"] == "fail")

    return {
        "overall_score": overall_score,
        "grade": grade,
        "passed": passed,
        "failed": failed,
        "warnings": warnings,
        "rules": rules,
    }


# ─── CLI test block ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json

    sample_html = """
    <html><body>
    <h1>Best Harley Davidson Parts Online</h1>
    <p>If you're looking for genuine <strong>Harley Davidson parts</strong>, you've come to the right place.
    We stock thousands of Harley Davidson parts for every model from the Sportster to the Road Glide.
    Whether you need engine components, exhaust systems, or custom accessories for your Harley Davidson,
    we have what you need at competitive prices. Our Harley Davidson parts experts are here to help you
    find exactly what your bike needs.</p>
    <h2>Why Choose Our Harley Davidson Parts Store</h2>
    <p>We carry only genuine OEM and premium aftermarket Harley Davidson parts. All products are
    rigorously tested and come with a full warranty. Our team has over 20 years of experience
    serving the Harley Davidson community.</p>
    <h2>Shop by Model</h2>
    <p>Browse our full selection of <a href="/models">Harley Davidson models</a> or use our
    parts finder to locate exactly what you need. We also recommend checking out
    <a href="https://www.harley-davidson.com">the official Harley Davidson website</a>
    for specifications. Our catalog is sourced from
    <a href="https://wikipedia.org/wiki/Harley-Davidson">Wikipedia's comprehensive model history</a>.</p>
    <h3>Popular Categories</h3>
    <p>Engine parts, brakes, exhausts, wheels, and more.</p>
    <img src="parts.jpg" alt="Harley Davidson engine parts">
    <img src="catalog.jpg" alt="Parts catalog">
    </body></html>
    """

    result = validate(
        content="",
        keyword="Harley Davidson parts",
        meta_title="Best Harley Davidson Parts | Shop OEM & Aftermarket",
        meta_description="Shop the best Harley Davidson parts online. Genuine OEM and aftermarket parts for every model. Fast shipping, expert advice, and full warranty on all items.",
        url_slug="harley-davidson-parts",
        html=sample_html,
    )

    print(f"\nSEO Scorecard: {result['overall_score']}/100 (Grade {result['grade']})")
    print(f"  Passed: {result['passed']}  Warnings: {result['warnings']}  Failed: {result['failed']}\n")
    for rule in result["rules"]:
        icon = {"pass": "✓", "warning": "⚠", "fail": "✗"}[rule["status"]]
        print(f"  {icon} [{rule['weight']:2d}] {rule['name']:<40} {rule['message']}")
    print()
    print(json.dumps(result, indent=2))
