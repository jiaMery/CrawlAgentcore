---
name: ecommerce-crawl
description: E-commerce product crawler that extracts product names, prices, images, and availability from online stores. Use when the user wants to scrape product listings or catalog pages.
argument-hint: <url> [max_pages]
---

# E-Commerce Product Crawler

Generate a complete, self-contained Python crawler script optimized for e-commerce product pages, then execute it.

## Target

$ARGUMENTS

## Libraries

- Use `requests` + `beautifulsoup4`.

## Data to Extract

- Product name, price, currency, description, image URLs, availability status.
- Return a dict with key `products` containing a list of product dicts.

## Pagination

- If the page has pagination, follow up to $1 pages max (default: 3).

## Code Structure

- Wrap in `crawl_products(url: str, max_pages: int = 3) -> dict`.
- Set `response.encoding = response.apparent_encoding` before reading `response.text`.

## Error Handling

- Timeout: 15 seconds per request.
- On HTTP 429 or 503: wait `random.uniform(5, 15)` seconds and retry up to 3 times.

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

# (max_workers, delay_lo, delay_hi) per tier
CONCURRENCY = {"STRICT": (3, 1.5, 3.0), "MODERATE": (5, 0.3, 1.0), "OPEN": (8, 0.0, 0.0)}

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

### Concurrent page fetching pattern

Use `ThreadPoolExecutor` to fetch all pages in parallel:

```python
tier = _tier(url)
workers, lo, hi = CONCURRENCY[tier]
session = _make_session(url)

# Build list of page URLs first, then fetch concurrently
page_urls = [build_page_url(base_url, p) for p in range(1, max_pages + 1)]
all_products = []

with ThreadPoolExecutor(max_workers=workers) as pool:
    futures = {pool.submit(_get, session, pu, lo, hi): pu for pu in page_urls}
    for future in as_completed(futures):
        try:
            resp = future.result()
            resp.encoding = resp.apparent_encoding
            products = parse_products(resp.text)   # your BeautifulSoup logic
            all_products.extend(products)
        except Exception as e:
            pass  # skip failed pages
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
For reference on common e-commerce HTML patterns, see [reference.md](reference.md).
