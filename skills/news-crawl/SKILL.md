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

- Timeout: 15 seconds per request.
- On HTTP 429 or 503: wait `random.uniform(5, 15)` seconds and retry up to 3 times.

## Date Parsing

- Try to parse publish dates into ISO 8601 format (YYYY-MM-DD).
- Check `<time>` elements, `meta[property="article:published_time"]`, and common class names like `.date`, `.published`.

## Performance & Anti-Detection — MANDATORY

Classify the target domain into a tier, then apply the matching session config,
delay, and concurrency. Copy this block verbatim at the top of every script:

```python
import random, time
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed

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

# News articles often load detail pages — moderate concurrency prevents
# overwhelming servers and triggering rate limits.
# (max_workers, delay_lo, delay_hi) per tier
CONCURRENCY = {"STRICT": (2, 2.0, 4.0), "MODERATE": (4, 0.5, 1.5), "OPEN": (6, 0.0, 0.0)}

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

### Concurrent article fetching pattern

Fetch the listing page sequentially to collect article URLs, then fetch each
article detail page concurrently:

```python
tier = _tier(url)
workers, lo, hi = CONCURRENCY[tier]
session = _make_session(url)

# Step 1: fetch listing page (single request)
resp = _get(session, url, lo, hi)
resp.encoding = resp.apparent_encoding
article_urls = extract_article_urls(resp.text)[:max_articles]

# Step 2: fetch each article concurrently
articles = []
with ThreadPoolExecutor(max_workers=workers) as pool:
    futures = {pool.submit(_get, session, au, lo, hi): au for au in article_urls}
    for future in as_completed(futures):
        try:
            r = future.result()
            r.encoding = r.apparent_encoding
            article = parse_article(r.text, futures[future])
            articles.append(article)
        except Exception as e:
            articles.append({"url": futures[future], "error": str(e)})
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
For reference on common news HTML patterns, see [reference.md](reference.md).
