#!/usr/bin/env python3
"""
Competitor Keyword Research Tool
=================================
Uses Semrush API (domain_organic) to pull organic keyword rankings
for competitor domains, filters for motorcycle/HD-related terms,
and exports to a multi-sheet Excel file for content planning.

Caching:
    Raw keyword data is cached in .tmp/cache/{domain}_{database}.csv
    and reused for up to CACHE_MAX_AGE_DAYS days. API units are only
    spent on the first run (or when --force is passed).

Dependencies:
    pip install requests pandas openpyxl python-dotenv

Usage:
    python tools/semrush_competitor_keywords.py            # uses cache
    python tools/semrush_competitor_keywords.py --force    # busts cache

Output:
    .tmp/competitor_keywords_YYYYMMDD_HHMMSS.xlsx
"""

import os
import sys
import time
import re
import requests
import pandas as pd
from io import StringIO
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ─── Configuration ────────────────────────────────────────────────────────────

COMPETITORS = [
    "partseurope.eu",
    "louis.eu",
    "thunderbike.de",
    "ironcitymotorcycles.co.uk",
    "arhcustom.co.uk",
    "custom-chrome-europe.com",
    "ksmotorcycles.com",
    "bigtwincity.com",
]

MY_DOMAIN = "legendary-parts.com"

# Semrush database codes for each target market
DATABASES = {
    "us": "United States",
    "uk": "United Kingdom",
    "fr": "France",
    "de": "Germany",
    "es": "Spain",
    "it": "Italy",
}

DISPLAY_LIMIT      = 1000   # Keywords per domain/database call (sorted by volume desc).
                             # Each 10 rows = 1 Semrush API unit.
                             # NOTE: Requests above 1000 rows require premium API units
                             # and return ERROR 132 on standard plans. 1000 is the safe cap.
MIN_VOLUME         = 70     # Drop keywords below this monthly search volume
REQUEST_DELAY      = 1.5    # Seconds between individual calls within a batch
BATCH_SIZE         = 3      # Calls per batch before a long pause
BATCH_PAUSE        = 120    # Seconds to wait after each batch of BATCH_SIZE calls.
                             # Semrush rate limit window is ~90-120s. Retries of 15/30/45s
                             # all land inside the window and fail — need a full 2-min pause.
MAX_RETRIES        = 3      # Retry attempts on 403/429 before skipping a call
CACHE_DIR          = ".tmp/cache"
CACHE_MAX_AGE_DAYS = 30     # Cache files older than this trigger a fresh API call

SEMRUSH_API = "https://api.semrush.com/"

# ─── Keyword Classification ───────────────────────────────────────────────────
#
# Two-tier system:
#   Tier 1 — Harley Davidson: HD brand names, model names, engine designations
#   Tier 2 — Motorcycle Generic: broad moto terms usable in an HD context
#
# A keyword matching Tier 1 is labelled "Harley Davidson".
# A keyword matching only Tier 2 is labelled "Motorcycle Generic".
# Everything else is discarded.

HD_PATTERNS = [re.compile(p, re.IGNORECASE) for p in [
    r"\bharley[\s\-]?davidson\b",
    r"\bharley\b",
    r"\bhd\s+(parts?|accessories|motorcycle|bike|shop|gear)\b",
    # Models / lines
    r"\bsportster\b",
    r"\bsoftail\b",
    r"\bdyna\b",
    r"\broad[\s\-]?king\b",
    r"\bstreet[\s\-]?glide\b",
    r"\belectra[\s\-]?glide\b",
    r"\broad[\s\-]?glide\b",
    r"\bfat[\s\-]?boy\b",
    r"\biron[\s\-]?883\b",
    r"\bforty[\s\-]?eight\b",
    r"\bbreakout\b",
    r"\blivewire\b",
    r"\bpan[\s\-]?america\b",
    r"\bnightster\b",
    r"\blow[\s\-]?rider\b",
    r"\bstreet[\s\-]?bob\b",
    r"\bwide[\s\-]?glide\b",
    r"\btri[\s\-]?glide\b",
    r"\bcvo\b",
    r"\bfat[\s\-]?bob\b",
    r"\bheritage[\s\-]?classic\b",
    r"\bdeluxe\b",
    # Classic engines / generations
    r"\bshovelhead\b",
    r"\bpanhead\b",
    r"\bknucklehead\b",
    r"\beverhead\b",
    r"\btwin[\s\-]?cam\b",
    r"\bmilwaukee[\s\-]?eight\b",
    r"\beverhead\b",
    # Model codes
    r"\bfxr\b", r"\bfxst\b", r"\bfxs\b", r"\bflh[a-z]*\b",
    r"\bxl[\s\-]?883\b", r"\bxl[\s\-]?1200\b",
]]

