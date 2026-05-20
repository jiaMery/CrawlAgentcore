#!/usr/bin/env python3
"""
Crawler Agent — 交互式客户端 / Interactive Client

用自然语言描述你想爬取的内容，Agent 会自动选择合适的爬虫技能并执行。
Describe what you want to crawl in natural language. The agent auto-selects
the best skill and executes the crawl.

用法 / Usage:
    python crawler_cli.py
    python crawler_cli.py --dev          # 使用本地开发服务器
    python crawler_cli.py --lang zh      # 界面语言：中文
    python crawler_cli.py --lang en      # UI language: English
    python crawler_cli.py --output results.json  # 保存结果到文件

示例输入 / Example inputs:
    爬取豆瓣电影TOP250的电影名称、评分、导演等信息
    Scrape all product prices from https://books.toscrape.com
    获取 https://news.ycombinator.com 的最新新闻标题和链接
    Fetch user data from https://jsonplaceholder.typicode.com/users
"""

import argparse
import json
import os
import subprocess
import sys
import time
import uuid

# Force UTF-8 for stdout/stderr so Chinese characters display correctly
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr.encoding != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")


# ── Unicode unescape helper ────────────────────────────────────────────

import re as _re

_UNICODE_ESCAPE_RE = _re.compile(r'[\\]u([0-9a-fA-F]{4})')


def _unescape_unicode_str(s: str) -> str:
    """Decode literal \\uXXXX sequences and JSON escapes in a string.

    The server escapes non-ASCII characters to \\uXXXX form so they survive
    the agentcore transport layer.  After json.loads the sequences remain as
    literal backslash-u text because they are double-escaped in the JSON wire
    format.  This function converts them back to real Unicode characters.
    It also restores standard JSON escape sequences (\\n, \\t, etc.).
    """
    if '\\' not in s:
        return s
    # The agentcore transport sometimes inserts newlines in the middle of
    # \\uXXXX escape sequences (line wrapping).  Rejoin them first.
    # Pattern: \u followed by hex digits split by \n, e.g. \\u662\nf → \\u662f
    s = _re.sub(r'\\u([0-9a-fA-F]{0,3})\n([0-9a-fA-F])', r'\\u\1\2', s)
    # Decode \\uXXXX sequences
    def _replace(m):
        cp = int(m.group(1), 16)
        # Skip lone surrogates (0xD800-0xDFFF) — they can't be encoded to UTF-8
        if 0xD800 <= cp <= 0xDFFF:
            return ''
        return chr(cp)
    try:
        s = _UNICODE_ESCAPE_RE.sub(_replace, s)
    except (ValueError, OverflowError):
        pass
    # Decode standard JSON escape sequences.
    # Process \\\\ first (literal double-backslash → single backslash) using a
    # placeholder so that \\n is not confused with \<newline>.
    _PH = '\x00BSLASH\x00'
    s = s.replace('\\\\', _PH)
    s = s.replace('\\n', '\n').replace('\\t', '\t').replace('\\r', '\r')
    s = s.replace(_PH, '\\')
    return s


def _unescape_unicode_recursive(obj):
    """Apply unicode unescape to all string values and dict keys."""
    if isinstance(obj, str):
        return _unescape_unicode_str(obj)
    if isinstance(obj, dict):
        return {
            _unescape_unicode_str(k): _unescape_unicode_recursive(v)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_unescape_unicode_recursive(item) for item in obj]
    return obj

# ── i18n ────────────────────────────────────────────────────────────────

