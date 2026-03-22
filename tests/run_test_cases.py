#!/usr/bin/env python3
"""End-to-end test cases for the Crawler Agent on AgentCore.

Invokes the deployed agent via `agentcore invoke` by default.
Each test sends a real payload and validates the response.

Usage:
    # Run all tests against deployed AgentCore agent (default):
    python tests/run_test_cases.py

    # Run against local dev server instead:
    python tests/run_test_cases.py --dev

    # Run a single test case:
    python tests/run_test_cases.py --case ecommerce-books

    # List available test cases:
    python tests/run_test_cases.py --list

    # Custom timeout (default 180s — remote agents need more time):
    python tests/run_test_cases.py --timeout 240

    # Use a specific session ID:
    python tests/run_test_cases.py --session-id my-test-session

    # Target a specific agent name (multi-agent config):
    python tests/run_test_cases.py --agent create_agent
"""

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass

# ── Test Case Definition ────────────────────────────────────────────────


@dataclass
class TestCase:
    name: str
    description: str
    payload: dict
    expected_skill: str
    required_output_keys: list[str]
    validate: callable = None  # optional extra validation


# ── Test Cases ──────────────────────────────────────────────────────────

TEST_CASES: list[TestCase] = [
    # ── default-crawl ───────────────────────────────────────────────
    TestCase(
        name="default-simple",
        description="Basic crawl of a simple page",
        payload={
            "prompt": "Crawl https://example.com",
            "skill": "default-crawl",
            "args": "https://example.com",
        },
        expected_skill="default-crawl",
        required_output_keys=["url", "title"],
    ),
    TestCase(
        name="default-auto-select",
        description="Auto-select skill for a generic crawl request",
        payload={
            "prompt": "Crawl https://example.com and extract the page title, links, and text content",
        },
        expected_skill="default-crawl",
        required_output_keys=["url"],
    ),

    # ── ecommerce-crawl ────────────────────────────────────────────
    TestCase(
        name="ecommerce-books",
        description="Scrape product listings from books.toscrape.com",
        payload={
            "prompt": "Scrape all book listings with prices",
            "skill": "ecommerce-crawl",
            "args": "https://books.toscrape.com 2",
        },
        expected_skill="ecommerce-crawl",
        required_output_keys=["products"],
        validate=lambda out: (
            isinstance(out.get("products"), list)
            and len(out["products"]) > 0
            and "name" in out["products"][0]
            and "price" in out["products"][0]
        ),
    ),
    TestCase(
        name="ecommerce-auto-select",
        description="Auto-select ecommerce skill from product-related prompt",
        payload={
            "prompt": "Get all product names and prices from https://books.toscrape.com",
        },
        expected_skill="ecommerce-crawl",
        required_output_keys=["products"],
    ),

    # ── news-crawl ─────────────────────────────────────────────────
    TestCase(
        name="news-quotes",
        description="Crawl article-like content from quotes.toscrape.com",
        payload={
            "prompt": "Extract articles and content",
            "skill": "news-crawl",
            "args": "https://quotes.toscrape.com 3",
        },
        expected_skill="news-crawl",
        required_output_keys=["articles"],
    ),
    TestCase(
        name="news-auto-select",
        description="Auto-select news skill from headline-related prompt",
        payload={
            "prompt": "Scrape the latest news headlines, authors, and publish dates from https://quotes.toscrape.com as a news article listing",
        },
        expected_skill="news-crawl",
        required_output_keys=["articles"],
    ),

    # ── api-crawl ──────────────────────────────────────────────────
    TestCase(
        name="api-jsonplaceholder",
        description="Fetch data from a public JSON API",
        payload={
            "prompt": "Fetch user data from the API",
            "skill": "api-crawl",
            "args": "https://jsonplaceholder.typicode.com/users 1",
        },
        expected_skill="api-crawl",
        required_output_keys=["endpoints_discovered", "total_records_fetched"],
        validate=lambda out: out.get("total_records_fetched", 0) > 0,
    ),
    TestCase(
        name="api-posts",
        description="Fetch posts from a paginated JSON API",
        payload={
            "prompt": "Crawl the posts API endpoint",
            "skill": "api-crawl",
            "args": "https://jsonplaceholder.typicode.com/posts 2",
        },
        expected_skill="api-crawl",
        required_output_keys=["total_records_fetched"],
    ),
    TestCase(
        name="api-auto-select",
        description="Auto-select API skill from REST endpoint prompt",
        payload={
            "prompt": "Fetch all records from the REST API at https://jsonplaceholder.typicode.com/todos",
        },
        expected_skill="api-crawl",
        required_output_keys=["total_records_fetched"],
    ),

    # ── docs-crawl ─────────────────────────────────────────────────
    TestCase(
        name="docs-python",
        description="Crawl Python documentation page",
        payload={
            "prompt": "Extract documentation content with code examples",
            "skill": "docs-crawl",
            "args": "https://docs.python.org/3/library/json.html 1",
        },
        expected_skill="docs-crawl",
        required_output_keys=["pages"],
        validate=lambda out: (
            isinstance(out.get("pages"), list)
            and len(out["pages"]) > 0
        ),
    ),
    TestCase(
        name="docs-auto-select",
        description="Auto-select docs skill from documentation-related prompt",
        payload={
            "prompt": "Scrape the documentation and code examples from https://docs.python.org/3/library/json.html",
        },
        expected_skill="docs-crawl",
        required_output_keys=["pages"],
    ),

    # ── social-crawl ───────────────────────────────────────────────
    TestCase(
        name="social-quotes",
        description="Crawl social/forum-like content from quotes.toscrape.com",
        payload={
            "prompt": "Extract posts and authors from the forum",
            "skill": "social-crawl",
            "args": "https://quotes.toscrape.com 10",
        },
        expected_skill="social-crawl",
        required_output_keys=["posts"],
    ),
    TestCase(
        name="social-auto-select",
        description="Auto-select social skill from forum-related prompt",
        payload={
            "prompt": "Get the latest forum posts and discussion threads from https://quotes.toscrape.com",
        },
        expected_skill="social-crawl",
        required_output_keys=["posts"],
    ),

    # ── error handling ─────────────────────────────────────────────
    TestCase(
        name="error-unreachable",
        description="Graceful error for unreachable URL",
        payload={
            "prompt": "Crawl this broken URL",
            "skill": "default-crawl",
            "args": "https://this-domain-does-not-exist-xyz123.com",
        },
        expected_skill="default-crawl",
        required_output_keys=["error"],
    ),
]


