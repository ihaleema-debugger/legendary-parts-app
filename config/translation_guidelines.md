# Translation Guidelines

These guidelines govern how SEO-Forge translates approved English blog posts into the 8 target languages: French (FR), German (DE), Spanish (ES), Italian (IT), Dutch (NL), Polish (PL), Slovenian (SL), and Portuguese (PT).

The workflow operates at **Balanced transcreation level** — body content is translated faithfully; SEO elements and CTAs are adapted for local search and tone.

---

## 1. Core principles

1. **Localize, don't translate.** Adapt content so it feels native to readers in each market. A literal translation that reads like a translation is a failure.
2. **Preserve factual and technical accuracy above all else.** Motorcycle parts content has real-world consequences. A misrepresented spec is worse than a clunky sentence.
3. **Write for how riders in each market actually search.** Keywords, part vocabulary, and phrasing should reflect real local search behavior — not English search behavior translated.
4. **Avoid semantic collapse.** Each translated blog must read as a distinct, market-native piece of content. If the 8 versions are too literal, AI systems (Google AI Overviews, ChatGPT, Perplexity) will treat them as redundant and default to the English version.
5. **One language per page.** Translated content must be fully in the target language. The only exception is the **protected tokens** list below (brand names, OEM codes, model names).

---

## 2. Transcreation scope (Balanced mode)

The model has different levels of latitude depending on content type:

| Content type | Latitude | Rule |
|---|---|---|
| Body paragraphs | Tight | Translate faithfully. Preserve sentence count, paragraph count, meaning, and all qualifiers. |
| H2/H3 subheadings | Balanced | Preserve meaning but adapt phrasing to include localized keywords where natural. |
| Title (H1) | Loose | Rewrite with localized primary keyword. Must stay within 60 characters. |
| Meta description | Loose | Rewrite with localized keywords and local-tone CTA. Must stay within 155 characters. |
| Intro hook (first 1-2 sentences) | Balanced | Light rephrasing permitted for natural flow. Meaning must be preserved. |
| CTAs (buttons, links, call-to-actions) | Loose | Rewrite for local tone conventions (formal/informal per language). |
| Alt text | Balanced | Translate faithfully but replace the primary keyword with its localized variant. |
| FAQ questions | Balanced | Rephrase to match how users in the target market would naturally ask. |
| FAQ answers | Tight | Translate faithfully. |

---

## 3. Protected tokens (never translate)

The following must appear **verbatim** in the translated output, exactly as they appear in the English source:

- **OEM part numbers** — e.g., `55903-05`, `50782-91`
- **Brand names** — Harley-Davidson, Legendary Parts, S&S Cycle, Vance & Hines, Arlen Ness, Drag Specialties, Kuryakyn, Mustang, Progressive Suspension
- **Harley-Davidson model names** — Softail, Dyna, Sportster, Touring, CVO, Road King, Street Glide, Fat Boy, Electra Glide, Heritage Classic, Breakout, Low Rider, Fat Bob, etc.
- **Engine designations** — Twin Cam 88, Twin Cam 96, Milwaukee-Eight 107, Milwaukee-Eight 114, Milwaukee-Eight 117, Evolution, Shovelhead, Panhead, Knucklehead
- **Technical unit abbreviations** — mm, cm, in, ft, lb, kg, Nm, ft-lb, cc, hp, rpm, psi, bar
- **Numerical values** — all dimensions, year ranges, torque specs, displacement figures, quantities
- **Model year ranges** — "2007-2017", "1999-2006", etc. Never rephrase as "from 2007 onwards" or similar.

---

## 4. Preserve hedges and qualifiers

English hedges and qualifiers carry technical or legal weight. They must be translated, not dropped.

Preserve all instances of: *typically, usually, generally, in most cases, often, may, might, can, recommended, suggested, approximately, around, up to, at least, minimum, maximum, optional, required, prior to, before, after, subject to, fits most, compatible with, designed for.*

**Example of drift to avoid:**
- EN: "This clamp typically fits Softail models from 2007 to 2017."
- Bad ES: "Esta brida encaja en modelos Softail de 2007 a 2017." *(dropped "typically")*
- Good ES: "Esta brida suele encajar en modelos Softail de 2007 a 2017."

---

## 5. Per-language tone and conventions

### French (FR)
- **Formality:** Use *vous* throughout. Commercial/technical content in French defaults to formal.
- **Tone:** Informative, precise, slightly reserved. Avoid overly enthusiastic marketing language.
- **Technical vocabulary:** French riders often mix English part terms with French ones. Prefer French terms where well-established (*guidon, cadre, fourche, frein*) but retain English for terms without clean French equivalents.
- **Diacritics:** Always preserve (é, è, ê, à, ç, ô, ù, î).
- **Number formatting:** Use comma as decimal separator (12,5 Nm). Space or period as thousands separator.

