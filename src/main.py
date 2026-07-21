"""Crawler Agent — generates crawler code and runs it in AgentCore Code Interpreter."""

import ast
import json
import logging
import os
import re
import base64

os.environ["BYPASS_TOOL_CONSENT"] = "true"

from strands import Agent
from strands_tools.code_interpreter import AgentCoreCodeInterpreter

try:
    from src.skills import load_skill, list_skills
except ModuleNotFoundError:
    from skills import load_skill, list_skills
from bedrock_agentcore.runtime import BedrockAgentCoreApp

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Observability — Strands OpenTelemetry → AWS X-Ray OTLP endpoint
# ---------------------------------------------------------------------------
class _RefreshingAWS4Auth:
    """Wrapper that refreshes SigV4 credentials on every request.

    boto3 credential objects can expire (e.g., ECS/EC2 task-role tokens).
    Re-fetching credentials on each call ensures the signature is always valid.
    """

    def __init__(self, boto3_session, region: str, service: str) -> None:
        self._boto3_session = boto3_session
        self._region = region
        self._service = service

    def __call__(self, r):
        from requests_aws4auth import AWS4Auth

        creds = self._boto3_session.get_credentials().get_frozen_credentials()
        auth = AWS4Auth(
            creds.access_key,
            creds.secret_key,
            self._region,
            self._service,
            session_token=creds.token,
        )
        return auth(r)


def _setup_observability() -> None:
    region = os.environ.get("AWS_REGION", "us-east-1")
    service_name = os.environ.get("OTEL_SERVICE_NAME", "crawler-agentcore")
    os.environ.setdefault("OTEL_SERVICE_NAME", service_name)

    try:
        import boto3
        import requests
        from strands.telemetry.config import StrandsTelemetry

        boto3_session = boto3.Session()
        session = requests.Session()
        session.auth = _RefreshingAWS4Auth(boto3_session, region, "xray")

        endpoint = f"https://xray.{region}.amazonaws.com/v1/traces"
        StrandsTelemetry().setup_otlp_exporter(endpoint=endpoint, session=session)
        logger.info("Observability: X-Ray OTLP tracing enabled → %s", endpoint)
    except Exception as e:
        logger.warning("Observability: setup failed (non-fatal): %s", e)


_setup_observability()

# ---------------------------------------------------------------------------
# AgentCore Code Interpreter tool
# ---------------------------------------------------------------------------
REGION = os.environ.get("AWS_REGION", "us-east-1")
CODE_INTERPRETER_ID = os.environ.get("CODE_INTERPRETER_ID")
if not CODE_INTERPRETER_ID:
    raise RuntimeError("CODE_INTERPRETER_ID environment variable is not set")
code_interpreter_tool = AgentCoreCodeInterpreter(region=REGION, identifier=CODE_INTERPRETER_ID)

# ---------------------------------------------------------------------------
# AgentCore Browser tool (optional — loaded only when use_browser=True)
# ---------------------------------------------------------------------------
_browser_crawl_impl = None
try:
    try:
        from src.browser_tool import browser_crawl as _browser_crawl_tool, _browser_crawl_impl
    except ModuleNotFoundError:
        from browser_tool import browser_crawl as _browser_crawl_tool, _browser_crawl_impl
    BROWSER_TOOL_AVAILABLE = True
    logger.info("Browser tool loaded (BROWSER_ID=%s)",
                os.environ.get("BROWSER_ID", "<not set>"))
except Exception as _e:
    BROWSER_TOOL_AVAILABLE = False
    _browser_crawl_tool = None
    logger.warning("Browser tool not available: %s", _e)

# ---------------------------------------------------------------------------
# System prompt templates
# ---------------------------------------------------------------------------
SYSTEM_PROMPT_TEMPLATE = """You are a web-crawler code generator and executor.

## Workflow
1. Read the crawl-style instructions below carefully.
2. Based on the user's target URL (and optional parameters), generate a
   complete, self-contained Python script that performs the crawl.
3. Execute the script using the code_interpreter tool.
4. Return the crawl results to the user.

## Crawl-Style Instructions
{crawl_style}

## CRITICAL Rules
- Always generate the full Python script — do NOT ask the user to fill in blanks.
- Store the final crawl data in a variable named `result`.
- You MUST call `_safe_output(result)` at the end of every script.
  This is the ONLY allowed way to output data.  Using print(json.dumps(...))
  will corrupt non-ASCII characters and is FORBIDDEN.
- If the crawl fails, call `_safe_output({{"error": "<message>"}})`.
- Do NOT install packages with pip — only use libraries available in the runtime
  (requests, beautifulsoup4, json, re, urllib, etc.).
- When making HTTP requests to sites that may return non-ASCII content, set
  `response.encoding = response.apparent_encoding` (or `'utf-8'`) before reading
  `response.text` to avoid charset mis-detection.
"""