STRINGS = {
    "zh": {
        "banner": "🕷️  爬虫智能体 — 用自然语言创建爬虫",
        "skills_header": "可用技能:",
        "prompt": "请描述你想爬取的内容 (输入 q 退出): ",
        "thinking": "⏳ 正在分析请求并执行爬虫...",
        "skill_used": "🎯 使用技能",
        "auto": "(自动选择)",
        "manual": "(手动指定)",
        "result_header": "📊 爬取结果:",
        "agent_says": "🤖 Agent 回复:",
        "saved": "💾 结果已保存到",
        "error": "❌ 错误",
        "timeout": "⏰ 请求超时 ({}秒)，请重试或简化请求",
        "bye": "👋 再见!",
        "empty": "⚠️  请输入爬取请求",
        "skill_prompt": "指定技能 (留空自动选择): ",
        "examples": [
            "爬取豆瓣电影TOP250的电影名称、评分、导演等信息",
            "抓取 https://books.toscrape.com 上所有书籍的名称和价格",
            "获取 https://news.ycombinator.com 的最新新闻标题和链接",
            "爬取 https://docs.python.org/3/library/json.html 的文档内容和代码示例",
            "从 https://jsonplaceholder.typicode.com/users 获取所有用户数据",
        ],
    },
    "en": {
        "banner": "🕷️  Crawler Agent — Create crawlers with natural language",
        "skills_header": "Available skills:",
        "prompt": "Describe what you want to crawl (q to quit): ",
        "thinking": "⏳ Analyzing request and running crawler...",
        "skill_used": "🎯 Skill used",
        "auto": "(auto-selected)",
        "manual": "(explicit)",
        "result_header": "📊 Crawl results:",
        "agent_says": "🤖 Agent says:",
        "saved": "💾 Results saved to",
        "error": "❌ Error",
        "timeout": "⏰ Request timed out ({}s), try again or simplify",
        "bye": "👋 Bye!",
        "empty": "⚠️  Please enter a crawl request",
        "skill_prompt": "Specify skill (leave empty for auto): ",
        "examples": [
            "Scrape the top 250 movies from Douban with titles, ratings, and directors",
            "Get all book names and prices from https://books.toscrape.com",
            "Fetch the latest headlines and links from https://news.ycombinator.com",
            "Crawl https://docs.python.org/3/library/json.html for docs and code examples",
            "Fetch all user data from https://jsonplaceholder.typicode.com/users",
        ],
    },
}

# ── Dev-server response extraction ──────────────────────────────────────


def _extract_dev_response(stdout: str) -> str:
    """Extract the JSON payload from the dev server's Python-repr wrapper.

    The dev server outputs:
        ✓ Response from dev server:
        {
            'response': '<json_string>'
        }
    The inner JSON string may contain raw newlines (line-wrapped by the
    transport) and escaped single-quotes (\\'). We locate the outer Python
    dict with ast.literal_eval; if that fails we fall back to a regex that
    strips line-wrapping newlines before parsing.
    """
    import ast as _ast

    # Strategy 1: find the outer Python dict and eval it
    brace_start = stdout.find('{')
    brace_end = stdout.rfind('}')
    if brace_start != -1 and brace_end > brace_start:
        candidate = stdout[brace_start:brace_end + 1]
        try:
            parsed = _ast.literal_eval(candidate)
            if isinstance(parsed, dict) and 'response' in parsed:
                return parsed['response']
        except (ValueError, SyntaxError):
            pass

    # Strategy 2: locate 'response': ' ... ' boundaries manually,
    # collapsing line-wrap newlines that appear inside the JSON string.
    marker = "'response': '"
    start = stdout.find(marker)
    if start == -1:
        raise ValueError("No 'response' key found in dev server output")
    start += len(marker)

    # Walk forward to find the closing unescaped single-quote.
    i = start
    s = stdout
    n = len(s)
    while i < n:
        c = s[i]
        if c == '\\':
            i += 2  # skip escaped character
            continue
        if c == '\n':
            i += 1  # skip line-wrap newline (not a real escape)
            continue
        if c == "'":
            break
        i += 1

    raw = s[start:i]
    # Remove line-wrap newlines that aren't actual \\n escape sequences
    raw = _re.sub(r'(?<!\\)\n', '', raw)
    return raw


# ── Agent Invocation ────────────────────────────────────────────────────


def find_agentcore_bin():
    """Locate the agentcore CLI binary."""
    base = os.path.dirname(__file__)
    for venv in (".venv2", ".venv"):
        candidate = os.path.join(base, venv, "bin", "agentcore")
        if os.path.isfile(candidate):
            return candidate
    return "agentcore"


