# Workflow: [Name]

## Objective
<!-- One sentence: what does this workflow accomplish? -->

## When to Use This
<!-- What triggers this workflow? What problem does it solve? -->

## Inputs Required
<!-- What does the agent need before starting? -->
| Input | Type | Source | Notes |
|-------|------|--------|-------|
| `example_input` | string | User-provided | Description |

## Tools Used
<!-- Which scripts in tools/ does this workflow call, and in what order? -->
| Step | Script | Purpose |
|------|--------|---------|
| 1 | `tools/example.py` | Description of what it does |

## Steps

### Step 1: [Action]
**Script:** `tools/example.py`
**Inputs:** `--input_param value`
**Output:** `.tmp/output_file.json`

```bash
python tools/example.py --param value
```

What to check before moving on:
- [ ] Output file exists and is non-empty
- [ ] No error messages in terminal

### Step 2: [Action]
...

## Expected Output
<!-- What does success look like? Where does the final deliverable go? -->
- Final output location: Google Sheet / Slides / etc.
- Format: 

## Error Handling
<!-- Known failure modes and how to recover -->

| Error | Likely Cause | Fix |
|-------|-------------|-----|
| `RateLimitError` | Too many requests | Wait X seconds, retry |
| `FileNotFoundError` | Missing input | Run Step N first |

## Notes & Learnings
<!-- Document quirks, rate limits, API gotchas discovered during use -->
<!-- This section grows over time — it's the self-improvement record -->