### German (DE)
- **Formality:** Use *Sie* throughout. German commercial content is almost always formal.
- **Tone:** Precise, technical, spec-heavy. German riders expect detailed specs and exact compatibility information.
- **Compound nouns:** German naturally combines words (*Lenkerklemme, Motorhalter, Zündkerze*). Don't artificially break these apart.
- **Technical vocabulary:** German has strong native automotive vocabulary — use it. Brand and model names stay English.
- **Diacritics:** Always preserve (ä, ö, ü, ß). Never substitute "ae/oe/ue/ss" unless the source uses them.
- **Number formatting:** Comma as decimal separator (12,5 Nm). Period as thousands separator (1.000).

### Spanish (ES — European/Castilian only)
- **Target variant:** European Spanish (Spain). Do NOT use Latin American vocabulary or phrasing.
- **Formality:** Use *usted* for commercial/transactional content; *tú* is acceptable in conversational blog intros and enthusiast-focused posts. Stay consistent within a post.
- **Tone:** Direct, enthusiast-friendly. Spanish motorcycle culture is strong — don't over-formalize.
- **Technical vocabulary:** Prefer European Spanish motorcycle terms (*manillar* not *manubrio*, *coche* not *carro*, *neumático* not *llanta*).
- **Diacritics:** Always preserve (á, é, í, ó, ú, ñ, ü). Never strip.
- **Number formatting:** Comma as decimal separator. Period as thousands separator.

### Italian (IT)
- **Formality:** Italian commercial content can go either way. Use *voi/Lei* for formal product pages; *tu* is acceptable for blog posts and enthusiast content. Stay consistent within a post.
- **Tone:** Warm, conversational, expressive. Italian readers respond well to enthusiasm — more latitude for expressive phrasing than French or German.
- **Technical vocabulary:** Italian has strong native motorcycle vocabulary (*manubrio, forcella, ammortizzatore, serbatoio*).
- **Diacritics:** Always preserve (à, è, é, ì, ò, ù).
- **Number formatting:** Comma as decimal separator. Period as thousands separator.

### Dutch (NL)
- **Formality:** Dutch skews informal. Default to *je/jij* for blog posts. Use *u* only if the English source is clearly formal or legalistic.
- **Tone:** Practical, direct, no-nonsense. Dutch readers dislike flowery or overly marketing-driven language.
- **Technical vocabulary:** Dutch motorcycle vocabulary mixes heavily with English. Native terms exist (*stuur, vork, rem, motor*) but English technical terms (*handlebar, clutch, throttle*) are also commonly understood and sometimes preferred in enthusiast contexts.
- **Diacritics:** Rare in Dutch but preserve when present (ë, ï, ü in loan words).
- **Number formatting:** Comma as decimal separator. Period as thousands separator.

### Polish (PL)
- **Formality:** Polish commercial content defaults to formal (*Pan/Pani*). Use direct second-person (*ty*) only for enthusiast-focused content, never for product or technical pages.
- **Tone:** Informative, technical. Polish readers expect specs and practical information.
- **Technical vocabulary:** Polish has native motorcycle terms (*kierownica, widelec, hamulec, silnik*) but English terms are increasingly common among younger riders. Prefer Polish.
- **Diacritics:** Critical — always preserve (ą, ć, ę, ł, ń, ó, ś, ź, ż). Stripping diacritics in Polish is a serious error that damages SEO and readability.
- **Grammar note:** Polish has 7 grammatical cases. Sentence restructuring is sometimes necessary for naturalness — permitted in intro/metadata zones but must preserve meaning in body content.
- **Number formatting:** Comma as decimal separator. Space as thousands separator (1 000).

### Slovenian (SL)
- **Formality:** Slovenian commercial content defaults to formal (*vikanje* — using *vi*). Use informal *ti* only for explicitly enthusiast-focused content.
- **Tone:** Precise, informative. Slovenian is a smaller market — riders often cross-reference English and German content, so accuracy is critical.
- **Technical vocabulary:** Slovenian has native motorcycle terms but leans on loanwords for technical components. When in doubt, prefer the Slovenian term if well-established.
- **Diacritics:** Always preserve (č, š, ž).
- **Grammar note:** Slovenian has dual grammatical number in addition to singular/plural. This is a known challenge for LLM translation — if in doubt, use plural for groups and singular for individual items.
- **Number formatting:** Comma as decimal separator. Period as thousands separator.

