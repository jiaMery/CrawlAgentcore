"""Tests simulating realistic customer inputs across all crawler skills.

Covers: skill discovery, argument substitution, system prompt assembly,
payload routing, output extraction, and edge cases — all without
requiring network or LLM access.
"""

import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.skills import load_skill, list_skills, load_supporting_file

# Copied from main.py so tests stay self-contained (no strands/bedrock imports)
SYSTEM_PROMPT_TEMPLATE = """You are a web-crawler code generator and executor.

## Workflow
1. Read the crawl-style instructions below carefully.
2. Based on the user's target URL (and optional parameters), generate a
   complete, self-contained Python script that performs the crawl.
3. Execute the script using the code_interpreter tool.
4. Return the crawl results to the user.

## Crawl-Style Instructions
{crawl_style}

## Rules
- Always generate the full Python script — do NOT ask the user to fill in blanks.
- The script MUST print its final JSON output wrapped in delimiters exactly like this:
  <<<CRAWLER_JSON>>>
  {{"url": "...", ...}}
  <<<END_CRAWLER_JSON>>>
  Use `print("<<<CRAWLER_JSON>>>")`, then `print(json.dumps(result, indent=2))`, then `print("<<<END_CRAWLER_JSON>>>")`.
- If the crawl fails, return a JSON object with an "error" key explaining what happened,
  still wrapped in the same delimiters.
- Do NOT install packages with pip — only use libraries available in the runtime
  (requests, beautifulsoup4, json, re, urllib, etc.).
"""

_CRAWLER_JSON_RE = re.compile(
    r"<<<CRAWLER_JSON>>>\s*(.*?)\s*<<<END_CRAWLER_JSON>>>", re.DOTALL
)

ALL_SKILL_NAMES = [
    "default-crawl",
    "ecommerce-crawl",
    "news-crawl",
    "api-crawl",
    "docs-crawl",
    "social-crawl",
]


# ── Skill Discovery ─────────────────────────────────────────────────────

class TestSkillDiscovery:
    """All six skills are discoverable and have valid metadata."""

    def test_all_skills_listed(self):
        names = [s["name"] for s in list_skills()]
        for expected in ALL_SKILL_NAMES:
            assert expected in names, f"{expected} missing from list_skills()"

    def test_every_skill_has_description(self):
        for s in list_skills():
            assert len(s["description"]) > 20, (
                f"{s['name']} description too short: {s['description']!r}"
            )

    def test_every_skill_has_argument_hint(self):
        for s in list_skills():
            assert "<url>" in s["argument_hint"], (
                f"{s['name']} argument_hint missing <url>: {s['argument_hint']!r}"
            )

    def test_skill_count(self):
        assert len(list_skills()) == 6


# ── Default Crawl — customer inputs ─────────────────────────────────────

class TestDefaultCrawlCustomerInputs:
    """Typical customer prompts that should route to default-crawl."""

    def test_simple_url(self):
        skill = load_skill("default-crawl", "https://example.com")
        assert "https://example.com" in skill.content
        assert "$ARGUMENTS" not in skill.content

    def test_url_with_path(self):
        skill = load_skill("default-crawl", "https://example.com/about/team")
        assert "https://example.com/about/team" in skill.content

    def test_system_prompt_assembly(self):
        skill = load_skill("default-crawl", "https://example.com")
        prompt = SYSTEM_PROMPT_TEMPLATE.format(crawl_style=skill.content)
        assert "crawl(url" in prompt
        assert "requests" in prompt
        assert "_safe_output" in prompt

    def test_sample_output_is_valid_json(self):
        raw = load_supporting_file("default-crawl", "examples/sample-output.json")
        data = json.loads(raw)
        assert "url" in data
        assert "title" in data
        assert "links" in data


# ── E-Commerce Crawl — customer inputs ──────────────────────────────────

class TestEcommerceCrawlCustomerInputs:
    """Customers scraping product catalogs."""

    def test_product_page_with_pagination(self):
        skill = load_skill("ecommerce-crawl", "https://shop.example.com/shoes 10")
        assert "https://shop.example.com/shoes 10" in skill.content
        # $1 → "10"
        assert "10" in skill.content

    def test_default_pagination(self):
        skill = load_skill("ecommerce-crawl", "https://store.example.com")
        # $1 with no second arg → empty string, default in code is 3
        assert "crawl_products" in skill.content

    def test_product_keywords_in_prompt(self):
        skill = load_skill("ecommerce-crawl", "https://amazon.example.com/dp/B09XYZ")
        assert "product" in skill.content.lower()
        assert "price" in skill.content.lower()
        assert "availability" in skill.content.lower()

    def test_reference_doc_available(self):
        ref = load_supporting_file("ecommerce-crawl", "reference.md")
        assert "price" in ref.lower()
        assert "pagination" in ref.lower()

    def test_sample_output_structure(self):
        raw = load_supporting_file("ecommerce-crawl", "examples/sample-output.json")
        data = json.loads(raw)
        assert "products" in data
        assert isinstance(data["products"], list)
        product = data["products"][0]
        for key in ("name", "price", "currency", "availability"):
            assert key in product, f"Missing key {key} in sample product"