GENERIC_MOTO_PATTERNS = [re.compile(p, re.IGNORECASE) for p in [
    r"\bmotorcycle\b",
    r"\bmotorbike\b",
    r"\bchopper\b",
    r"\bcruiser\b",
    r"\bbagger\b",
    r"\bbobber\b",
    r"\bcafe[\s\-]?racer\b",
    r"\bscrambler\b",
    r"\bv[\s\-]?twin\b",
    r"\bbig[\s\-]?twin\b",
    r"\bcustom[\s\-]?bike\b",
    r"\bcustom[\s\-]?motorcycle\b",
    r"\btrike\b",
    r"\bsidecar\b",
    # Apparel / gear
    r"\briding[\s\-]?jacket\b",
    r"\briding[\s\-]?boots?\b",
    r"\briding[\s\-]?gear\b",
    r"\briding[\s\-]?gloves?\b",
    r"\bbiker[\s\-]?jacket\b",
    r"\bbiker[\s\-]?gear\b",
    r"\bmotorcycle[\s\-]?helmet\b",
    r"\bmotorcycle[\s\-]?gloves?\b",
    r"\bmotorcycle[\s\-]?boots?\b",
    r"\bmotorcycle[\s\-]?jacket\b",
    # Parts / hardware
    r"\bsaddlebag\b",
    r"\bsaddle[\s\-]?bag\b",
    r"\bhandlebar\b",
    r"\bfootpeg\b",
    r"\bfoot[\s\-]?peg\b",
    r"\bexhaust[\s\-]?(pipe|system|kit|tip)\b",
    r"\bmotorcycle[\s\-]?(parts?|accessories)\b",
    r"\bbike[\s\-]?(parts?|accessories)\b",
    # Community / lifestyle
    r"\bbiker\b",
    r"\bmoto\b",
]]


def classify_keyword(kw: str):
    """Returns 'Harley Davidson', 'Motorcycle Generic', or None (irrelevant)."""
    for p in HD_PATTERNS:
        if p.search(kw):
            return "Harley Davidson"
    for p in GENERIC_MOTO_PATTERNS:
        if p.search(kw):
            return "Motorcycle Generic"
    return None


# ─── Semrush API ──────────────────────────────────────────────────────────────

