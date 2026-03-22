---
name: news-crawl
description: News and article crawler that extracts headlines, authors, publish dates, and article body text from news sites and blogs. Use when the user wants to scrape news articles, blog posts, or editorial content.
argument-hint: <url> [max_articles]
---

# News & Article Crawler

Generate a complete, self-contained Python crawler script optimized for news and article pages, then execute it.

## Target

$ARGUMENTS

## Libraries

- Use `requests` + `beautifulsoup4`.

## Data to Extract

- Headline / title, author(s), publish date, article body text, summary / lead paragraph, tags or categories, canonical URL.
- Return a dict with key `articles` containing a list of article dicts.

## Multi-Article Pages

- If the target is a listing page (e.g. homepage, category page), extract up to $1 articles (default: 5).
- Follow each article link and extract the full content from the detail page.

## Code Structure

- Wrap in `crawl_articles(url: str, max_articles: int = 5) -> dict`.
- Set `response.encoding = response.apparent_encoding` before reading `response.text`.

## Error Handling

- Retry failed requests once before giving up.
- Timeout: 15 seconds per request.

## Date Parsing

- Try to parse publish dates into ISO 8601 format (YYYY-MM-DD).
- Check `<time>` elements, `meta[property="article:published_time"]`, and common class names like `.date`, `.published`.

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
For reference on common news HTML patterns, see [reference.md](reference.md).