# ── News Crawl — customer inputs ────────────────────────────────────────

class TestNewsCrawlCustomerInputs:
    """Customers scraping news sites and blogs."""

    def test_news_homepage(self):
        skill = load_skill("news-crawl", "https://news.ycombinator.com")
        assert "https://news.ycombinator.com" in skill.content
        assert "articles" in skill.content.lower()

    def test_blog_with_article_limit(self):
        skill = load_skill("news-crawl", "https://blog.example.com 20")
        assert "20" in skill.content

    def test_date_parsing_instructions(self):
        skill = load_skill("news-crawl", "https://reuters.example.com")
        assert "iso 8601" in skill.content.lower() or "ISO 8601" in skill.content

    def test_author_extraction_mentioned(self):
        skill = load_skill("news-crawl", "https://medium.example.com/@user")
        assert "author" in skill.content.lower()

    def test_reference_doc_patterns(self):
        ref = load_supporting_file("news-crawl", "reference.md")
        assert "article" in ref.lower()
        assert "byline" in ref.lower() or "author" in ref.lower()

    def test_sample_output_structure(self):
        raw = load_supporting_file("news-crawl", "examples/sample-output.json")
        data = json.loads(raw)
        assert "articles" in data
        article = data["articles"][0]
        for key in ("title", "author", "publish_date", "body_text", "url"):
            assert key in article, f"Missing key {key} in sample article"


# ── API Crawl — customer inputs ─────────────────────────────────────────

class TestApiCrawlCustomerInputs:
    """Customers fetching data from REST/JSON endpoints."""

    def test_rest_api_endpoint(self):
        skill = load_skill("api-crawl", "https://api.github.com/repos/user/repo/issues")
        assert "https://api.github.com/repos/user/repo/issues" in skill.content

    def test_pagination_limit(self):
        skill = load_skill("api-crawl", "https://api.example.com/v1/users 15")
        assert "15" in skill.content

    def test_json_accept_header(self):
        skill = load_skill("api-crawl", "https://api.example.com/data")
        assert "application/json" in skill.content

    def test_handles_non_json_gracefully(self):
        """Skill instructions mention handling non-JSON responses."""
        skill = load_skill("api-crawl", "https://api.example.com/xml-endpoint")
        assert "non-json" in skill.content.lower() or "non-JSON" in skill.content

    def test_sample_output_structure(self):
        raw = load_supporting_file("api-crawl", "examples/sample-output.json")
        data = json.loads(raw)
        assert "endpoints_discovered" in data
        assert "total_records_fetched" in data


# ── Docs Crawl — customer inputs ────────────────────────────────────────

class TestDocsCrawlCustomerInputs:
    """Customers scraping documentation and wiki sites."""

    def test_readthedocs_url(self):
        skill = load_skill("docs-crawl", "https://docs.python.org/3/library/json.html")
        assert "https://docs.python.org/3/library/json.html" in skill.content

    def test_multi_page_limit(self):
        skill = load_skill("docs-crawl", "https://docs.example.com/getting-started 8")
        assert "8" in skill.content

    def test_code_block_extraction(self):
        skill = load_skill("docs-crawl", "https://docs.example.com")
        assert "code block" in skill.content.lower() or "code_blocks" in skill.content.lower()

    def test_heading_hierarchy(self):
        skill = load_skill("docs-crawl", "https://wiki.example.com/page")
        assert "heading" in skill.content.lower()

    def test_reference_doc_patterns(self):
        ref = load_supporting_file("docs-crawl", "reference.md")
        assert "sidebar" in ref.lower() or "navigation" in ref.lower()
        assert "code" in ref.lower()

    def test_sample_output_structure(self):
        raw = load_supporting_file("docs-crawl", "examples/sample-output.json")
        data = json.loads(raw)
        assert "pages" in data
        page = data["pages"][0]
        assert "sections" in page
        section = page["sections"][0]
        for key in ("heading", "level", "text"):
            assert key in section, f"Missing key {key} in sample section"


# ── Social Crawl — customer inputs ──────────────────────────────────────