# Appended to system prompt when browser_crawl tool is available (auto mode)
BROWSER_HINT = """
## Browser Tool (browser_crawl)

You have access to TWO tools:
1. **code_interpreter** — runs Python scripts (requests + BeautifulSoup). Fast and cheap.
2. **browser_crawl** — opens a real managed Chromium browser with full JS rendering.

### When to use browser_crawl instead of code_interpreter
- The target URL requires JavaScript to display content (SPA / React / Vue apps)
- Plain HTTP requests return 403, captcha page, or empty body
- The user explicitly asked to use the browser

### When to use code_interpreter (default)
- Static HTML pages (most news, docs, APIs, e-commerce)
- The user did NOT explicitly request browser mode

### browser_crawl usage
Call: browser_crawl(url="https://example.com", wait_seconds=3.0)
Returns JSON with: url, title, text_content, links, screenshot_b64, method="browser"
Parse the returned JSON string with json.loads() to access the fields.
Do NOT use _safe_output() with browser results — return them directly in your reply.
"""

# Replaces browser hint when use_browser=True is explicitly set — MANDATORY
BROWSER_FORCE = """
## MANDATORY: You MUST use browser_crawl for this request

The user has explicitly enabled browser mode. You MUST call browser_crawl() as your
crawling tool. Do NOT use code_interpreter for the actual page fetch.

### browser_crawl usage
Call: browser_crawl(url="https://example.com", wait_seconds=3.0)
- Increase wait_seconds to 5-8 for slow SPA sites or login pages
- Returns JSON string: parse with json.loads() to get url, title, text_content, links, screenshot_b64, method="browser"
- Do NOT wrap the result in _safe_output() — return it directly

You may still use code_interpreter ONLY for post-processing the crawled data (e.g.,
parsing JSON, filtering links, formatting output). The initial page fetch MUST use browser_crawl.
"""

# ---------------------------------------------------------------------------
# Extract raw crawler JSON from agent conversation history
# ---------------------------------------------------------------------------
_CRAWLER_JSON_RE = re.compile(
    r"<<<CRAWLER_JSON>>>\s*(.*?)\s*<<<END_CRAWLER_JSON>>>", re.DOTALL
)
_CRAWLER_B64_RE = re.compile(
    r"<<<CRAWLER_B64>>>\s*(.*?)\s*<<<END_CRAWLER_B64>>>", re.DOTALL
)


# ---------------------------------------------------------------------------
# Mojibake repair: fix UTF-8 content that was decoded as Latin-1
# ---------------------------------------------------------------------------
def _repair_mojibake(text: str) -> str:
    """Best-effort repair of UTF-8 text that was incorrectly decoded as Latin-1."""
    result = text
    for _ in range(3):
        try:
            candidate = result.encode('latin-1').decode('utf-8')
        except (UnicodeDecodeError, UnicodeEncodeError):
            break
        if candidate == result:
            break
        result = candidate
    return result


def _looks_like_mojibake(obj) -> bool:
    """Detect if a parsed JSON structure contains mojibake (encoding corruption)."""
    text = json.dumps(obj, ensure_ascii=False) if not isinstance(obj, str) else obj
    if not text:
        return False
    mojibake_markers = ['Ã¨', 'Ã¥', 'Ã¦', 'Ã©', 'Ã§', 'Â·', 'Ã¤', 'Ã¬',
                        'Ã¯', 'Ã³', 'Ã¹', 'Ã¼', 'Ã¶', 'Ã±']
    marker_count = sum(text.count(m) for m in mojibake_markers)
    high_chars = sum(1 for c in text if 0x80 <= ord(c) <= 0xFF)
    total_chars = len(text)
    if total_chars == 0:
        return False
    high_ratio = high_chars / total_chars
    return marker_count >= 3 or (high_ratio > 0.15 and marker_count >= 1)


