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

## Headers

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
