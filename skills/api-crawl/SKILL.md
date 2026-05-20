---
name: api-crawl
description: API and JSON endpoint crawler that fetches structured data from REST APIs, handling pagination and nested resources. Use when the user wants to crawl a JSON API or extract data from REST endpoints.
argument-hint: <url> [max_pages]
---

# API / JSON Endpoint Crawler

Generate a complete, self-contained Python script that fetches and aggregates data from a JSON API endpoint, then execute it.

## Target

$ARGUMENTS

## Libraries

- Use `requests` and the standard `json` module.

## Data to Extract

- Fetch the JSON response and collect all records / items.
- Detect and follow pagination (query params like `page`, `offset`, `cursor`, or `Link` headers).
- Return a dict with keys: `base_url`, `endpoints_discovered`, `total_records_fetched`.

## Pagination

- Follow pagination up to $1 pages (default: 5).
- Support common patterns: `?page=N`, `?offset=N`, `next` URL in response body, `Link` header.

## Code Structure

- Wrap in `crawl_api(url: str, max_pages: int = 5) -> dict`.
- Set `response.encoding = response.apparent_encoding` before reading `response.text`.

## Error Handling

- Timeout: 15 seconds per request.
- Handle non-JSON responses gracefully (return content-type and a snippet of the body).
- On HTTP 429 or 503: wait `random.uniform(5, 15)` seconds and retry up to 3 times.

## Performance & Anti-Detection — MANDATORY

REST APIs are usually rate-limit-aware. Classify by tier and apply concurrency.
Copy this block verbatim at the top of every script:

```python
import random, time
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed

# ── Tier classification ────────────────────────────────────────────
# APIs with aggressive rate limiting
STRICT_SITES = {
    "api.weibo.com", "api.twitter.com", "api.x.com",
    "api.instagram.com", "graph.facebook.com",
    "open.douban.com",
}
# Open / test APIs — no rate limits
OPEN_SITES = {
    "jsonplaceholder.typicode.com", "api.github.com",
    "httpbin.org", "pokeapi.co", "restcountries.com",
    "api.chucknorris.io", "catfact.ninja",
}

def _tier(url: str) -> str:
    host = urlparse(url).netloc.lstrip("www.")
    if any(host == d or host.endswith("." + d) for d in STRICT_SITES):
        return "STRICT"
    if any(host == d or host.endswith("." + d) for d in OPEN_SITES):
        return "OPEN"
    return "MODERATE"

# API pages are cheap — higher concurrency is safe for most endpoints.
# (max_workers, delay_lo, delay_hi) per tier
CONCURRENCY = {"STRICT": (2, 1.0, 2.0), "MODERATE": (6, 0.1, 0.5), "OPEN": (10, 0.0, 0.0)}

UAS = [
    "Mozilla/5.0 (compatible; CrawlerBot/1.0)",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
]

def _make_session(url: str) -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": random.choice(UAS),
        "Accept": "application/json",
        "Accept-Encoding": "gzip, deflate, br",
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
                # respect Retry-After header if present
                retry_after = int(resp.headers.get("Retry-After", 0))
                wait = max(retry_after, random.uniform(5, 15)) * (attempt + 1)
                time.sleep(wait)
                continue
            return resp
        except Exception:
            if attempt == 2:
                raise
            time.sleep(random.uniform(2, 5))
    return resp
```

### Concurrent page fetching pattern

Discover all page URLs first (page 1 reveals total count / last page), then
fetch remaining pages concurrently:

```python
tier = _tier(url)
workers, lo, hi = CONCURRENCY[tier]
session = _make_session(url)

# Step 1: fetch page 1 to learn total pages
resp = _get(session, build_page_url(url, 1), lo, hi)
data_p1 = resp.json()
total_pages = detect_total_pages(data_p1)  # parse from meta/count fields
all_records = extract_records(data_p1)

# Step 2: fetch remaining pages concurrently
remaining = [build_page_url(url, p) for p in range(2, min(total_pages, max_pages) + 1)]
with ThreadPoolExecutor(max_workers=workers) as pool:
    futures = {pool.submit(_get, session, pu, lo, hi): pu for pu in remaining}
    for future in as_completed(futures):
        try:
            r = future.result()
            all_records.extend(extract_records(r.json()))
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