# ── Terminal Colors ─────────────────────────────────────────────────────

PASS = "\033[92m✓ PASS\033[0m"
FAIL = "\033[91m✗ FAIL\033[0m"
WARN = "\033[93m⚠ WARN\033[0m"


# ── Agent Invocation ────────────────────────────────────────────────────

def invoke_agent(
    payload: dict,
    dev: bool,
    timeout: int,
    session_id: str | None = None,
    agent: str | None = None,
) -> dict:
    """Call `agentcore invoke` and return the parsed JSON response.

    By default targets the deployed AgentCore runtime.
    Pass dev=True to hit the local dev server instead.
    """
    # Prefer venv-installed agentcore, fall back to PATH
    agentcore_bin = os.path.join(
        os.path.dirname(__file__), "..", ".venv", "bin", "agentcore"
    )
    if not os.path.isfile(agentcore_bin):
        agentcore_bin = "agentcore"

    cmd = [agentcore_bin, "invoke"]

    if dev:
        cmd.append("--dev")

    if session_id:
        cmd.extend(["--session-id", session_id])

    if agent:
        cmd.extend(["--agent", agent])

    cmd.append(json.dumps(payload))

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"agentcore invoke failed (exit {result.returncode}):\n"
            f"stdout: {result.stdout[:500]}\n"
            f"stderr: {result.stderr[:500]}"
        )

    stdout = result.stdout.strip()

    # Try parsing the whole thing as JSON first
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        pass

    # AgentCore CLI prints a rich banner then "Response:\n{json}"
    # Look for the JSON after "Response:" marker
    resp_marker = stdout.find("Response:")
    if resp_marker != -1:
        json_part = stdout[resp_marker + len("Response:"):].strip()
        try:
            return json.loads(json_part, strict=False)
        except json.JSONDecodeError:
            pass

    # Fallback: find outermost { ... }
    start = stdout.find("{")
    end = stdout.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(stdout[start : end + 1], strict=False)
        except json.JSONDecodeError:
            pass

    raise RuntimeError(f"Could not parse JSON from agentcore output:\n{stdout[:500]}")


# ── Single Test Runner ──────────────────────────────────────────────────