def find_dev_port():
    """Find the port where the agentcore dev server is actually listening."""
    import socket
    for port in (8080, 8081, 8082, 8083, 8084):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return port
        except OSError:
            continue
    return 8080  # fallback


def _invoke_agent_http(payload: dict, port: int, session_id: str, timeout: int) -> dict:
    """Call dev server directly via HTTP — avoids agentcore CLI parsing issues."""
    import urllib.request
    import urllib.error
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/invocations",
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Amzn-Bedrock-AgentCore-Runtime-SessionId": session_id,
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _invoke_agent_cloud(payload: dict, session_id: str, timeout: int) -> dict:
    """Call the deployed AgentCore Runtime Endpoint via boto3."""
    import boto3
    from botocore.config import Config

    region = os.environ.get("AWS_REGION", "us-east-1")
    runtime_id = os.environ.get("AGENTCORE_RUNTIME_ID")
    account_id = os.environ.get("AWS_ACCOUNT_ID")
    endpoint_name = os.environ.get("AGENTCORE_ENDPOINT_NAME", "crawlerEndpoint")

    if not runtime_id:
        raise RuntimeError("AGENTCORE_RUNTIME_ID environment variable is not set")
    if not account_id:
        raise RuntimeError("AWS_ACCOUNT_ID environment variable is not set")

    runtime_arn = (
        os.environ.get("AGENTCORE_RUNTIME_ARN")
        or f"arn:aws:bedrock-agentcore:{region}:{account_id}:runtime/{runtime_id}"
    )

    client = boto3.client(
        "bedrock-agentcore",
        region_name=region,
        config=Config(read_timeout=timeout, connect_timeout=10),
    )
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    resp = client.invoke_agent_runtime(
        agentRuntimeArn=runtime_arn,
        qualifier=endpoint_name,
        runtimeSessionId=session_id,
        contentType="application/json",
        accept="application/json",
        payload=body,
    )
    raw = resp["response"]
    if hasattr(raw, "read"):
        raw = raw.read()
    return json.loads(raw.decode("utf-8"))


def invoke_agent(prompt, skill=None, dev=False, cloud=False, timeout=180, use_browser=False):
    """Send a crawl request to the AgentCore agent and return parsed response."""
    payload = {"prompt": prompt}
    if skill:
        payload["skill"] = skill
        payload["args"] = prompt
    if use_browser:
        payload["use_browser"] = True

    session_id = f"cli-{uuid.uuid4().hex}"

    # Cloud mode: call the deployed AgentCore Runtime Endpoint via boto3.
    if cloud:
        parsed = _invoke_agent_cloud(payload, session_id, timeout)
        return _unescape_unicode_recursive(parsed)

    # Dev mode: call the local server directly via HTTP.
    if dev:
        port = find_dev_port()
        parsed = _invoke_agent_http(payload, port, session_id, timeout)
        return _unescape_unicode_recursive(parsed)

    agentcore = find_agentcore_bin()
    cmd = [agentcore, "invoke"]
    cmd.extend(["--session-id", session_id])
    cmd.append(json.dumps(payload, ensure_ascii=False))

    # Force UTF-8 encoding for subprocess
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["LC_ALL"] = "en_US.UTF-8"
    env["LANG"] = "en_US.UTF-8"

    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout,
        env=env, encoding="utf-8", errors="replace",
    )

    if result.returncode != 0:
        stderr = result.stderr.strip()
        stdout = result.stdout.strip()
        raise RuntimeError(stderr or stdout or f"Exit code {result.returncode}")

    stdout = result.stdout.strip()

    # Parse response — multiple strategies for deployed agent output formats
    for parser in [
        # 1. Direct JSON (clean output)
        lambda s: json.loads(s),
        # 2. Runtime format: "Response:\n<json>"
        lambda s: json.loads(
            s[s.find("Response:") + 9:].strip().replace('\n', '')
        ) if "Response:" in s else (_ for _ in ()).throw(ValueError()),
        # 3. Brute-force: find outermost { ... }
        lambda s: json.loads(
            s[s.find("{"):s.rfind("}") + 1].replace('\n', '')
        ) if "{" in s else (_ for _ in ()).throw(ValueError()),
    ]:
        try:
            parsed = parser(stdout)
            return _unescape_unicode_recursive(parsed)
        except (json.JSONDecodeError, ValueError, TypeError):
            continue

    raise RuntimeError(f"Cannot parse response:\n{stdout[:300]}")


