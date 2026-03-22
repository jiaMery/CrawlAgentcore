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

- Retry failed requests once before giving up.
- Timeout: 15 seconds per request.
- Handle non-JSON responses gracefully (return content-type and a snippet of the body).

## Headers

- Send `Accept: application/json`.
- Use a realistic User-Agent header.

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
