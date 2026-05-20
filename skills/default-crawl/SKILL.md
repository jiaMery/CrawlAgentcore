---
name: default-crawl
description: General-purpose web crawler that extracts page title, links, and text content from any URL. Use when the user wants to crawl a webpage without specific data extraction needs.
argument-hint: <url>
---

# Default Web Crawler

Generate a complete, self-contained Python crawler script for the target URL, then execute it.

## Target

$ARGUMENTS

## Libraries

- Use `requests` for HTTP calls and `beautifulsoup4` (bs4) for HTML parsing.
- These are pre-installed in the Code Interpreter runtime.

## Code Structure

- Wrap logic in a `crawl(url: str) -> dict` function.
- Return a dict with keys: `url`, `title`, `links`, `text_content`.
- Set `response.encoding = response.apparent_encoding` before reading `response.text`.

## Error Handling

- Catch network errors gracefully and return `{"error": "<message>"}`.
- Set a request timeout of 10 seconds.
- On HTTP 429 or 503: wait `random.uniform(5, 15)` seconds and retry up to 3 times.

## Performance & Anti-Detection — MANDATORY

Classify the target domain into a tier, then apply the matching session config and delay.
Copy this block verbatim at the top of every script (before any requests):

```python
import random, time
from urllib.parse import urlparse

# ── Tier classification ────────────────────────────────────────────
STRICT_SITES = {
    "douban.com", "zhihu.com", "weibo.com", "sina.com.cn",
    "amazon.com", "amazon.co.jp", "jd.com", "taobao.com",
    "tmall.com", "pinduoduo.com", "booking.com", "yelp.com",
    "instagram.com", "twitter.com", "x.com", "tiktok.com",
}
OPEN_SITES = {
    "jsonplaceholder.typicode.com", "books.toscrape.com",
    "quotes.toscrape.com", "httpbin.org", "api.github.com",
    "docs.python.org", "wikipedia.org",
}

def _tier(url: str) -> str:
    host = urlparse(url).netloc.lstrip("www.")
    if any(host == d or host.endswith("." + d) for d in STRICT_SITES):
        return "STRICT"
    if any(host == d or host.endswith("." + d) for d in OPEN_SITES):
        return "OPEN"
    return "MODERATE"

# delay range (lo, hi) seconds between requests
DELAY    = {"STRICT": (1.5, 3.0), "MODERATE": (0.5, 1.5), "OPEN": (0.0, 0.0)}

UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
]

def _make_session(url: str) -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": random.choice(UAS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": f"{urlparse(url).scheme}://{urlparse(url).netloc}/",
        "Connection": "keep-alive",
    })
    return session

def _get(session, url, tier, **kwargs):
    """GET with tier-appropriate delay and 429/503 backoff retry."""
    lo, hi = DELAY[tier]
    if hi > 0:
        time.sleep(random.uniform(lo, hi))
    for attempt in range(3):
        try:
            resp = session.get(url, timeout=10, **kwargs)
            if resp.status_code in (429, 503):
                wait = random.uniform(5, 15) * (attempt + 1)
                time.sleep(wait)
                continue
            return resp
        except Exception:
            if attempt == 2:
                raise
            time.sleep(random.uniform(2, 5))
    return resp
```

Use `_make_session(url)` and `_get(session, url, tier)` for every HTTP call.
This skill crawls a single page — no concurrency needed.

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