def fetch_keywords(domain: str, database: str, api_key: str) -> pd.DataFrame:
    """
    Fetches organic keyword rankings for a domain/database from Semrush.
    Columns returned: keyword, position, volume, kd, url, domain, database
    Returns an empty DataFrame on any error.
    """
    params = {
        "type":           "domain_organic",
        "key":            api_key,
        "domain":         domain,
        "database":       database,
        "display_limit":  DISPLAY_LIMIT,
        "display_sort":   "nq_desc",                   # Highest volume first
        "export_columns": "Ph,Po,Nq,Kd,Ur",            # Phrase, Position, Volume, KD, URL
        "display_filter": f"+|Nq|Ge|{MIN_VOLUME}",     # Server-side volume filter
    }

    text = ""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.get(SEMRUSH_API, params=params, timeout=30)
            if r.status_code in (403, 429):
                wait = 60 * attempt   # 60s, 120s, 180s — must clear the ~120s window
                print(f"rate limited (attempt {attempt}/{MAX_RETRIES}), waiting {wait}s ... ", end="", flush=True)
                time.sleep(wait)
                continue
            r.raise_for_status()
            text = r.text.strip()
            break
        except requests.RequestException as e:
            if attempt == MAX_RETRIES:
                print(f"request failed — {e}")
                return pd.DataFrame()
            time.sleep(5 * attempt)

    if not text:
        print("no response after retries")
        return pd.DataFrame()

    # Semrush error responses start with "ERROR"
    if text.startswith("ERROR"):
        code = text[:80]
        print(f"API error — {code}")
        return pd.DataFrame()

    try:
        df = pd.read_csv(StringIO(text), sep=";")
    except Exception as e:
        print(f"parse error — {e}")
        return pd.DataFrame()

    if df.empty or len(df.columns) < 3:
        print("no rows returned")
        return pd.DataFrame()

    # Semrush may return full English column names or short codes depending on plan.
    # Map both variants to our internal names.
    col_map = {
        "Keyword":            "keyword",   "Ph": "keyword",
        "Position":           "position",  "Po": "position",
        "Search Volume":      "volume",    "Nq": "volume",
        "Keyword Difficulty": "kd",        "Kd": "kd",
        "URL":                "url",       "Ur": "url",
    }
    df = df.rename(columns={c: col_map[c] for c in df.columns if c in col_map})

    # Ensure all expected columns are present
    for col in ["keyword", "position", "volume", "kd", "url"]:
        if col not in df.columns:
            df[col] = None

    df = df[["keyword", "position", "volume", "kd", "url"]].copy()
    df["domain"]   = domain
    df["database"] = database.upper()

    df["volume"]   = pd.to_numeric(df["volume"],   errors="coerce").fillna(0).astype(int)
    df["position"] = pd.to_numeric(df["position"], errors="coerce")
    df["kd"]       = pd.to_numeric(df["kd"],       errors="coerce")

    # Re-apply client-side volume floor (in case server filter behaved unexpectedly)
    return df[df["volume"] >= MIN_VOLUME].reset_index(drop=True)


# ─── Cache Layer ──────────────────────────────────────────────────────────────

def _cache_path(domain: str, database: str) -> str:
    """Returns the cache file path for a domain/database pair."""
    return os.path.join(CACHE_DIR, f"{domain}_{database}.csv")


