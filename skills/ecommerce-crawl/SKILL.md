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

- Retry failed requests once before giving up.
- Timeout: 15 seconds per request.

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