### Portuguese (PT — European/Portugal only)
- **Target variant:** European Portuguese (Portugal). Do NOT use Brazilian vocabulary, spelling, or phrasing.
- **Formality:** Portuguese commercial content defaults to formal. Use *você* or third-person constructions. Stay consistent.
- **Tone:** Slightly more formal than Italian or Spanish. Portuguese readers expect clarity and precision.
- **Technical vocabulary:** Use European Portuguese terms specifically:
  - *autocarro* (not *ônibus*)
  - *travão* (not *freio*)
  - *condutor* (not *motorista*)
- **Spelling:** Follow the 1990 Orthographic Agreement but with European Portuguese preferences where they differ.
- **Diacritics:** Always preserve (á, â, ã, ç, é, ê, í, ó, ô, õ, ú).
- **Number formatting:** Comma as decimal separator. Space as thousands separator.

---

## 6. URL and link handling

The workflow handles URL localization automatically via sitemap scraping. The translator model should **never invent, modify, or translate URLs**.

### Rules

| Link type | Behavior |
|---|---|
| Internal product link (legendary-parts.com/en/...) | Replaced with localized URL via sitemap lookup by OEM number. |
| Internal blog link (legendary-parts.com/blog/...) | Replaced with localized URL via sitemap lookup by slug. |
| Internal link not found in target sitemap | **Flagged in Doc for review.** Link kept as-is with visible comment: `[REVIEW: OEM {code} not found in {lang} sitemap]`. |
| External link (any third-party domain) | Kept as original URL. No modification. |
| Anchor text | Translated into target language. Exception: brand names and model names stay English. |

### Inline English anchor annotation (for review)

Every translated internal link in the output Doc must include an inline English annotation for spot-checking:

```
[Translated anchor text](localized-URL) [EN: original English anchor]
```

The annotation is for your Doc review only. A pre-publish step strips all `[EN: ...]` annotations before content goes live — **annotations must never appear on the public site** (violates the one-language-per-page rule).

### URL slug handling

The workflow never rewrites product URL slugs. Slugs are scraped from the target-language sitemap and used as-is. If a product's localized slug on legendary-parts.com is `elevador-de-manillar-superior-oem-55903-05`, that exact slug is used — the model does not attempt to generate, guess, or translate slugs.

---

## 7. Metadata localization

### Title (H1 / `<title>`)
- Must include the localized primary keyword.
- Max 60 characters (hard limit for search display).
- Preserve brand/model names in English.
- Do not translate literally — rewrite for search behavior.

**Example:**
- EN: "Upper Handlebar Clamp for Harley Softail (OEM 55903-05)"
- ES: "Elevador de Manillar Superior Harley Softail (OEM 55903-05)"
- DE: "Obere Lenkerklemme für Harley Softail (OEM 55903-05)"

### Meta description
- Must include the localized primary keyword and a local-tone CTA.
- Max 155 characters.
- Rewrite for click-through, not for literal accuracy.

### H2/H3 subheadings
- Preserve the meaning and structural role of the English subheading.
- Adapt phrasing to include localized secondary keywords where natural.
- Do not merge or split sections.

### Alt text
- Translate faithfully but use the localized keyword variant.
- Keep brand and model names in English.

---

## 8. Cultural adaptation rules

### Units of measurement
- **If the English source uses imperial units (inches, ft-lb, psi):** keep imperial as primary, add metric equivalent in parentheses for EU markets.
- **Example:** "Torque to 25 ft-lb" → "Aprieta a 25 ft-lb (34 Nm)" (ES)
- Applies to all 8 EU-market languages.

### Dates
- Convert US date format (MM/DD/YYYY) to European format (DD/MM/YYYY).
- Exception: OEM production year ranges stay as "2007-2017" format across all languages.

### Currency
- If prices appear in the source, keep as EUR for all 8 markets unless explicitly overridden.

### Humor, idioms, and cultural references
- **Idioms** (e.g., "a piece of cake," "kick the tires") must not be translated literally. Either replace with a local equivalent idiom or rewrite plainly.
- **Puns and wordplay** must be flagged in the Doc for review: `[REVIEW: pun in source — suggest rewrite]`. Do not attempt literal translation.
- **Cultural references** (US-specific — Route 66, Sturgis, Daytona Bike Week) may be preserved but should include brief explanatory phrasing if not globally recognized. Europe-wide references (Wheels & Waves, EICMA) need no explanation.

### Seasonal and climate references
- All 8 target markets are Northern Hemisphere, so hemisphere-specific references rarely apply — but flag any explicit season references for review.

---

## 9. Validation and quality checks

The workflow runs automated validation after translation. The translator model should produce output compatible with these checks.

### Numerical fidelity check
- All numbers, year ranges, OEM codes, and technical values in the source must appear exactly in the target.
- Mismatches are flagged in the Doc before your review email.