def _repair_mojibake_recursive(obj):
    """Apply mojibake repair to all string values in a JSON-like structure."""
    if isinstance(obj, str):
        return _repair_mojibake(obj)
    if isinstance(obj, dict):
        return {k: _repair_mojibake_recursive(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_repair_mojibake_recursive(item) for item in obj]
    return obj


def _decode_candidates(raw: str) -> list[str]:
    """Generate multiple decode attempts for Code Interpreter output."""
    candidates = [raw]
    repaired = _repair_mojibake(raw)
    if repaired != raw:
        candidates.insert(0, repaired)
    unescaped = raw.replace('\\n', '\n').replace('\\t', '\t').replace('\\r', '\r')
    candidates.append(unescaped)
    repaired_unescaped = _repair_mojibake(unescaped)
    if repaired_unescaped != unescaped:
        candidates.append(repaired_unescaped)
    double_unescaped = unescaped.replace('\\"', '"')
    candidates.append(double_unescaped)
    if re.search(r'\\u[0-9a-fA-F]{4}', raw):
        try:
            candidates.append(
                raw.encode('raw_unicode_escape').decode('unicode_escape')
            )
        except (UnicodeDecodeError, ValueError):
            pass
    return candidates


def _unwrap_ci_text(text: str) -> str:
    """Unwrap Code Interpreter toolResult format.

    The CI wraps stdout in a Python repr: [{'type': 'text', 'text': '...'}]
    We extract the inner 'text' value to find our markers/JSON.
    """
    try:
        parsed = ast.literal_eval(text)
        if isinstance(parsed, list):
            parts = []
            for item in parsed:
                if isinstance(item, dict) and 'text' in item:
                    parts.append(item['text'])
            if parts:
                return '\n'.join(parts)
    except (ValueError, SyntaxError):
        pass
    # Fallback: regex extract 'text': '...' values
    inner_texts = re.findall(r"'text':\s*'((?:[^'\\]|\\.)*)'", text)
    if not inner_texts:
        inner_texts = re.findall(r'"text":\s*"((?:[^"\\]|\\.)*)"', text)
    if inner_texts:
        return '\n'.join(inner_texts)
    return text


def _extract_crawler_output(agent) -> dict | list | None:
    """Walk the agent's message history and pull out the raw crawler JSON.

    The Code Interpreter tool result contains stdout from the executed script.
    We look for <<<CRAWLER_B64>>> or <<<CRAWLER_JSON>>> delimiters, or bare JSON.
    The CI wraps stdout in [{'type': 'text', 'text': '...'}] format, so we
    unwrap that first.
    """
    messages = getattr(agent, "messages", None) or []

    def _try_parse(text: str):
        """Try to extract and parse JSON from text containing our delimiters."""
        unwrapped = _unwrap_ci_text(text)

        for search_text in ([unwrapped, text] if unwrapped != text else [text]):
            text_no_nl = search_text.replace('\n', '').replace('\r', '')

            # Try base64-encoded output first (preferred, encoding-safe)
            m_b64 = _CRAWLER_B64_RE.search(search_text)
            if not m_b64:
                m_b64 = _CRAWLER_B64_RE.search(text_no_nl)
            if m_b64:
                raw_b64 = re.sub(r'\s+', '', m_b64.group(1).strip())
                try:
                    decoded_bytes = base64.b64decode(raw_b64)
                    return json.loads(decoded_bytes.decode('utf-8'))
                except Exception:
                    pass

            # Legacy: try plain JSON delimiters
            m = _CRAWLER_JSON_RE.search(search_text)
            if m:
                raw = m.group(1).strip()
                raw = re.sub(r'\x1b\[[0-9;]*m', '', raw)
                raw = raw.replace('\x00', '')
                for candidate in _decode_candidates(raw):
                    candidate = candidate.strip()
                    try:
                        return _repair_mojibake_recursive(json.loads(candidate))
                    except (json.JSONDecodeError, TypeError):
                        pass
                    for sc, ec in [('{', '}'), ('[', ']')]:
                        si, ei = candidate.find(sc), candidate.rfind(ec)
                        if si != -1 and ei > si:
                            try:
                                return _repair_mojibake_recursive(
                                    json.loads(candidate[si:ei + 1]))
                            except (json.JSONDecodeError, TypeError):
                                continue
                return _repair_mojibake(raw)

            # Fallback: no delimiters — try to find bare JSON
            text_clean = re.sub(r'\x1b\[[0-9;]*m', '', search_text).strip()
            for sc, ec in [('{', '}'), ('[', ']')]:
                si, ei = text_clean.find(sc), text_clean.rfind(ec)
                if si != -1 and ei > si:
                    snippet = text_clean[si:ei + 1]
                    try:
                        parsed = json.loads(snippet)
                        if isinstance(parsed, dict) and len(parsed) >= 2:
                            return _repair_mojibake_recursive(parsed)
                        if isinstance(parsed, list) and len(parsed) >= 1:
                            return _repair_mojibake_recursive(parsed)
                    except (json.JSONDecodeError, TypeError):
                        pass
        return None

    for msg in reversed(messages):
        content = msg.get("content") if isinstance(msg, dict) else None
        if not content:
            continue
        # Check toolResult blocks first (Code Interpreter stdout)
        for block in content:
            tool_result = block.get("toolResult") if isinstance(block, dict) else None
            if not tool_result:
                continue
            for item in tool_result.get("content", []):
                if isinstance(item, dict):
                    text = item.get("text", "")
                    json_content = item.get("json")
                    if json_content:
                        if isinstance(json_content, (dict, list)):
                            return _repair_mojibake_recursive(json_content)
                        try:
                            return _repair_mojibake_recursive(
                                json.loads(str(json_content)))
                        except (json.JSONDecodeError, TypeError):
                            pass
                    parsed = _try_parse(text)
                    if parsed is not None:
                        return parsed
        # Also check assistant text blocks
        for block in content:
            text = block.get("text", "") if isinstance(block, dict) else ""
            parsed = _try_parse(text)
            if parsed is not None:
                return parsed
    return None


# ---------------------------------------------------------------------------
# Skill auto-selector
# ---------------------------------------------------------------------------
SELECTOR_PROMPT = """You are a skill selector. Given a user's crawl request and a list of available skills, pick the single best skill.

Available skills:
{skills_json}

User request: {prompt}

Reply with ONLY a JSON object: {{"skill": "<skill-name>"}}
Do NOT include any other text."""


def _auto_select_skill(prompt: str) -> str:
    """Use the LLM to pick the best skill based on the user's prompt."""
    skills = list_skills()
    if len(skills) <= 1:
        return skills[0]["name"] if skills else "default-crawl"

    skills_json = json.dumps(skills, indent=2)
    from strands.models import BedrockModel
    from botocore.config import Config as BotocoreConfig
    selector = Agent(
        model=BedrockModel(
            model_id="us.anthropic.claude-sonnet-4-5",
            boto_client_config=BotocoreConfig(read_timeout=300, connect_timeout=10),
        ),
        tools=[],
        system_prompt=SELECTOR_PROMPT.format(skills_json=skills_json, prompt=prompt),
    )
    result = selector("Pick the best skill for this request.")
    response_text = ""
    if hasattr(result, "message"):
        msg = result.message
        if isinstance(msg, dict) and "content" in msg:
            for block in msg["content"]:
                if isinstance(block, dict) and "text" in block:
                    response_text = block["text"]
                    break
        elif isinstance(msg, str):
            response_text = msg

    try:
        parsed = json.loads(response_text)
        selected = parsed.get("skill", "default-crawl")
    except (json.JSONDecodeError, TypeError):
        for s in skills:
            if s["name"] in response_text:
                selected = s["name"]
                break
        else:
            selected = "default-crawl"

    logger.info(f"Auto-selected skill: {selected}")
    return selected


# ---------------------------------------------------------------------------
# BedrockAgentCoreApp
# ---------------------------------------------------------------------------
app = BedrockAgentCoreApp()


def _ensure_ascii_safe(obj):
    """Recursively convert all string values AND dict keys to ASCII-safe form.

    The agentcore runtime serializes responses with ensure_ascii=False, and the
    transport layer corrupts non-ASCII bytes.  By pre-escaping all non-ASCII
    characters we guarantee the JSON survives transport intact.
    """
    if isinstance(obj, str):
        return json.dumps(obj, ensure_ascii=True)[1:-1]
    if isinstance(obj, dict):
        return {
            json.dumps(k, ensure_ascii=True)[1:-1]: _ensure_ascii_safe(v)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_ensure_ascii_safe(item) for item in obj]
    return obj


@app.entrypoint
def invoke(payload: dict, context: dict) -> dict:
    """Handle an incoming crawl request.

    Payload fields:
      prompt       (str)  — natural-language crawl request
      skill        (str)  — optional: force a specific skill name
      args         (str)  — optional: arguments forwarded to the skill
      use_browser  (bool) — optional: inject browser_crawl tool (default False)
    """
    prompt = payload.get("prompt", "")
    explicit_skill = payload.get("skill")
    skill_args = payload.get("args", prompt)
    use_browser = bool(payload.get("use_browser", False))

    if explicit_skill:
        skill_name = explicit_skill
    else:
        skill_name = _auto_select_skill(prompt)

    skill = load_skill(skill_name, arguments=skill_args)
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(crawl_style=skill.content)

    # ── Browser fast-path: skip Agent tool-call loop to avoid Runtime timeout ──
    # When use_browser=True, call _browser_crawl_impl directly instead of routing
    # through the Agent. This saves 2-3 LLM roundtrips (~80-120s) and keeps the
    # total request well within the AgentCore Runtime timeout ceiling (~145s).
    if use_browser and BROWSER_TOOL_AVAILABLE and _browser_crawl_impl is not None:
        import re as _re_url
        # Extract URL from prompt if present, otherwise pass full prompt as URL hint
        _url_match = _re_url.search(r'https?://\S+', prompt)
        target_url = _url_match.group(0).rstrip('.,)"\'') if _url_match else prompt

        logger.info("Browser fast-path: crawling %s directly", target_url)
        browser_result = _browser_crawl_impl(target_url, wait_seconds=3.0)

        response = {
            "result": {"content": [{"text": f"Browser crawl completed for {target_url}"}]},
            "crawler_output": browser_result,
            "skill_used": skill_name,
            "skill_description": skill.description,
            "auto_selected": explicit_skill is None,
            "browser_used": True,
            "web_bot_auth_enabled": os.environ.get("BROWSER_SIGNING_ENABLED", "").lower() in ("1", "true", "yes"),
            "available_skills": list_skills(),
        }
        return _ensure_ascii_safe(response)

    elif use_browser and not BROWSER_TOOL_AVAILABLE:
        logger.warning("use_browser=True but browser tool is not available; falling back to code_interpreter")

    # ── Standard Agent path (code_interpreter) ──
    tools = [code_interpreter_tool.code_interpreter]

    from strands.models import BedrockModel
    from botocore.config import Config as BotocoreConfig
    bedrock_model = BedrockModel(
        model_id="us.anthropic.claude-sonnet-4-5",
        boto_client_config=BotocoreConfig(read_timeout=300, connect_timeout=10),
    )
    agent = Agent(
        model=bedrock_model,
        tools=tools,
        system_prompt=system_prompt,
    )

    result = agent(prompt)

    crawler_output = _extract_crawler_output(agent)

    # ── Retry: output is None — probe for result variable via base64 ──
    if crawler_output is None:
        _b64_extract_code = (
            "import json, base64\n"
            "_data = None\n"
            "for _name in ['result', 'data', 'output', 'results', 'movies',\n"
            "              'products', 'articles', 'items', 'records', 'crawl_result',\n"
            "              'movie_list', 'all_movies', 'top250']:\n"
            "    try:\n"
            "        _data = eval(_name)\n"
            "        break\n"
            "    except NameError:\n"
            "        continue\n"
            "if _data is not None:\n"
            "    raw = json.dumps(_data, ensure_ascii=False).encode('utf-8')\n"
            "    b64 = base64.b64encode(raw).decode('ascii')\n"
            "    print('<<<CRAWLER_B64>>>')\n"
            "    for i in range(0, len(b64), 76):\n"
            "        print(b64[i:i+76])\n"
            "    print('<<<END_CRAWLER_B64>>>')\n"
            "else:\n"
            "    print('NO_RESULT_VARIABLE_FOUND')\n"
        )
        try:
            agent(
                "Run this exact code, do not modify it:\n\n"
                "```python\n" + _b64_extract_code + "```"
            )
            retry_output = _extract_crawler_output(agent)
            if retry_output is not None:
                crawler_output = retry_output
        except Exception as e:
            logger.warning(f"Variable probe failed: {e}")

    # ── Retry: output exists but is mojibake ──
    if crawler_output and _looks_like_mojibake(crawler_output):
        try:
            agent(
                "The output has encoding corruption. Re-run the crawl using "
                "_safe_output(result) with <<<CRAWLER_B64>>> delimiters."
            )
            retry_output = _extract_crawler_output(agent)
            if retry_output and not _looks_like_mojibake(retry_output):
                crawler_output = retry_output
        except Exception as e:
            logger.warning(f"Mojibake retry failed: {e}")

    response = {
        "result": result.message,
        "crawler_output": crawler_output,
        "skill_used": skill.name,
        "skill_description": skill.description,
        "auto_selected": explicit_skill is None,
        "browser_used": False,
        "available_skills": list_skills(),
    }

    return _ensure_ascii_safe(response)


if __name__ == "__main__":
    app.run()