def run_test_case(
    tc: TestCase,
    dev: bool,
    timeout: int,
    session_id: str | None = None,
    agent: str | None = None,
) -> tuple[str, str]:
    """Run one test case. Returns (status, message)."""
    try:
        response = invoke_agent(
            tc.payload,
            dev=dev,
            timeout=timeout,
            session_id=session_id,
            agent=agent,
        )
    except subprocess.TimeoutExpired:
        return "FAIL", f"Timed out after {timeout}s"
    except Exception as e:
        return "FAIL", f"Invocation error: {e}"

    messages = []

    # ── Validate skill_used ─────────────────────────────────────────
    skill_used = response.get("skill_used", "")
    if tc.payload.get("skill"):
        # Explicit skill — must match
        if skill_used != tc.expected_skill:
            return "FAIL", f"Expected skill '{tc.expected_skill}', got '{skill_used}'"
    else:
        # Auto-selected — warn if different
        if skill_used != tc.expected_skill:
            messages.append(
                f"Auto-selected '{skill_used}' instead of expected '{tc.expected_skill}'"
            )

    # ── Validate crawler_output ─────────────────────────────────────
    crawler_output = response.get("crawler_output")
    if crawler_output is None:
        return "FAIL", "No crawler_output in response"

    if isinstance(crawler_output, str):
        try:
            crawler_output = json.loads(crawler_output)
        except (json.JSONDecodeError, TypeError):
            return "FAIL", f"crawler_output not valid JSON: {crawler_output[:200]}"

    if not isinstance(crawler_output, (dict, list)):
        return "FAIL", f"crawler_output is {type(crawler_output).__name__}, expected dict or list"

    # If output is a list, wrap it so key checks work against the first item
    output_to_check = crawler_output
    if isinstance(crawler_output, list):
        if len(crawler_output) == 0:
            return "FAIL", "crawler_output is an empty list"
        output_to_check = crawler_output[0] if isinstance(crawler_output[0], dict) else {"items": crawler_output}

    # ── Check required keys ─────────────────────────────────────────
    missing = [k for k in tc.required_output_keys if k not in output_to_check]
    if missing:
        if "error" in output_to_check and tc.required_output_keys != ["error"]:
            return "FAIL", f"Crawl returned error: {output_to_check['error']}"
        return "FAIL", f"Missing keys: {missing}. Got: {list(output_to_check.keys())}"

    # ── Custom validation ───────────────────────────────────────────
    if tc.validate:
        try:
            if not tc.validate(output_to_check):
                return "FAIL", (
                    f"Custom validation failed. Output: "
                    f"{json.dumps(output_to_check)[:300]}"
                )
        except Exception as e:
            return "FAIL", f"Custom validation raised: {e}"

    if messages:
        return "WARN", "; ".join(messages)
    return "PASS", "OK"


# ── Main ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Run end-to-end test cases against the Crawler Agent on AgentCore.",
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Target local dev server instead of deployed AgentCore agent",
    )
    parser.add_argument(
        "--case",
        type=str,
        default=None,
        help="Run a single test case by name",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all available test cases and exit",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=180,
        help="Timeout per test case in seconds (default: 180)",
    )
    parser.add_argument(
        "--session-id",
        type=str,
        default=None,
        help="AgentCore session ID (auto-generated if omitted)",
    )
    parser.add_argument(
        "--agent",
        type=str,
        default=None,
        help="Agent name for multi-agent configs (e.g. create_agent)",
    )
    args = parser.parse_args()

    # ── List mode ───────────────────────────────────────────────────
    if args.list:
        print(f"\n{'NAME':<25} {'SKILL':<20} DESCRIPTION")
        print("-" * 80)
        for tc in TEST_CASES:
            print(f"{tc.name:<25} {tc.expected_skill:<20} {tc.description}")
        print(f"\nTotal: {len(TEST_CASES)} test cases")
        sys.exit(0)

    # ── Filter cases ────────────────────────────────────────────────
    cases = TEST_CASES
    if args.case:
        cases = [tc for tc in TEST_CASES if tc.name == args.case]
        if not cases:
            print(f"Unknown test case: {args.case}")
            print(f"Available: {', '.join(tc.name for tc in TEST_CASES)}")
            sys.exit(1)

    # ── Session ID ──────────────────────────────────────────────────
    session_id = args.session_id or f"test-{uuid.uuid4().hex}"

    # ── Banner ──────────────────────────────────────────────────────
    target = "local dev server" if args.dev else "deployed AgentCore agent"
    print(f"\n{'=' * 80}")
    print(f"  Crawler Agent — End-to-End Test Suite")
    print(f"  Target:     {target}")
    print(f"  Session:    {session_id}")
    print(f"  Timeout:    {args.timeout}s per case")
    print(f"  Test cases: {len(cases)}")
    if args.agent:
        print(f"  Agent:      {args.agent}")
    print(f"{'=' * 80}\n")

    print(f"{'#':<4} {'NAME':<25} {'STATUS':<12} {'TIME':>7}  MESSAGE")
    print("-" * 80)

    # ── Run ─────────────────────────────────────────────────────────
    results = {"PASS": 0, "FAIL": 0, "WARN": 0}
    total_time = 0.0

    for i, tc in enumerate(cases, 1):
        start = time.time()
        status, message = run_test_case(
            tc,
            dev=args.dev,
            timeout=args.timeout,
            session_id=f"{session_id}-{i:02d}",
            agent=args.agent,
        )
        elapsed = time.time() - start
        total_time += elapsed
        results[status] = results.get(status, 0) + 1

        icon = {"PASS": PASS, "FAIL": FAIL, "WARN": WARN}.get(status, status)
        print(f"{i:<4} {tc.name:<25} {icon}  {elapsed:>5.1f}s  {message}")

    # ── Summary ─────────────────────────────────────────────────────
    total = sum(results.values())
    print(f"\n{'=' * 80}")
    print(
        f"  Results: {results['PASS']}/{total} passed, "
        f"{results['FAIL']} failed, {results['WARN']} warnings"
    )
    print(f"  Total time: {total_time:.1f}s")
    print(f"{'=' * 80}\n")

    sys.exit(1 if results["FAIL"] > 0 else 0)


if __name__ == "__main__":
    main()
