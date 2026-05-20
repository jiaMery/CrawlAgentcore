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

- Timeout: 15 seconds per request.
- On HTTP 429 or 503: wait `random.uniform(5, 15)` seconds and retry up to 3 times.

## Content Cleaning

- Strip navigation chrome, footers, cookie banners, and ads.
- Preserve code block formatting and language annotations.

## Performance & Anti-Detection — MANDATORY

Docs sites are generally OPEN or MODERATE. Classify by tier and apply concurrency.
Copy this block verbatim at the top of every script:

```python
import random, time
from urllib.parse import urlparse, urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed

# ── Tier classification ────────────────────────────────────────────
STRICT_SITES = {
    "confluence.atlassian.com", "notion.so",
}
OPEN_SITES = {
    "docs.python.org", "developer.mozilla.org", "wikipedia.org",
    "readthedocs.io", "docs.github.com", "docs.aws.amazon.com",
    "docs.docker.com", "kubernetes.io",
}

def _tier(url: str) -> str:
    host = urlparse(url).netloc.lstrip("www.")
    if any(host == d or host.endswith("." + d) for d in STRICT_SITES):
        return "STRICT"
    if any(host == d or host.endswith("." + d) for d in OPEN_SITES):
        return "OPEN"
    return "MODERATE"

# Docs pages are lightweight — higher concurrency is acceptable.
# (max_workers, delay_lo, delay_hi) per tier
CONCURRENCY = {"STRICT": (2, 1.5, 3.0), "MODERATE": (5, 0.2, 0.8), "OPEN": (8, 0.0, 0.0)}

UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
]

def _make_session(url: str) -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": random.choice(UAS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": f"{urlparse(url).scheme}://{urlparse(url).netloc}/",
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

Fetch the root page first to discover sidebar/TOC links, then crawl discovered
pages concurrently:

```python
tier = _tier(url)
workers, lo, hi = CONCURRENCY[tier]
session = _make_session(url)
base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"

# Step 1: fetch root page and collect nav links
resp = _get(session, url, lo, hi)
resp.encoding = resp.apparent_encoding
root_data = parse_doc_page(resp.text, url)
nav_links = [urljoin(base, l) for l in root_data.get("nav_links", [])]
nav_links = list(dict.fromkeys(nav_links))[:max_pages - 1]  # dedup, cap

# Step 2: fetch remaining pages concurrently
pages = [root_data]
with ThreadPoolExecutor(max_workers=workers) as pool:
    futures = {pool.submit(_get, session, nl, lo, hi): nl for nl in nav_links}
    for future in as_completed(futures):
        try:
            r = future.result()
            r.encoding = r.apparent_encoding
            pages.append(parse_doc_page(r.text, futures[future]))
        except Exception as e:
            pages.append({"url": futures[future], "error": str(e)})
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
For reference on common documentation HTML patterns, see [reference.md](reference.md).
