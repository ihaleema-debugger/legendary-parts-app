---
name: keyword-clustering
description: Cluster Semrush keyword CSV exports into groups by search intent and topic for Legendary Parts (Harley Davidson parts). Use when the user asks to cluster keywords, group keywords, analyze keyword intent, organize a keyword list, or process a Semrush export into topic groups.
---

# Keyword Clustering for Legendary Parts

Cluster Semrush keyword CSV exports into actionable groups by search intent and topic. Every cluster should map to a potential content asset (blog post, category page, product page, or FAQ).

## Brand Context

- **Site:** https://www.legendary-parts.com/
- **Niche:** Harley Davidson OEM and aftermarket parts (30,000+ products)
- **Audience:** Harley riders, mechanics, DIY wrenchers, and garage owners
- **Location context:** France-based, but content is typically English and global

## Step 0: Get the File

If the user hasn't pointed to a file yet, ask:

- Path to the Semrush CSV export
- Any filters to apply before clustering (e.g., min search volume, max KD, specific keyword containing, exclude branded)

## Step 1: Parse the CSV

Semrush exports typically include these columns (names vary by export type):

- `Keyword`
- `Intent` (Informational / Commercial / Transactional / Navigational, sometimes blank)
- `Volume` (monthly search volume)
- `Keyword Difficulty` or `KD%`
- `CPC`
- `Competitive Density`
- `SERP Features`
- `Trends`

Load the CSV with Python (pandas) in Claude Code's code execution. Handle common issues:

- UTF-8 vs UTF-8 BOM encoding
- Semicolon vs comma separators (Semrush sometimes uses semicolons for European exports)
- Trailing whitespace in column names
- Missing intent labels (fill with a best-guess based on keyword phrasing)

Apply any user-specified filters before clustering.

## Step 2: Classify Intent (if missing or to refine Semrush's labels)

Semrush's intent labels are decent but sometimes wrong for niche verticals. Re-classify any keyword where:

- Intent is blank
- Intent seems obviously wrong based on the phrase

Use these rules for Harley parts specifically:

**Informational (I):**
- "how to", "what is", "vs", "difference between", "troubleshooting", "symptoms", "problems", "guide", "tutorial"
- Examples: "how to change Harley oil", "what causes stator failure", "Twin Cam vs Milwaukee-Eight"

**Commercial (C):**
- "best", "top", "review", "comparison", "recommended", "worth it"
- Examples: "best Harley exhaust", "top aftermarket air cleaner"

**Transactional (T):**
- Specific part names, SKUs, model years + part type, "buy", "for sale", "price", "cheap"
- Examples: "Harley 883 oil filter", "buy Screamin Eagle cams", "FLH primary cover"

**Navigational (N):**
- Brand names, site names
- Examples: "Legendary Parts", "Harley Davidson catalog"

## Step 3: Cluster by Intent + Topic

Group keywords using this two-level hierarchy:

1. **First level: Intent** (I / C / T / N)
2. **Second level: Topic** (the specific Harley subject matter)

For topic grouping, look for shared:

- **Part/system:** engine, exhaust, brakes, suspension, electrical, primary drive, transmission, fuel system, lighting, body/trim
- **Model family:** Sportster, Softail, Touring/FLH, Dyna, Street, V-Rod, CVO, Trike
- **Engine type:** Shovelhead, Evo, Twin Cam, Milwaukee-Eight, Revolution
- **Year range:** pre-1984, Evo era (1984–1999), Twin Cam era (1999–2017), M8 era (2017+)
- **Task/action:** installation, replacement, troubleshooting, upgrade, maintenance

A cluster should have:

- 3+ keywords minimum (anything smaller is a fragment, not a cluster)
- Combined search volume worth targeting (suggest a minimum, usually 100+/month)
- One clear primary keyword (highest volume + best match to intent)
- A content asset type recommendation

## Step 4: Output Format

Produce two outputs:

### Output 1: Markdown Summary

```markdown
# Keyword Cluster Report

**Source file:** [filename]
**Total keywords analyzed:** [N]
**Keywords after filters:** [N]
**Clusters identified:** [N]
**Total addressable volume:** [sum]

---

## Cluster 1: [Descriptive name, e.g. "Twin Cam Oil Change Guides"]

- **Intent:** Informational
- **Topic area:** Engine maintenance / Twin Cam
- **Primary keyword:** [highest volume keyword] (Vol: X, KD: Y)
- **Supporting keywords:** [count]
- **Total volume:** [sum]
- **Avg KD:** [avg]
- **Recommended asset:** Blog post / Category page / Product page / FAQ
- **Suggested title angle:** [one-line angle]

| Keyword | Volume | KD | Intent |
|---|---|---|---|
| [kw] | [v] | [kd] | [i] |

---

[Repeat for each cluster]

## Unclustered Keywords

[List keywords that didn't fit any cluster, usually because volume was too low or topic was too unique]
```

### Output 2: Clustered CSV

Save a new CSV with the original columns plus two new ones:

- `cluster_id` (e.g. `C01`, `C02`)
- `cluster_name` (descriptive name)
- `is_primary` (TRUE/FALSE for the primary keyword in each cluster)

Save to the same directory as the input file, named `[original]_clustered.csv`.

## Step 5: Recommendations

After the cluster report, suggest:

- **Top 5 priority clusters** based on a score of (volume × relevance to Legendary Parts catalog) ÷ avg KD
- **Quick-win clusters:** high volume + KD < 30
- **Which clusters should become category pages vs. blog posts vs. FAQs**
- **Any gaps** where a cluster has good keywords but no obvious Legendary Parts product category to link to

## Notes on Quality

- A good cluster has tight semantic coherence. "Harley oil filters" and "Harley oil" should probably be separate clusters because the search intent is different (product vs. maintenance guide).
- Don't force everything into a cluster. Unclustered leftover is fine and often more honest than a junk cluster.
- Branded Harley part numbers (like "63798-99") are transactional and should go into product-page clusters, not blog clusters.
