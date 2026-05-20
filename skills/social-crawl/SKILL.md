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

- Timeout: 15 seconds per request.
- On HTTP 429 or 503: wait `random.uniform(5, 15)` seconds and retry up to 3 times.

## Timestamp Handling

- Convert relative timestamps ("2h ago", "yesterday") to ISO 8601 when possible.
- Check `<time datetime="...">` elements first.

## Performance & Anti-Detection — MANDATORY

Social sites have the toughest anti-bot measures. Always use conservative
concurrency and the longest delays for STRICT sites.
Copy this block verbatim at the top of every script:

```python
import random, time
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed

# ── Tier classification ────────────────────────────────────────────
# Social platforms with aggressive bot detection
STRICT_SITES = {
    "weibo.com", "zhihu.com", "douban.com",
    "twitter.com", "x.com", "instagram.com",
    "facebook.com", "tiktok.com", "reddit.com",
    "tieba.baidu.com", "v2ex.com",
}
# Forums / communities with no or minimal bot protection
OPEN_SITES = {
    "news.ycombinator.com", "lobste.rs",
    "old.reddit.com",  # less strict than reddit.com
}

def _tier(url: str) -> str:
    host = urlparse(url).netloc.lstrip("www.")
    if any(host == d or host.endswith("." + d) for d in STRICT_SITES):
        return "STRICT"
    if any(host == d or host.endswith("." + d) for d in OPEN_SITES):
        return "OPEN"
    return "MODERATE"

# Social crawls are page-level — concurrency across pages, not within a page.
# Use low workers + long delays for STRICT to avoid triggering bot detection.
# (max_workers, delay_lo, delay_hi) per tier
CONCURRENCY = {"STRICT": (2, 2.5, 5.0), "MODERATE": (3, 1.0, 2.5), "OPEN": (5, 0.3, 1.0)}

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
        # Cookie header: social sites often require a session cookie even for
        # public pages. If you have one, add it here; otherwise omit.
    })
    return session

def _get(session, url, delay_lo, delay_hi, **kwargs):
    """GET with delay and 429/503 backoff retry."""
    if delay_hi > 0:
        time.sleep(random.uniform(delay_lo, delay_hi))
    for attempt in range(3):
        try:
            resp = session.get(url, timeout=15, **kwargs)
            if resp.status_code in (429, 503):
                time.sleep(random.uniform(5, 15) * (attempt + 1))
                continue
            return resp
        except Exception:
            if attempt == 2:
                raise
            time.sleep(random.uniform(2, 5))
    return resp
```

### Concurrent page fetching pattern

Social feeds are paginated. Fetch page 1 first to check structure, then
fetch additional pages concurrently — but respect the tier delay:

```python
tier = _tier(url)
workers, lo, hi = CONCURRENCY[tier]
session = _make_session(url)

# Step 1: fetch first page
resp = _get(session, url, lo, hi)
resp.encoding = resp.apparent_encoding
posts = parse_posts(resp.text)
page_urls = build_next_page_urls(resp.text, url, max_extra_pages=2)

# Step 2: fetch additional pages concurrently
if page_urls:
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_get, session, pu, lo, hi): pu for pu in page_urls}
        for future in as_completed(futures):
            try:
                r = future.result()
                r.encoding = r.apparent_encoding
                posts.extend(parse_posts(r.text))
            except Exception:
                pass
```

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