class TestSocialCrawlCustomerInputs:
    """Customers scraping forums and social feeds."""

    def test_forum_thread(self):
        skill = load_skill("social-crawl", "https://forum.example.com/t/help-with-python/123")
        assert "https://forum.example.com/t/help-with-python/123" in skill.content

    def test_post_limit(self):
        skill = load_skill("social-crawl", "https://reddit.example.com/r/python 50")
        assert "50" in skill.content

    def test_engagement_metrics(self):
        skill = load_skill("social-crawl", "https://community.example.com")
        content_lower = skill.content.lower()
        assert "likes" in content_lower or "upvotes" in content_lower

    def test_timestamp_handling(self):
        skill = load_skill("social-crawl", "https://forum.example.com")
        assert "iso 8601" in skill.content.lower() or "ISO 8601" in skill.content

    def test_reference_doc_patterns(self):
        ref = load_supporting_file("social-crawl", "reference.md")
        assert "post" in ref.lower()
        assert "author" in ref.lower() or "username" in ref.lower()

    def test_sample_output_structure(self):
        raw = load_supporting_file("social-crawl", "examples/sample-output.json")
        data = json.loads(raw)
        assert "posts" in data
        post = data["posts"][0]
        for key in ("author", "content", "timestamp", "url"):
            assert key in post, f"Missing key {key} in sample post"


# ── Payload Routing — simulated invoke payloads ─────────────────────────

class TestPayloadRouting:
    """Simulate the payload parsing logic from main.py's invoke()."""

    @staticmethod
    def _route_payload(payload: dict) -> dict:
        """Replicate invoke() routing without LLM or agent calls."""
        prompt = payload.get("prompt", "")
        explicit_skill = payload.get("skill")
        skill_args = payload.get("args", prompt)
        skill_name = explicit_skill or "default-crawl"
        skill = load_skill(skill_name, arguments=skill_args)
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(crawl_style=skill.content)
        return {
            "skill_used": skill.name,
            "system_prompt": system_prompt,
            "auto_selected": explicit_skill is None,
        }

    def test_explicit_ecommerce_skill(self):
        result = self._route_payload({
            "prompt": "Scrape all sneakers from this store",
            "skill": "ecommerce-crawl",
            "args": "https://shoes.example.com/sneakers 5",
        })
        assert result["skill_used"] == "ecommerce-crawl"
        assert result["auto_selected"] is False
        assert "products" in result["system_prompt"].lower()

    def test_explicit_news_skill(self):
        result = self._route_payload({
            "prompt": "Get the latest headlines",
            "skill": "news-crawl",
            "args": "https://news.example.com 10",
        })
        assert result["skill_used"] == "news-crawl"
        assert "articles" in result["system_prompt"].lower()

    def test_explicit_api_skill(self):
        result = self._route_payload({
            "prompt": "Fetch all users from the API",
            "skill": "api-crawl",
            "args": "https://api.example.com/v1/users 20",
        })
        assert result["skill_used"] == "api-crawl"
        assert "application/json" in result["system_prompt"]

    def test_explicit_docs_skill(self):
        result = self._route_payload({
            "prompt": "Scrape the SDK documentation",
            "skill": "docs-crawl",
            "args": "https://docs.example.com/sdk",
        })
        assert result["skill_used"] == "docs-crawl"
        assert "heading" in result["system_prompt"].lower()

    def test_explicit_social_skill(self):
        result = self._route_payload({
            "prompt": "Get recent posts from the forum",
            "skill": "social-crawl",
            "args": "https://forum.example.com/latest 25",
        })
        assert result["skill_used"] == "social-crawl"
        assert "posts" in result["system_prompt"].lower()

    def test_no_skill_falls_back_to_default(self):
        result = self._route_payload({
            "prompt": "Crawl https://example.com",
        })
        assert result["skill_used"] == "default-crawl"
        assert result["auto_selected"] is True

    def test_empty_payload(self):
        result = self._route_payload({})
        assert result["skill_used"] == "default-crawl"

    def test_unknown_skill_falls_back(self):
        result = self._route_payload({
            "prompt": "Crawl something",
            "skill": "nonexistent-skill",
        })
        assert result["skill_used"] == "default-crawl"


# ── Output Extraction — simulated Code Interpreter results ──────────────