# ── Display Helpers ─────────────────────────────────────────────────────

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BLUE = "\033[94m"


def print_json_pretty(data, indent=0):
    """Print JSON data with colors, handling nested structures."""
    prefix = "  " * indent
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, (dict, list)):
                print(f"{prefix}{CYAN}{k}{RESET}:")
                print_json_pretty(v, indent + 1)
            else:
                val_str = str(v)
                if len(val_str) > 120:
                    val_str = val_str[:120] + "..."
                # Sanitize surrogates before printing
                val_str = val_str.encode("utf-8", errors="replace").decode("utf-8")
                print(f"{prefix}{CYAN}{k}{RESET}: {val_str}")
    elif isinstance(data, list):
        for i, item in enumerate(data):
            if isinstance(item, dict):
                print(f"{prefix}{DIM}[{i}]{RESET}")
                print_json_pretty(item, indent + 1)
            else:
                item_str = str(item).encode("utf-8", errors="replace").decode("utf-8")
                print(f"{prefix}- {item_str}")
    else:
        data_str = str(data).encode("utf-8", errors="replace").decode("utf-8")
        print(f"{prefix}{data_str}")


def extract_agent_text(result_msg):
    """Extract readable text from the agent's result message."""
    if isinstance(result_msg, dict):
        content = result_msg.get("content", [])
        texts = []
        for block in content:
            if isinstance(block, dict) and "text" in block:
                texts.append(block["text"])
        return "\n".join(texts)
    return str(result_msg) if result_msg else ""


# ── Interactive Loop ────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Crawler Agent interactive client")
    parser.add_argument("--dev", action="store_true", help="Use local dev server")
    parser.add_argument("--cloud", action="store_true", help="Use deployed cloud AgentCore Runtime")
    parser.add_argument("--browser", action="store_true",
                        help="Enable AgentCore Browser tool (real Chromium, JS rendering, anti-bot)")
    parser.add_argument("--lang", choices=["zh", "en"], default="zh",
                        help="UI language (default: zh)")
    parser.add_argument("--timeout", type=int, default=180,
                        help="Request timeout in seconds (default: 180)")
    parser.add_argument("--output", type=str, default=None,
                        help="Save crawl results to JSON file")
    parser.add_argument("--skill", type=str, default=None,
                        help="Force a specific skill (skip auto-selection)")
    parser.add_argument("request", nargs="*",
                        help="Crawl request (if omitted, enters interactive mode)")
    args = parser.parse_args()

    t = STRINGS[args.lang]

    # ── Banner ──────────────────────────────────────────────────────
    print(f"\n{BOLD}{t['banner']}{RESET}")
    print(f"{'─' * 60}")
    print(f"{DIM}{t['skills_header']}{RESET}")
    skills = [
        ("default-crawl",    "通用网页爬虫" if args.lang == "zh" else "General web crawler"),
        ("ecommerce-crawl",  "电商产品爬虫" if args.lang == "zh" else "E-commerce products"),
        ("news-crawl",       "新闻文章爬虫" if args.lang == "zh" else "News & articles"),
        ("api-crawl",        "API/JSON 爬虫" if args.lang == "zh" else "REST API / JSON"),
        ("docs-crawl",       "文档/Wiki 爬虫" if args.lang == "zh" else "Documentation / Wiki"),
        ("social-crawl",     "社交/论坛爬虫" if args.lang == "zh" else "Social media / Forums"),
    ]
    for name, desc in skills:
        print(f"  {GREEN}•{RESET} {name:<20} {DIM}{desc}{RESET}")

    print(f"\n{DIM}{'示例' if args.lang == 'zh' else 'Examples'}:{RESET}")
    for ex in t["examples"][:3]:
        print(f"  {DIM}→ {ex}{RESET}")
    print()

    # ── Single-shot mode (args on command line) ─────────────────────
    if args.request:
        prompt = " ".join(args.request)
        run_one(prompt, args.skill, args.dev, args.cloud, args.timeout, args.output, t,
                use_browser=args.browser)
        return

    # ── Interactive loop ────────────────────────────────────────────
    while True:
        try:
            prompt = input(f"{BOLD}{t['prompt']}{RESET}").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n{t['bye']}")
            break

        if prompt.lower() in ("q", "quit", "exit", "退出"):
            print(t["bye"])
            break

        if not prompt:
            print(t["empty"])
            continue

        run_one(prompt, args.skill, args.dev, args.cloud, args.timeout, args.output, t,
                use_browser=args.browser)
        print()


