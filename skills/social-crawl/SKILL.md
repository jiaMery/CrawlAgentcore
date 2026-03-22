---
name: social-crawl
description: Social media and forum crawler that extracts posts, authors, timestamps, and engagement metrics from forums, discussion boards, and social platforms. Use when the user wants to scrape community discussions, forum threads, or social media feeds.
argument-hint: <url> [max_posts]
---

# Social Media & Forum Crawler

Generate a complete, self-contained Python crawler script optimized for social media and forum pages, then execute it.

## Target

$ARGUMENTS

## Libraries

- Use `requests` + `beautifulsoup4`.

## Data to Extract

- Post content, author / username, timestamp, engagement metrics (likes, upvotes, replies), tags or flair, post URL.
- Return a dict with key `posts` containing a list of post dicts.

## Multi-Post Extraction

- Extract up to $1 posts from the page (default: 10).
- If the page has "load more" or pagination, follow up to 3 pages.

## Code Structure

- Wrap in `crawl_social(url: str, max_posts: int = 10) -> dict`.
- Set `response.encoding = response.apparent_encoding` before reading `response.text`.

## Error Handling

- Retry failed requests once before giving up.
- Timeout: 15 seconds per request.

## Timestamp Handling

- Convert relative timestamps ("2h ago", "yesterday") to ISO 8601 when possible.
- Check `<time datetime="...">` elements first.

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
For reference on common social/forum HTML patterns, see [reference.md](reference.md).
