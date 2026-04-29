---
name: content-brief
description: Create a comprehensive SEO content brief for a target keyword covering SERP analysis, search intent, recommended H2 outline, LSI terms, word count, meta tags, and internal linking suggestions for Legendary Parts (Harley Davidson parts). Use when the user asks for a content brief, SEO brief, writer brief, content outline, or article plan.
---

# Content Brief Generator for Legendary Parts

Produce a complete SEO content brief that a writer (human or AI) can use to create a ranking-ready piece of content. The brief covers strategy, structure, and every specific element needed to execute.

## Brand Context

- **Site:** https://www.legendary-parts.com/
- **Niche:** Harley Davidson OEM and aftermarket parts
- **Voice:** Professional but expert, rider-to-rider, technically accurate, not salesy
- **Catalog:** 30,000+ products, both OEM and aftermarket
- **Content goal:** Rank in Google and AI answer engines

## Step 0: Collect Inputs

Ask for:

- **Primary keyword** (required)
- **Cluster context** (if this is part of a cluster, share the supporting keywords)
- **Content type:** blog post, pillar page, category landing, product guide, buying guide, FAQ
- **Any angle or position** the user wants the brief to reflect

## Step 1: SERP Competitor Analysis

Run a web search for the primary keyword. Analyze the top 10 results:

For each of the top 5 competitors, capture:

- **URL and page title**
- **Publisher type:** brand site, aftermarket retailer, publication, forum, blog
- **Word count** (rough estimate)
- **Content structure:** how many H2s, are they question-based or topic-based
- **Angle:** what perspective is taken (e.g., "buying guide", "how-to", "comparison")
- **Strengths:** what this page does well
- **Gaps:** what it misses or does poorly

Also note:

- **SERP features present:** featured snippet, PAA, shopping, video, images, local pack
- **"People also ask" questions** (all of them)
- **"Related searches"** at bottom of SERP
- **Any AI Overview** and what entities it cites

## Step 2: Target Keyword and Intent

Define clearly:

- **Primary keyword:** [exact phrase]
- **Monthly search volume:** [if known]
- **Keyword difficulty:** [if known]
- **Search intent:** Informational / Commercial / Transactional / Navigational
- **Intent nuance:** one-sentence description of what the searcher actually wants (e.g., "Wants to diagnose a specific Twin Cam oil leak symptom before deciding whether to DIY or take it to a shop")
- **Searcher profile:** who is this person (beginner rider, experienced wrench, shop owner, etc.)

## Step 3: LSI and Entity Coverage

List terms the content must cover for topical completeness. Organize as:

- **Must-include terms** (appear across top 5 SERP results)
- **Should-include terms** (appear in top 10 or autocomplete)
- **Questions to answer** (from PAA and forums)

Scale the count to word count: roughly 8–12 must-include terms per 1,000 words.

## Step 4: Recommended Outline

Produce a full H2 outline. Structure it as:

```markdown
### Title (working): [Title with primary keyword]

### Meta Title (55-60 chars): [draft]

### Meta Description (150-160 chars): [draft]

### TL;DR (50-80 words): [what the post delivers]

### Introduction (100-150 words)
Hook angle: [specific opening approach]
Primary keyword placement: [where in first 50 words]

### H2 #1: [Heading]
- Intent: Answer capsule / Standard editorial
- Word count: ~[N]
- Key points to cover:
  - [point]
  - [point]
- LSI terms to weave in: [term, term]
- Must link to: [internal or external link]

### H2 #2: [Heading]
[same structure]

[Continue for 4-7 H2 sections]

### Conclusion (75-100 words)
- Key takeaways: [list]
- CTA: [specific action, pointing to specific Legendary Parts URL]

### FAQ Section (5 questions)
1. [Question] - 2-3 sentence answer direction
2. [Question] - ...
```

Mark ~60% of H2s as "answer capsule" format (H2 is a question, followed by a 30–60 word direct answer).

## Step 5: Word Count and Format Recommendation

Base the recommendation on competitor analysis, not a default:

- **Recommended word count:** [range, e.g., 1,200–1,500 words]
- **Justification:** [e.g., "Top 5 competitors average 1,400 words. Going longer won't help rank; being more useful will."]
- **Format elements:**
  - Hero image with alt text: [suggestion]
  - Diagrams or specs tables: yes/no, what kind
  - Internal FAQ schema: yes/no
  - Video embed: yes/no (if YouTube has strong SERP presence)
  - Product comparison table: yes/no

## Step 6: Meta Title and Description

Provide 2 options for each, with character counts:

**Meta Title Options:**
1. [Option 1] ([X] chars)
2. [Option 2] ([X] chars)

Rules:
- 55–60 characters max (to avoid truncation)
- Primary keyword near the front
- Include a modifier or year if relevant (e.g., "2026 Guide", "Complete Guide", "OEM vs Aftermarket")
- No em dashes (Legendary Parts style rule)

**Meta Description Options:**
1. [Option 1] ([X] chars)
2. [Option 2] ([X] chars)

Rules:
- 150–160 characters max
- Primary keyword within first 120 characters
- One clear benefit or hook
- Soft CTA when it fits naturally

## Step 7: Internal Linking Plan

Identify 4–7 Legendary Parts pages to link to. For each:

```markdown
| Target Page | Anchor Text | Section | Why Relevant |
|---|---|---|---|
| /category/oil-filters | genuine Harley oil filters | H2 #3 | Product category matches the buying intent mentioned |
```

Priorities for internal links:
1. **Category pages** when a part type is mentioned (strongest)
2. **Related blog posts** for deeper reading on a sub-topic
3. **Product pages** only when a specific SKU is named
4. **Contact/service pages** for "talk to an expert" moments

If the user's sitemap hasn't been fetched yet, fetch https://www.legendary-parts.com/sitemap.xml first.

## Step 8: External Source Plan

Identify 8–12 authoritative sources the writer should cite:

```markdown
| # | Source | URL | Specific Insight | Section |
|---|---|---|---|---|
| 1 | Harley-Davidson Service Manual | [url] | Torque spec for primary case | H2 #4 |
```

Prioritize:
- Official Harley-Davidson documentation
- Reputable motorcycle publications
- OEM technical bulletins
- Expert mechanic interviews or published guides
- Recent data (last 12 months preferred for stats)

## Output Format

Deliver the brief as a single markdown document the user can save as `[primary-keyword]-brief.md`. Structure in this order:

1. Header (keyword, intent, word count, content type)
2. Executive summary (2–3 sentences on the strategy)
3. SERP analysis
4. Target keyword + intent
5. LSI and entity coverage
6. Recommended outline
7. Word count and format
8. Meta title and description options
9. Internal linking plan
10. External source plan
11. Any special notes or warnings (e.g., "Avoid making claims about warranty compatibility without a source")

## Notes on Quality

- A brief should let a writer execute without further research. If the writer has to go figure out the competitor angle or find sources themselves, the brief is incomplete.
- Be specific, not generic. "Cover Twin Cam cam tensioner failure symptoms including chain slap noise, metal shavings in oil, and hydraulic tensioner collapse" beats "cover common problems."
- Flag anything the writer should NOT do (e.g., "Don't recommend specific aftermarket cams without citing dyno data")
- If the SERP is dominated by forums or shopping results, note that and adjust recommendations (e.g., "This is a transactional SERP, a blog post won't rank here. Recommend creating a category page instead.")