def run_one(prompt, skill, dev, cloud, timeout, output_file, t, use_browser=False):
    """Execute a single crawl request and display results."""
    print(f"\n{YELLOW}{t['thinking']}{RESET}")
    if use_browser:
        print(f"{DIM}🌐 Browser mode enabled (real Chromium + JS rendering){RESET}")

    try:
        response = invoke_agent(prompt, skill=skill, dev=dev, cloud=cloud, timeout=timeout,
                                use_browser=use_browser)
    except subprocess.TimeoutExpired:
        print(f"{RED}{t['timeout'].format(timeout)}{RESET}")
        return
    except Exception as e:
        print(f"{RED}{t['error']}: {e}{RESET}")
        return

    # ── Skill info ──────────────────────────────────────────────────
    skill_used = response.get("skill_used", "unknown")
    auto = response.get("auto_selected", True)
    mode = t["auto"] if auto else t["manual"]
    browser_used = response.get("browser_used", False)
    browser_tag = f" {DIM}[browser]{RESET}" if browser_used else ""
    print(f"{t['skill_used']}: {GREEN}{skill_used}{RESET} {DIM}{mode}{RESET}{browser_tag}")

    # ── Agent text response ─────────────────────────────────────────
    agent_text = extract_agent_text(response.get("result"))
    if agent_text:
        # Remove surrogate characters that can't be encoded to UTF-8
        agent_text = agent_text.encode("utf-8", errors="replace").decode("utf-8")
        # Truncate very long agent responses for readability
        lines = agent_text.split("\n")
        if len(lines) > 20:
            display = "\n".join(lines[:20])
            print(f"\n{BLUE}{t['agent_says']}{RESET}\n{display}")
            print(f"{DIM}  ... ({len(lines) - 20} more lines){RESET}")
        else:
            print(f"\n{BLUE}{t['agent_says']}{RESET}\n{agent_text}")

    # ── Structured crawl output ─────────────────────────────────────
    crawler_output = response.get("crawler_output")
    if not crawler_output and agent_text:
        # No structured output — auto-save the full response as fallback
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        save_path = output_file or os.path.join(OUTPUT_DIR, f"crawl_{ts}.json")
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(response, f, ensure_ascii=False, indent=2)
        print(f"\n{GREEN}{t['saved']} {save_path}{RESET}")

    if crawler_output:
        print(f"\n{BOLD}{t['result_header']}{RESET}")
        print(f"{'─' * 60}")

        if isinstance(crawler_output, str):
            try:
                crawler_output = json.loads(crawler_output)
            except (json.JSONDecodeError, TypeError):
                pass

        if isinstance(crawler_output, (dict, list)):
            print_json_pretty(crawler_output)

            # Auto-save to output/ directory with timestamp
            os.makedirs(OUTPUT_DIR, exist_ok=True)
            ts = time.strftime("%Y%m%d_%H%M%S")
            save_path = output_file or os.path.join(
                OUTPUT_DIR, f"crawl_{ts}.json"
            )
            with open(save_path, "w", encoding="utf-8") as f:
                json.dump(crawler_output, f, ensure_ascii=False, indent=2)
            print(f"\n{GREEN}{t['saved']} {save_path}{RESET}")
        else:
            print(crawler_output)


if __name__ == "__main__":
    main()
