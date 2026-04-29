---
name: lsi-generation
description: Generate LSI (semantically related) keywords and supporting terms for a target keyword in the Harley Davidson parts niche. Use when the user asks for LSI keywords, related terms, semantic keywords, supporting keywords, entity coverage, NLP terms, or terms to include in a blog post or page.
---

# LSI Keyword Generation for Legendary Parts

Generate a comprehensive list of semantically related terms to include in content targeting a given primary keyword. Output is designed to help content rank better by covering the full topic entity graph that Google and AI engines expect.

## Brand Context

- **Site:** https://www.legendary-parts.com/
- **Niche:** Harley Davidson OEM and aftermarket parts
- **Audience:** Harley riders, mechanics, DIY wrenchers
- **Content goal:** Rank in Google and AI answer engines (ChatGPT, Perplexity, AI Overviews)

## Step 0: Get the Inputs

Ask if not provided:

- **Primary keyword** (required)
- **Content type:** blog post, category page, product page, FAQ, or buying guide
- **Target word count** (to scale the LSI list appropriately)
- **Any context:** specific Harley model, engine, year range, or use case the content targets

## Step 1: Research Phase

Do these in parallel using web search, then synthesize:

1. **Google top 10 SERP scan** for the primary keyword. Look for:
   - Recurring terms across top-ranking pages
   - "People also ask" questions
   - Related searches at the bottom of the SERP
   - Featured snippet content (if any)

2. **Google autocomplete** variations. Search the primary keyword and note the suggestions that appear.

3. **Harley-specific sources:**
   - Official Harley-Davidson documentation or service manuals
   - Forums (HDForums.com, Sportster.org, V-Twin Forum)
   - Reputable publications (Cycle World, Motorcyclist, Hot Bike)
   - Reddit (r/Harley, r/motorcycles)

4. **AI answer engine scan:** If the skill has access, check how ChatGPT and Perplexity answer the query. Note which entities and terms they reference.

## Step 2: Categorize LSI Terms

Organize into these buckets for the output:

### 1. Synonyms and Variations
Direct alternatives to the primary keyword. Plural/singular, abbreviations, slang.
Example for "Harley Twin Cam engine": "88 cubic inch motor", "TC88", "Twin Cam 88", "A-motor/B-motor"

### 2. Component Parts and Subsystems
What the primary keyword is made of, or what it connects to.
Example for "Twin Cam engine": cam chest, tensioners, lifters, pushrods, rocker boxes, crankcase, flywheels, pistons, cylinder heads

### 3. Related Systems
Adjacent systems the reader likely cares about.
Example for "Twin Cam engine": primary drive, transmission, exhaust, fuel system, ignition

### 4. Common Tasks and Actions
What people *do* with or to the subject.
Example: install, replace, rebuild, torque, inspect, adjust, upgrade, diagnose, maintain

### 5. Problems and Symptoms
Pain points readers search alongside.
Example for "Twin Cam engine": tensioner failure, cam chain noise, oil leaks, excessive heat, low oil pressure, camshaft wear

### 6. Measurements, Specs, and Numbers
Quantitative entities Google expects on authoritative content.
Example: 88ci, 96ci, 103ci, 110ci (CVO), compression ratio, torque spec, oil capacity (3–4 quarts), bore/stroke

### 7. Model and Year Context
Which Harleys and years are affected.
Example for Twin Cam: 1999–2017, Softail/Dyna/Touring, excludes Sportster

### 8. Brands and Manufacturers
Aftermarket and OEM names relevant to the topic.
Example: S&S Cycle, Screamin' Eagle, Andrews, Wood Performance, Feuling, JIMS

### 9. Tools and Equipment
What's needed to work with the subject.
Example: torque wrench, primary case gasket, cam chest tool, flywheel locking pin

### 10. Related Questions (for FAQ coverage)
Natural questions a reader would also have.
Example: "How long do Twin Cam engines last?" / "Is Twin Cam better than Milwaukee-Eight?"

## Step 3: Scoring and Prioritization

For each LSI term, tag with:

- **Priority:** Must-include / Should-include / Nice-to-have
  - Must-include: appears in top 5 ranking pages OR in featured snippet OR in PAA questions
  - Should-include: appears in top 10 or in autocomplete
  - Nice-to-have: semantically related but less frequent
- **Placement hint:** H2, H3, body copy, FAQ, meta description, alt text

## Step 4: Output Format

```markdown
# LSI Report: [Primary Keyword]

**Content type:** [blog / category / product / FAQ / guide]
**Target word count:** [N]
**Total LSI terms identified:** [N]
**Must-include terms:** [N]

---

## 1. Synonyms and Variations

| Term | Priority | Placement |
|---|---|---|
| [term] | Must | H2 or first paragraph |

## 2. Component Parts and Subsystems

[same table format]

[Continue for all 10 categories]

---

## Quick-Reference Checklist

Terms to include at minimum (the "must-include" list):

- [ ] [term 1]
- [ ] [term 2]
...

## Suggested H2 Topics Derived from LSI

Based on the entity coverage above, these would be strong H2 sections:

1. [H2 idea tied to a cluster of LSI terms]
2. [H2 idea]
...

## Related Questions for FAQ

From PAA and forum research:

1. [Question]
2. [Question]
...
```

## Step 5: Sanity Check

Before finalizing, verify:

- Total LSI count is proportional to word count (rough rule: ~10 must-include per 1,000 words)
- No generic filler terms that don't add topical depth ("motorcycle", "bike", "parts" alone are too broad)
- Technical accuracy: all Harley-specific terms spelled correctly (e.g., "Screamin' Eagle" with the apostrophe, "Milwaukee-Eight" hyphenated)
- Year ranges and compatibility claims are correct (Twin Cam is 1999–2017, not 1998)

## Notes

- For product-page LSI, prioritize transactional and spec-oriented terms. For blog LSI, prioritize informational and problem/symptom terms.
- Don't just dump every related term. LSI is about *relevant* semantic coverage, not keyword stuffing.
- Forum language often catches real-rider terminology that SERP tools miss. Always check at least one forum source.
