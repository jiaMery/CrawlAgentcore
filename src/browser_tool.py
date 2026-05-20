"""AgentCore Browser tool for CrawlAgentcore.

Wraps the AWS Bedrock AgentCore Browser API as a Strands @tool so the Agent
can call browser_crawl(url, extract_js=True) for STRICT / JS-heavy sites.

Workflow:
  1. StartBrowserSession  — creates a managed Chromium session
  2. UpdateBrowserStream  — activates the automation stream (ENABLED)
  3. InvokeBrowser(navigate via keyType on address bar) + screenshot
  4. InvokeBrowser(screenshot) — capture rendered page
  5. Extract text / links from screenshot via LLM vision, OR inject JS
     via CDP WebSocket automation stream to pull document.body.innerText
  6. StopBrowserSession   — always cleanup

The tool returns a dict compatible with what the main agent expects:
  {"url": ..., "title": ..., "text_content": ..., "links": [...],
   "screenshot_b64": <base64-png>, "method": "browser"}
"""

import base64
import json
import logging
import os
import time
import uuid

import boto3

logger = logging.getLogger(__name__)

BROWSER_ID = os.environ.get("BROWSER_ID", "crawlerBrowser-HCHUMemYzS")
REGION = os.environ.get("AWS_REGION", "us-east-1")

# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _rt_client():
    return boto3.client("bedrock-agentcore", region_name=REGION)


def _start_session(client, browser_id: str, timeout: int = 300) -> str:
    resp = client.start_browser_session(
        browserIdentifier=browser_id,
        name=f"crawl-{uuid.uuid4().hex[:8]}",
        sessionTimeoutSeconds=timeout,
        viewPort={"width": 1280, "height": 900},
    )
    return resp["sessionId"]


def _enable_automation_stream(client, browser_id: str, session_id: str) -> str:
    """Activate the automation (CDP) stream and return its endpoint URL."""
    resp = client.update_browser_stream(
        browserIdentifier=browser_id,
        sessionId=session_id,
        streamUpdate={"automationStreamUpdate": {"streamStatus": "ENABLED"}},
    )
    return resp["streams"]["automationStream"]["streamEndpoint"]


def _wait_stream_ready(client, browser_id: str, session_id: str, retries: int = 10) -> str:
    """Poll until automationStream.streamStatus == ENABLED, return endpoint."""
    for _ in range(retries):
        resp = client.get_browser_session(
            browserIdentifier=browser_id,
            sessionId=session_id,
        )
        stream = resp.get("streams", {}).get("automationStream", {})
        if stream.get("streamStatus") == "ENABLED":
            return stream["streamEndpoint"]
        time.sleep(2)
    raise RuntimeError("Browser automation stream did not become ENABLED in time")


def _invoke(client, browser_id: str, session_id: str, action: dict) -> dict:
    resp = client.invoke_browser(
        browserIdentifier=browser_id,
        sessionId=session_id,
        action=action,
    )
    return resp.get("result", {})


def _navigate(client, browser_id: str, session_id: str, url: str) -> None:
    """Navigate by clicking the address bar, typing the URL, and pressing Enter."""
    # Focus address bar with keyboard shortcut
    _invoke(client, browser_id, session_id,
            {"keyShortcut": {"keys": ["ctrl", "l"]}})
    time.sleep(0.5)
    # Clear + type URL
    _invoke(client, browser_id, session_id,
            {"keyShortcut": {"keys": ["ctrl", "a"]}})
    _invoke(client, browser_id, session_id,
            {"keyType": {"text": url}})
    _invoke(client, browser_id, session_id,
            {"keyPress": {"key": "Return", "presses": 1}})


def _screenshot_b64(client, browser_id: str, session_id: str) -> str:
    """Take a screenshot and return base64-encoded PNG."""
    result = _invoke(client, browser_id, session_id,
                     {"screenshot": {"format": "png"}})
    data = result.get("screenshot", {}).get("data", b"")
    if isinstance(data, (bytes, bytearray)):
        return base64.b64encode(data).decode("ascii")
    return ""


