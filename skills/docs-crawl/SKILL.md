---
name: docs-crawl
description: Documentation and wiki crawler that extracts structured content, headings, code blocks, and navigation hierarchy from documentation sites and wikis. Use when the user wants to scrape technical docs, knowledge bases, or wiki pages.
argument-hint: <url> [max_pages]
---

# Documentation & Wiki Crawler

Generate a complete, self-contained Python crawler script optimized for documentation and wiki sites, then execute it.

## Target

$ARGUMENTS

## Libraries

- Use `requests` + `beautifulsoup4`.

## Data to Extract

- Page title, section headings (with hierarchy), body text per section, code blocks (with language tags), internal navigation links.
- Return a dict with key `pages` containing a list of page dicts.

## Multi-Page Crawling

- If the page has a sidebar or table of contents with links, follow up to $1 pages (default: 5).
- Only follow links within the same documentation domain / path prefix.

## Code Structure

- Wrap in `crawl_docs(url: str, max_pages: int = 5) -> dict`.
- Set `response.encoding = response.apparent_encoding` before reading `response.text`.

## Error Handling

- Retry failed requests once before giving up.
- Timeout: 15 seconds per request.

## Content Cleaning

- Strip navigation chrome, footers, cookie banners, and ads.
- Preserve code block formatting and language annotations.

## Output — MANDATORY

The runtime corrupts non-ASCII bytes in stdout.  Every script MUST define and
call this helper as the ONLY way to print results:

```python
import json, base64

def _safe_output(data):
    raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
    b64 = base64.b64encode(raw).decode("ascii")
    print("<<<CRAWLER_B64>>>")
    for i in range(0, len(b64), 76):
        print(b64[i:i+76])
    print("<<<END_CRAWLER_B64>>>")
```

The script MUST:
1. Store the crawl result in a variable named `result`.
2. Call `_safe_output(result)` as the LAST line of the script.
3. Do NOT use `print(json.dumps(...))` — it will corrupt non-ASCII characters.
4. Do NOT use `<<<CRAWLER_JSON>>>`.

For example output format, see [examples/sample-output.json](examples/sample-output.json).
For reference on common documentation HTML patterns, see [reference.md](reference.md).