def get_semrush_data(domain: str, database: str, api_key: str, force: bool = False):
    """
    Returns (DataFrame, was_api_call) for a domain/database pair.

    Cache logic:
      - If .tmp/cache/{domain}_{database}.csv exists and is < CACHE_MAX_AGE_DAYS
        old, loads from file and returns (df, False).
      - Otherwise makes a Semrush API call, saves the result to cache,
        and returns (df, True).
      - force=True skips the cache check and always makes a fresh API call.
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = _cache_path(domain, database)

    if not force and os.path.exists(path):
        age_days = (time.time() - os.path.getmtime(path)) / 86400
        if age_days < CACHE_MAX_AGE_DAYS:
            print(f"[CACHE HIT {age_days:.0f}d old] ", end="", flush=True)
            df = pd.read_csv(path, dtype={"keyword": str, "url": str})
            df["volume"]   = pd.to_numeric(df["volume"],   errors="coerce").fillna(0).astype(int)
            df["position"] = pd.to_numeric(df["position"], errors="coerce")
            df["kd"]       = pd.to_numeric(df["kd"],       errors="coerce")
            return df, False

    print("[API CALL] ", end="", flush=True)
    df = fetch_keywords(domain, database, api_key)

    if not df.empty:
        df.to_csv(path, index=False)

    return df, True


# ─── Aggregation Helpers ──────────────────────────────────────────────────────

def build_master(raw: pd.DataFrame) -> pd.DataFrame:
    """
    Deduplicate and aggregate raw keyword rows into one row per keyword.
    Columns: Keyword, Category, Max Search Volume, Keyword Difficulty,
             Best Position, # Competitors Ranking, Competitors, Countries
    Sorted by: # Competitors Ranking DESC, Max Search Volume DESC.
    """
    agg = (
        raw.groupby("keyword", as_index=False)
        .agg(
            Category            = ("category",  "first"),
            Max_Search_Volume   = ("volume",    "max"),
            Keyword_Difficulty  = ("kd",        "mean"),
            Best_Position       = ("position",  "min"),
            Num_Competitors     = ("domain",    "nunique"),
            Competitors         = ("domain",    lambda x: ", ".join(sorted(x.unique()))),
            Countries           = ("database",  lambda x: ", ".join(sorted(x.unique()))),
        )
        .rename(columns={
            "keyword":           "Keyword",
            "Max_Search_Volume": "Max Search Volume",
            "Keyword_Difficulty":"Keyword Difficulty",
            "Best_Position":     "Best Position",
            "Num_Competitors":   "# Competitors Ranking",
        })
    )
    agg["Keyword Difficulty"] = agg["Keyword Difficulty"].round(1)
    return agg.sort_values(
        ["# Competitors Ranking", "Max Search Volume"], ascending=False
    ).reset_index(drop=True)


def autosize_columns(ws) -> None:
    """Widen each Excel column to fit its longest cell value (capped at 65 chars)."""
    for col_cells in ws.columns:
        width = max((len(str(c.value or "")) for c in col_cells), default=10)
        ws.column_dimensions[col_cells[0].column_letter].width = min(width + 3, 65)


# ─── Main Pipeline ────────────────────────────────────────────────────────────

def run(api_key: str, force: bool = False) -> None:
    timestamp   = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = f".tmp/competitor_keywords_{timestamp}.xlsx"
    os.makedirs(".tmp", exist_ok=True)

    total_calls = len(COMPETITORS) * len(DATABASES)
    est_units   = (DISPLAY_LIMIT / 10) * total_calls
    print("=" * 65)
    print("  Competitor Keyword Research — Semrush API")
    print("=" * 65)
    print(f"  Competitors : {len(COMPETITORS)}")
    print(f"  Databases   : {', '.join(DATABASES.keys())}")
    print(f"  Total pairs : {total_calls}  ({len(COMPETITORS)} × {len(DATABASES)})")
    print(f"  Limit/call  : {DISPLAY_LIMIT:,} keywords (sorted by volume)")
    print(f"  Est. units  : ~{int(est_units):,}  (only on cache misses)")
    print(f"  Cache       : {CACHE_DIR}  (max age {CACHE_MAX_AGE_DAYS}d)")
    print(f"  Force refetch: {force}")
    print("=" * 65)

    # ── Step 1: Competitor keywords ──────────────────────────────────────────
    print("\nSTEP 1  Fetching competitor keywords\n")

    raw_rows        = []
    api_calls_made  = 0
    cache_hits      = 0
    api_calls_batch = 0   # tracks API calls since the last batch pause
    i = 0

    for domain in COMPETITORS:
        for db, market in DATABASES.items():
            i += 1
            label = f"[{i:02d}/{total_calls}]  {domain:<38}  {market}"
            print(f"  {label} ... ", end="", flush=True)

            df, was_api_call = get_semrush_data(domain, db, api_key, force=force)

            if was_api_call:
                api_calls_made  += 1
                api_calls_batch += 1
            else:
                cache_hits += 1

            if not df.empty:
                df["category"] = df["keyword"].apply(classify_keyword)
                relevant = df[df["category"].notna()]
                raw_rows.append(relevant)
                print(f"{len(relevant):,} keywords")

            # Batch pause only after actual API calls — cache hits don't need it
            if was_api_call:
                if api_calls_batch % BATCH_SIZE == 0 and i < total_calls:
                    print(f"\n  --- batch pause {BATCH_PAUSE}s (rate limit) ---\n")
                    time.sleep(BATCH_PAUSE)
                    api_calls_batch = 0
                else:
                    time.sleep(REQUEST_DELAY)

    if not raw_rows:
        print("\n  No data retrieved. Verify SEMRUSH_API_KEY is correct and has API units.")
        sys.exit(1)

    raw = pd.concat(raw_rows, ignore_index=True)
    print(f"\n  Total rows collected : {len(raw):,}")
    print(f"  API calls made       : {api_calls_made}")
    print(f"  Cache hits           : {cache_hits}")

    # ── Step 2: My domain — gap analysis ─────────────────────────────────────
    print(f"\nSTEP 2  Fetching {MY_DOMAIN} rankings (gap analysis)\n")

    my_top10        = set()
    api_calls_batch = 0

    for j, (db, market) in enumerate(DATABASES.items(), start=1):
        print(f"  {market:<25} ... ", end="", flush=True)
        df, was_api_call = get_semrush_data(MY_DOMAIN, db, api_key, force=force)

        if was_api_call:
            api_calls_made  += 1
            api_calls_batch += 1
        else:
            cache_hits += 1

        if not df.empty:
            top10 = set(df[df["position"] <= 10]["keyword"].str.lower())
            my_top10.update(top10)
            print(f"{len(top10):,} top-10 keywords")

        if was_api_call:
            if api_calls_batch % BATCH_SIZE == 0 and j < len(DATABASES):
                print(f"\n  --- batch pause {BATCH_PAUSE}s ---\n")
                time.sleep(BATCH_PAUSE)
                api_calls_batch = 0
            else:
                time.sleep(REQUEST_DELAY)

    print(f"\n  Keywords already in top-10: {len(my_top10):,}  (excluded from Gap sheet)")

    # ── Step 3: Build Excel ───────────────────────────────────────────────────
    print("\nSTEP 3  Building Excel report ...")

    master  = build_master(raw)
    gap     = master[~master["Keyword"].str.lower().isin(my_top10)].copy()
    hd      = master[master["Category"] == "Harley Davidson"].copy()
    generic = master[master["Category"] == "Motorcycle Generic"].copy()

    raw_export = (
        raw[["keyword","category","domain","database","position","volume","kd","url"]]
        .copy()
        .rename(columns={
            "keyword":  "Keyword",
            "category": "Category",
            "domain":   "Competitor",
            "database": "Country",
            "position": "Position",
            "volume":   "Search Volume",
            "kd":       "Keyword Difficulty",
            "url":      "Ranking URL",
        })
        .sort_values(["Competitor", "Country", "Position"])
        .reset_index(drop=True)
    )

    sheets = {
        "Master Keywords":    master,
        "Keyword Gap":        gap,
        "Harley Davidson":    hd,
        "Generic Motorcycle": generic,
        "Raw Data":           raw_export,
    }

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        for sheet_name, df in sheets.items():
            df.to_excel(writer, sheet_name=sheet_name, index=False)
            autosize_columns(writer.sheets[sheet_name])

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{'=' * 65}")
    print("  DONE")
    print(f"{'=' * 65}")
    print(f"  Unique keywords total      : {len(master):,}")
    print(f"  ├─ Harley Davidson         : {len(hd):,}")
    print(f"  └─ Generic Motorcycle      : {len(generic):,}")
    print(f"  Keyword gap (opportunity)  : {len(gap):,}")
    print(f"  API calls made             : {api_calls_made}  (units spent)")
    print(f"  Cache hits                 : {cache_hits}  (free)")
    print(f"\n  Output → {output_path}")
    print()


if __name__ == "__main__":
    key = os.getenv("SEMRUSH_API_KEY")
    if not key:
        print("Error: SEMRUSH_API_KEY is not set in .env")
        sys.exit(1)
    force = "--force" in sys.argv
    run(key, force=force)