### Structural fidelity check
- Paragraph count in target must match source (body content only; metadata is exempt).
- Sentence count per paragraph in body must match source ± 1 (to allow for natural language variation).
- Major deviations are flagged.

### Protected tokens check
- All items in the protected tokens list (Section 3) must appear verbatim.
- Missing or modified tokens are flagged.

### Link integrity check
- Every link in the source has a corresponding link in the target (either localized or flagged-for-review).
- External links are preserved as-is.

### Character limit check
- Title ≤ 60 characters
- Meta description ≤ 155 characters
- Alt text ≤ 125 characters
- Violations are flagged.

---

## 10. Output format

Each translated blog is saved as a Google Doc in the same Drive folder as the English source, with the filename pattern:

```
{original-slug}--{lang-code}.gdoc
```

Example: `upper-handlebar-clamp-oem-55903-05--es.gdoc`

The Doc includes:
1. Translated title (H1)
2. Translated meta description (as a callout box at top)
3. Translated body with inline English anchor annotations on all internal links
4. Translated FAQ section (if present in source)
5. Review flags (inline, highlighted) for: unresolved sitemap lookups, preserved puns/idioms, numerical mismatches, structural deviations
6. Metadata footer: source doc_id, language, translator model used, timestamp, list of all flags raised

---

## 11. What the translator model must NOT do

- Invent OEM numbers, year ranges, or technical specs not present in the source.
- Translate brand names, model names, or protected tokens.
- Merge or split paragraphs in body content.
- Drop hedges or qualifiers ("typically," "usually," "recommended," etc.).
- Invent or modify URLs.
- Strip diacritics.
- Mix languages within the published content (inline EN annotations for Doc review are the only exception, and are stripped pre-publish).
- Translate literally when a literal translation would read as non-native.
- Attempt to translate puns or wordplay — flag instead.
- Switch Spanish variants (must stay ES-ES).
- Switch Portuguese variants (must stay PT-PT).

---

## 12. Escalation triggers (flag for human review)

The translator should flag any of the following in the Doc rather than guess:

- OEM number not found in target sitemap
- Pun, idiom, or cultural reference with no clean local equivalent
- Numerical or year-range value that appears ambiguous in the source
- Sentence whose meaning cannot be preserved without significant restructuring
- Brand or product name not on the protected tokens list but appears proprietary
- Claim that would require regulatory or safety verification in the target market (e.g., emissions compliance, road-legal status)

Flags use the inline format: `[REVIEW: {reason}]` — highlighted in yellow in the Doc.

---

## 13. Structural fidelity — strict rules

The source HTML defines the document structure. Your job is to translate the text content while preserving the structure exactly. You are a translator, not an editor or designer.

**Heading hierarchy:**
- Preserve every heading tag at its exact level. H1 stays H1, H2 stays H2, H3 stays H3. Never promote, demote, or change a heading level.
- The source body sections use H3. Your output must use H3 for those same sections. Do not change them to H2.
- The number of headings in your output must match the number of headings in the source. Count them before finishing.

**Link preservation:**
- Preserve every link from the source. The number of links in your output must match the number of links in the source.
- You may localize the language code segment of internal links from the source domain (e.g., /en/collections/sell → /fr/collections/sell for French translations). Do this for all internal links to the source domain.
- Do not localize external links (links to other domains).
- Do not drop, merge, or invent links. If the source has 8 links, your output must have 8 links.
- Anchor text (the visible link text) should be translated. The URL itself should be preserved or localized as above.

Before returning your output, count the links in your translation and verify the count matches the source.

**Do not invent content:**
- Do not add subtitles, taglines, decorative headings, or section labels that are not present in the source.
- If the source goes directly from H1 to the first body H3, your output must do the same. Do not insert an H2 subtitle between them.
- Do not add introductory phrases, transitions, or summary sentences that do not exist in the source.
- If you feel the structure "needs" something extra to read well in the target language, you are wrong. Translate what is there.

**Length discipline:**
- Your translation should be within ±15% of the source word count.
- If your draft is significantly longer than the source, you are padding. Common padding patterns to avoid: hedging phrases ("it is important to note that"), restating the previous sentence, adding examples not in the source, expanding lists with extra items.
- Tighten before returning. Translation, not expansion.

**Before returning your output, verify:**
1. Heading count matches source (count H1, H2, H3, H4 separately).
2. No headings exist in your output that have no counterpart in source.
3. Word count is within ±15% of source.
4. Link count matches source (count all hyperlinks).

---

*Last updated: 2026-05-07*
*Owner: Haleema*
*Workflow: SEO-Forge translation pipeline*
