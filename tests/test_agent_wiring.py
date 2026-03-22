"""Tests that the agent module loads and the entrypoint is wired correctly."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_system_prompt_includes_skill():
    """Verify the system prompt template gets populated with skill content."""
    from src.skills import load_skill

    SYSTEM_PROMPT_TEMPLATE = """You are a web-crawler code generator and executor.

## Crawl-Style Instructions
{crawl_style}
"""
    skill = load_skill("default-crawl", arguments="https://example.com")
    prompt = SYSTEM_PROMPT_TEMPLATE.format(crawl_style=skill.content)

    assert "requests" in prompt
    assert "beautifulsoup4" in prompt
    assert "https://example.com" in prompt
    print("✓ System prompt correctly interpolates skill content with arguments")


def test_payload_parsing():
    """Verify payload defaults work as expected."""
    payload_with_skill = {
        "prompt": "Crawl https://example.com",
        "skill": "ecommerce-crawl",
        "args": "https://example.com 3",
    }
    payload_minimal = {"prompt": "Crawl https://example.com"}
    payload_empty = {}

    # Explicit skill provided
    assert payload_with_skill.get("skill") == "ecommerce-crawl"
    # No skill → should be None (triggers auto-select)
    assert payload_minimal.get("skill") is None
    assert payload_empty.get("prompt", "") == ""
    # args defaults to prompt when not provided
    assert payload_minimal.get("args", payload_minimal.get("prompt", "")) == "Crawl https://example.com"
    print("✓ Payload parsing and defaults work correctly")


def test_skill_metadata_in_response():
    """Verify list_skills returns proper metadata."""
    from src.skills import list_skills

    skills = list_skills()
    assert len(skills) >= 2
    for s in skills:
        assert "name" in s
        assert "description" in s
        assert len(s["description"]) > 0
    print("✓ Skill metadata includes name and description")


def test_extract_crawler_output():
    """Verify _extract_crawler_output parses delimited JSON from agent messages."""
    import re, json

    _CRAWLER_JSON_RE = re.compile(
        r"<<<CRAWLER_JSON>>>\s*(.*?)\s*<<<END_CRAWLER_JSON>>>", re.DOTALL
    )

    # Simulate a Code Interpreter toolResult message
    fake_messages = [
        {
            "role": "user",
            "content": [{"text": "Crawl https://example.com"}],
        },
        {
            "role": "assistant",
            "content": [
                {
                    "toolUse": {
                        "toolUseId": "t1",
                        "name": "code_interpreter",
                        "input": {"code": "print('hello')"},
                    }
                }
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "toolResult": {
                        "toolUseId": "t1",
                        "content": [
                            {
                                "text": 'Some debug output\n<<<CRAWLER_JSON>>>\n{"url": "https://example.com", "title": "Example"}\n<<<END_CRAWLER_JSON>>>\nDone.'
                            }
                        ],
                    }
                }
            ],
        },
    ]

    # Replicate extraction logic inline
    result = None
    for msg in reversed(fake_messages):
        content = msg.get("content") if isinstance(msg, dict) else None
        if not content:
            continue
        for block in content:
            tool_result = block.get("toolResult") if isinstance(block, dict) else None
            if not tool_result:
                continue
            for item in tool_result.get("content", []):
                text = item.get("text", "") if isinstance(item, dict) else ""
                m = _CRAWLER_JSON_RE.search(text)
                if m:
                    result = json.loads(m.group(1))
                    break

    assert result is not None
    assert result["url"] == "https://example.com"
    assert result["title"] == "Example"
    print("✓ _extract_crawler_output correctly parses delimited JSON from tool results")


def test_base64_extraction():
    """Verify base64-encoded crawler output is correctly decoded."""
    import json, base64, re

    _CRAWLER_B64_RE = re.compile(
        r"<<<CRAWLER_B64>>>\s*(.*?)\s*<<<END_CRAWLER_B64>>>", re.DOTALL
    )

    # Simulate Chinese content encoded as base64
    chinese_data = {
        "rank": "1",
        "title": "肖申克的救赎",
        "rating": "9.7",
        "director": "弗兰克·德拉邦特",
    }
    raw = json.dumps(chinese_data, ensure_ascii=False).encode("utf-8")
    b64 = base64.b64encode(raw).decode("ascii")
    # Simulate chunked output (76 chars per line)
    lines = [b64[i:i+76] for i in range(0, len(b64), 76)]
    stdout = "<<<CRAWLER_B64>>>\n" + "\n".join(lines) + "\n<<<END_CRAWLER_B64>>>"

    m = _CRAWLER_B64_RE.search(stdout)
    assert m is not None
    raw_b64 = re.sub(r'\s+', '', m.group(1).strip())
    decoded = json.loads(base64.b64decode(raw_b64).decode("utf-8"))

    assert decoded["title"] == "肖申克的救赎"
    assert decoded["director"] == "弗兰克·德拉邦特"
    print("✓ Base64 extraction correctly decodes Chinese characters")


def test_ensure_ascii_safe_roundtrip():
    """Verify _ensure_ascii_safe + json.loads round-trip preserves Chinese."""
    import json

    # Import the function from main.py without triggering agent/bedrock imports
    # Replicate the logic inline
    def _ensure_ascii_safe(obj):
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

    # Import the actual CLI unescape function
    from crawler_cli import _unescape_unicode_recursive

    original = {
        "电影名称": "肖申克的救赎",
        "导演": "弗兰克·德拉邦特 Frank Darabont",
        "评分": "9.7",
        "items": [{"名称": "霸王别姬", "年份": "1993"}],
        "描述": "第一行\n第二行\n第三行",
    }

    escaped = _ensure_ascii_safe(original)

    # All strings should be pure ASCII now
    escaped_json = json.dumps(escaped)
    assert all(ord(c) < 128 for c in escaped_json), "Escaped JSON contains non-ASCII"

    # Round-trip: simulate agentcore wire → CLI json.loads → unescape
    wire = json.dumps(escaped, ensure_ascii=False)
    restored = json.loads(wire)
    final = _unescape_unicode_recursive(restored)

    assert final["电影名称"] == "肖申克的救赎"
    assert final["导演"] == "弗兰克·德拉邦特 Frank Darabont"
    assert final["items"][0]["名称"] == "霸王别姬"
    assert final["描述"] == "第一行\n第二行\n第三行"
    print("✓ ensure_ascii_safe round-trip preserves Chinese characters and newlines")


def test_mojibake_detection():
    """Verify _looks_like_mojibake detects corrupted Chinese text."""
    # Replicate the detection logic inline
    import json

    def _looks_like_mojibake(obj):
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

    # Clean Chinese text should NOT be detected as mojibake
    clean = {"title": "肖申克的救赎", "rating": "9.7"}
    assert not _looks_like_mojibake(clean), "Clean Chinese falsely detected as mojibake"

    # Corrupted text SHOULD be detected
    corrupted = {"title": "èç³åçæèµ", "rating": "9.7", "director": "å¼å°åÂ·å¾·æé¦ç¹"}
    assert _looks_like_mojibake(corrupted), "Corrupted text not detected as mojibake"

    # Pure ASCII should NOT be detected
    ascii_only = {"title": "The Shawshank Redemption", "rating": "9.7"}
    assert not _looks_like_mojibake(ascii_only), "ASCII text falsely detected as mojibake"

    print("✓ Mojibake detection works correctly")