def _cdp_eval(ws_endpoint: str, js_expression: str, timeout: int = 10) -> str:
    """Send a CDP Runtime.evaluate over the automation WebSocket stream."""
    try:
        import websocket  # websocket-client
        ws = websocket.create_connection(ws_endpoint, timeout=timeout)
        msg_id = 1
        ws.send(json.dumps({
            "id": msg_id,
            "method": "Runtime.evaluate",
            "params": {"expression": js_expression, "returnByValue": True},
        }))
        deadline = time.time() + timeout
        while time.time() < deadline:
            raw = ws.recv()
            obj = json.loads(raw)
            if obj.get("id") == msg_id:
                ws.close()
                return obj.get("result", {}).get("result", {}).get("value", "")
        ws.close()
    except Exception as e:
        logger.warning("CDP eval failed: %s", e)
    return ""


def _stop_session(client, browser_id: str, session_id: str) -> None:
    try:
        client.stop_browser_session(
            browserIdentifier=browser_id,
            sessionId=session_id,
        )
    except Exception as e:
        logger.warning("stop_browser_session failed: %s", e)


# ---------------------------------------------------------------------------
# High-level crawl function (used by the Strands @tool below)
# ---------------------------------------------------------------------------

def _browser_crawl_impl(
    url: str,
    wait_seconds: float = 3.0,
    use_cdp_js: bool = True,
) -> dict:
    """
    Open url in a managed Chromium session, render JS, extract content.

    Returns dict with keys: url, title, text_content, links, screenshot_b64, method.
    """
    client = _rt_client()
    session_id = None
    try:
        # 1. Start session
        session_id = _start_session(client, BROWSER_ID)
        logger.info("Browser session started: %s", session_id)

        # 2. Enable automation stream (CDP)
        _enable_automation_stream(client, BROWSER_ID, session_id)
        ws_endpoint = _wait_stream_ready(client, BROWSER_ID, session_id)

        # 3. Navigate
        _navigate(client, BROWSER_ID, session_id, url)
        time.sleep(wait_seconds)  # wait for JS rendering

        # 4. Extract via CDP JS injection (fastest, most accurate)
        title = ""
        text_content = ""
        links = []
        if use_cdp_js and ws_endpoint:
            title = _cdp_eval(ws_endpoint, "document.title")
            text_content = _cdp_eval(
                ws_endpoint,
                "document.body ? document.body.innerText.slice(0, 50000) : ''",
            )
            links_json = _cdp_eval(
                ws_endpoint,
                "JSON.stringify([...document.querySelectorAll('a[href]')]"
                ".map(a=>({text:a.innerText.trim().slice(0,80),href:a.href}))"
                ".filter(a=>a.href.startsWith('http')).slice(0,100))",
            )
            try:
                links = json.loads(links_json) if links_json else []
            except (json.JSONDecodeError, TypeError):
                links = []

        # 5. Screenshot (fallback for JS-heavy / visual content)
        screenshot_b64 = _screenshot_b64(client, BROWSER_ID, session_id)

        return {
            "url": url,
            "title": title,
            "text_content": text_content,
            "links": links,
            "screenshot_b64": screenshot_b64,
            "method": "browser",
        }

    except Exception as e:
        logger.error("browser_crawl_impl failed for %s: %s", url, e)
        return {"url": url, "error": str(e), "method": "browser"}
    finally:
        if session_id:
            _stop_session(client, BROWSER_ID, session_id)


# ---------------------------------------------------------------------------
# Strands @tool — registered with the Agent
# ---------------------------------------------------------------------------

try:
    from strands import tool

    @tool
    def browser_crawl(url: str, wait_seconds: float = 3.0) -> str:
        """Crawl a webpage using a real managed Chromium browser (AgentCore Browser).

        Use this tool instead of code_interpreter for sites that:
        - Require JavaScript rendering (SPA / React / Vue / dynamic content)
        - Have aggressive bot detection (fingerprint / canvas checks)
        - Return 403 / empty content when accessed with plain HTTP requests

        Args:
            url: The URL to crawl.
            wait_seconds: Seconds to wait after navigation for JS rendering (default 3.0).
                          Increase to 5-8 for slow SPA sites.

        Returns:
            JSON string with keys: url, title, text_content, links (list),
            screenshot_b64 (base64 PNG), method="browser".
            On error: {"url": ..., "error": "...", "method": "browser"}
        """
        result = _browser_crawl_impl(url, wait_seconds=wait_seconds)
        return json.dumps(result, ensure_ascii=False)

except ImportError:
    # strands not available (e.g., running tests locally without full venv)
    def browser_crawl(url: str, wait_seconds: float = 3.0) -> str:  # type: ignore[misc]
        result = _browser_crawl_impl(url, wait_seconds=wait_seconds)
        return json.dumps(result, ensure_ascii=False)