class TestOutputExtraction:
    """Simulate _extract_crawler_output with realistic CI stdout."""

    @staticmethod
    def _make_tool_result_message(stdout: str) -> list[dict]:
        return [
            {"role": "user", "content": [{"text": "Crawl it"}]},
            {
                "role": "user",
                "content": [{
                    "toolResult": {
                        "toolUseId": "t1",
                        "content": [{"text": stdout}],
                    }
                }],
            },
        ]

    @staticmethod
    def _extract(messages: list[dict]):
        for msg in reversed(messages):
            content = msg.get("content")
            if not content:
                continue
            for block in content:
                tr = block.get("toolResult") if isinstance(block, dict) else None
                if not tr:
                    continue
                for item in tr.get("content", []):
                    text = item.get("text", "") if isinstance(item, dict) else ""
                    m = _CRAWLER_JSON_RE.search(text)
                    if m:
                        return json.loads(m.group(1).strip())
        return None

    def test_ecommerce_output(self):
        stdout = (
            'Crawling page 1...\nCrawling page 2...\n'
            '<<<CRAWLER_JSON>>>\n'
            '{"products": [{"name": "Widget", "price": 9.99}], "pages_crawled": 2}\n'
            '<<<END_CRAWLER_JSON>>>\n'
        )
        result = self._extract(self._make_tool_result_message(stdout))
        assert result["products"][0]["name"] == "Widget"
        assert result["pages_crawled"] == 2

    def test_news_output(self):
        stdout = (
            'Fetching articles...\n'
            '<<<CRAWLER_JSON>>>\n'
            '{"articles": [{"title": "Breaking News", "author": "Reporter"}], "articles_crawled": 1}\n'
            '<<<END_CRAWLER_JSON>>>\n'
        )
        result = self._extract(self._make_tool_result_message(stdout))
        assert result["articles"][0]["title"] == "Breaking News"

    def test_api_output(self):
        stdout = (
            '<<<CRAWLER_JSON>>>\n'
            '{"endpoints_discovered": [{"url": "/users", "status_code": 200}], "total_records_fetched": 50}\n'
            '<<<END_CRAWLER_JSON>>>\n'
        )
        result = self._extract(self._make_tool_result_message(stdout))
        assert result["total_records_fetched"] == 50

    def test_docs_output(self):
        stdout = (
            '<<<CRAWLER_JSON>>>\n'
            '{"pages": [{"title": "Getting Started", "sections": [{"heading": "Install", "level": 2}]}]}\n'
            '<<<END_CRAWLER_JSON>>>\n'
        )
        result = self._extract(self._make_tool_result_message(stdout))
        assert result["pages"][0]["sections"][0]["heading"] == "Install"

    def test_social_output(self):
        stdout = (
            '<<<CRAWLER_JSON>>>\n'
            '{"posts": [{"author": "user42", "content": "Hello world", "likes": 10}]}\n'
            '<<<END_CRAWLER_JSON>>>\n'
        )
        result = self._extract(self._make_tool_result_message(stdout))
        assert result["posts"][0]["likes"] == 10

    def test_error_output(self):
        stdout = (
            '<<<CRAWLER_JSON>>>\n'
            '{"error": "Connection timed out after 15s"}\n'
            '<<<END_CRAWLER_JSON>>>\n'
        )
        result = self._extract(self._make_tool_result_message(stdout))
        assert "error" in result

    def test_no_delimiters_returns_none(self):
        stdout = "Some random output without delimiters"
        result = self._extract(self._make_tool_result_message(stdout))
        assert result is None


# ── Edge Cases — unusual but valid customer inputs ──────────────────────

class TestEdgeCases:
    """Unusual but valid customer inputs."""

    def test_url_with_query_params(self):
        skill = load_skill("ecommerce-crawl", "https://shop.example.com/search?q=shoes&page=1 3")
        assert "https://shop.example.com/search?q=shoes&page=1 3" in skill.content

    def test_url_with_fragment(self):
        skill = load_skill("docs-crawl", "https://docs.example.com/api#authentication")
        assert "#authentication" in skill.content

    def test_unicode_in_arguments(self):
        skill = load_skill("news-crawl", "https://news.example.com/日本語ニュース")
        assert "日本語ニュース" in skill.content

    def test_empty_arguments(self):
        skill = load_skill("default-crawl", "")
        assert "$ARGUMENTS" not in skill.content

    def test_very_long_url(self):
        long_url = "https://example.com/" + "a" * 500
        skill = load_skill("default-crawl", long_url)
        assert long_url in skill.content

    def test_all_skills_have_supporting_files(self):
        for name in ALL_SKILL_NAMES:
            skill = load_skill(name)
            assert "examples/sample-output.json" in skill.supporting_files, (
                f"{name} missing examples/sample-output.json"
            )

    def test_all_sample_outputs_are_valid_json(self):
        for name in ALL_SKILL_NAMES:
            raw = load_supporting_file(name, "examples/sample-output.json")
            data = json.loads(raw)
            assert isinstance(data, dict), f"{name} sample output is not a dict"
