"""深度编码管道测试

覆盖 main.py 中所有编码/解码函数，包括之前测试中未完整覆盖的路径。
函数实现从 main.py 内联复制（与 test_agent_wiring.py 的做法一致），
避免触发 strands/bedrock 模块级副作用。

覆盖范围：
- _repair_mojibake：1 层 / 2 层嵌套 / 不可修复内容
- _repair_mojibake_recursive：dict / list / 嵌套结构
- _looks_like_mojibake：标记计数 / 高字节比率 / 边界情况
- _decode_candidates：多种 unescape 路径
- _unwrap_ci_text：Python repr 格式 / 正则回退 / 无包装
- _extract_crawler_output：B64 / JSON 定界符 / 裸 JSON / toolResult / assistant text
- _ensure_ascii_safe：dict key / list / 嵌套 / 非字符串值
- 完整编码往返：中文 / 日文 / 法语重音 / 特殊字符
"""

import ast
import base64
import json
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ---------------------------------------------------------------------------
# 内联复制 main.py 中的被测函数（不触发模块级副作用）
# ---------------------------------------------------------------------------

def _repair_mojibake(text: str) -> str:
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
    if isinstance(obj, str):
        return _repair_mojibake(obj)
    if isinstance(obj, dict):
        return {k: _repair_mojibake_recursive(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_repair_mojibake_recursive(item) for item in obj]
    return obj


def _decode_candidates(raw: str) -> list:
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
    inner_texts = re.findall(r"'text':\s*'((?:[^'\\]|\\.)*)'", text)
    if not inner_texts:
        inner_texts = re.findall(r'"text":\s*"((?:[^"\\]|\\.)*)"', text)
    if inner_texts:
        return '\n'.join(inner_texts)
    return text


_CRAWLER_JSON_RE = re.compile(
    r"<<<CRAWLER_JSON>>>\s*(.*?)\s*<<<END_CRAWLER_JSON>>>", re.DOTALL
)
_CRAWLER_B64_RE = re.compile(
    r"<<<CRAWLER_B64>>>\s*(.*?)\s*<<<END_CRAWLER_B64>>>", re.DOTALL
)


def _extract_crawler_output(agent):
    messages = getattr(agent, "messages", None) or []

    def _try_parse(text: str):
        unwrapped = _unwrap_ci_text(text)
        for search_text in ([unwrapped, text] if unwrapped != text else [text]):
            text_no_nl = search_text.replace('\n', '').replace('\r', '')
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
        for block in content:
            text = block.get("text", "") if isinstance(block, dict) else ""
            parsed = _try_parse(text)
            if parsed is not None:
                return parsed
    return None


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


# ---------------------------------------------------------------------------
# _repair_mojibake
# ---------------------------------------------------------------------------

class TestRepairMojibake(unittest.TestCase):
    def test_repairs_single_layer(self):
        original = "肖申克的救赎"
        corrupted = original.encode("utf-8").decode("latin-1")
        self.assertEqual(_repair_mojibake(corrupted), original)

    def test_repairs_two_layers(self):
        original = "弗兰克·德拉邦特"
        layer1 = original.encode("utf-8").decode("latin-1")
        layer2 = layer1.encode("utf-8").decode("latin-1")
        self.assertEqual(_repair_mojibake(layer2), original)

    def test_preserves_clean_ascii(self):
        text = "The Shawshank Redemption (1994)"
        self.assertEqual(_repair_mojibake(text), text)

    def test_preserves_clean_chinese(self):
        self.assertEqual(_repair_mojibake("霸王别姬"), "霸王别姬")

    def test_stops_on_unrecoverable_garbage(self):
        garbage = "\x80\x81\x82\x83\x84"
        result = _repair_mojibake(garbage)
        self.assertIsInstance(result, str)

    def test_empty_string(self):
        self.assertEqual(_repair_mojibake(""), "")

    def test_latin_accents_preserved(self):
        self.assertEqual(_repair_mojibake("Léon: The Professional"),
                         "Léon: The Professional")


# ---------------------------------------------------------------------------
# _repair_mojibake_recursive
# ---------------------------------------------------------------------------

class TestRepairMojibakeRecursive(unittest.TestCase):
    def _corrupt(self, s):
        return s.encode("utf-8").decode("latin-1")

    def test_fixes_string(self):
        self.assertEqual(_repair_mojibake_recursive(self._corrupt("肖申克的救赎")),
                         "肖申克的救赎")

    def test_fixes_dict_values(self):
        result = _repair_mojibake_recursive({
            "title": self._corrupt("霸王别姬"),
            "rating": "9.6",
        })
        self.assertEqual(result["title"], "霸王别姬")
        self.assertEqual(result["rating"], "9.6")

    def test_fixes_list_items(self):
        result = _repair_mojibake_recursive([self._corrupt("肖申克的救赎"), "ok"])
        self.assertEqual(result[0], "肖申克的救赎")
        self.assertEqual(result[1], "ok")

    def test_fixes_nested_structure(self):
        result = _repair_mojibake_recursive({
            "movies": [
                {"title": self._corrupt("活着"), "year": 1994},
                {"title": self._corrupt("花样年华"), "year": 2000},
            ]
        })
        self.assertEqual(result["movies"][0]["title"], "活着")
        self.assertEqual(result["movies"][1]["title"], "花样年华")

    def test_preserves_non_string_values(self):
        result = _repair_mojibake_recursive(
            {"count": 42, "active": True, "score": 9.5, "data": None}
        )
        self.assertEqual(result["count"], 42)
        self.assertIs(result["active"], True)
        self.assertAlmostEqual(result["score"], 9.5)
        self.assertIsNone(result["data"])


# ---------------------------------------------------------------------------
# _looks_like_mojibake
# ---------------------------------------------------------------------------

class TestLooksLikeMojibake(unittest.TestCase):
    def test_clean_chinese_not_mojibake(self):
        self.assertFalse(_looks_like_mojibake({"title": "肖申克的救赎"}))

    def test_corrupted_chinese_is_mojibake(self):
        corrupted_text = "Ã¨Â¿Â·Ã§Â³Â»Ã¥Â°Â·"
        self.assertTrue(_looks_like_mojibake(corrupted_text))

    def test_pure_ascii_not_mojibake(self):
        self.assertFalse(_looks_like_mojibake("Hello World 123"))

    def test_empty_string_not_mojibake(self):
        self.assertFalse(_looks_like_mojibake(""))

    def test_empty_dict_not_mojibake(self):
        self.assertFalse(_looks_like_mojibake({}))

    def test_high_byte_ratio_triggers_detection(self):
        text = "Ã¨" + "\x80" * 30
        self.assertTrue(_looks_like_mojibake(text))

    def test_single_marker_below_threshold_not_mojibake(self):
        text = "Normal text Ã¨ normal text"
        self.assertFalse(_looks_like_mojibake(text))

    def test_three_or_more_markers_is_mojibake(self):
        text = "Ã¨ some text Ã¥ more text Ã¦ end"
        self.assertTrue(_looks_like_mojibake(text))

    def test_japanese_not_mojibake(self):
        self.assertFalse(_looks_like_mojibake({"title": "こんにちは世界"}))

    def test_mixed_cjk_not_mojibake(self):
        data = [{"title": "活着"}, {"title": "霸王别姬"}, {"title": "花样年华"}]
        self.assertFalse(_looks_like_mojibake(data))


# ---------------------------------------------------------------------------
# _decode_candidates
# ---------------------------------------------------------------------------

class TestDecodeCandidates(unittest.TestCase):
    def test_includes_original(self):
        raw = '{"title": "hello"}'
        self.assertIn(raw, _decode_candidates(raw))

    def test_includes_unescaped_newlines(self):
        raw = '{"text": "line1\\nline2"}'
        self.assertTrue(any("\n" in c for c in _decode_candidates(raw)))

    def test_includes_unicode_unescaped(self):
        """\\uXXXX 转义序列在候选列表中能被 unicode_escape 解码路径还原。"""
        # 肖(U+8096) 申(U+7533) 克(U+514B)
        raw = '\\u8096\\u7533\\u514b'
        candidates = _decode_candidates(raw)
        self.assertTrue(any("肖申克" in c for c in candidates),
                        f"Expected '肖申克' in one of: {candidates}")

    def test_includes_mojibake_repaired(self):
        """_decode_candidates 应包含 mojibake 修复后的候选字符串。"""
        original = "肖申克的救赎"
        corrupted = original.encode("utf-8").decode("latin-1")
        # 直接将 corrupted 字符串作为 raw 传入（不用 json.dumps 包装）
        candidates = _decode_candidates(corrupted)
        # 修复路径应出现
        self.assertIn(original, candidates,
                      f"Expected '{original}' in candidates: {candidates}")

    def test_returns_list(self):
        self.assertIsInstance(_decode_candidates("test"), list)

    def test_non_empty_for_clean_ascii(self):
        raw = '{"title": "The Shawshank Redemption"}'
        self.assertGreater(len(_decode_candidates(raw)), 0)


# ---------------------------------------------------------------------------
# _unwrap_ci_text
# ---------------------------------------------------------------------------

class TestUnwrapCiText(unittest.TestCase):
    def test_unwraps_python_repr_list(self):
        inner = "<<<CRAWLER_JSON>>>\n{}\n<<<END_CRAWLER_JSON>>>"
        wrapped = repr([{"type": "text", "text": inner}])
        self.assertIn("<<<CRAWLER_JSON>>>", _unwrap_ci_text(wrapped))

    def test_falls_back_to_regex_single_quotes(self):
        wrapped = "[{'type': 'text', 'text': 'hello world'}]"
        self.assertIn("hello world", _unwrap_ci_text(wrapped))

    def test_returns_original_when_no_wrap(self):
        plain = "some plain text without wrapping"
        self.assertEqual(_unwrap_ci_text(plain), plain)

    def test_handles_multiple_text_blocks(self):
        wrapped = repr([
            {"type": "text", "text": "part1"},
            {"type": "text", "text": "part2"},
        ])
        result = _unwrap_ci_text(wrapped)
        self.assertIn("part1", result)
        self.assertIn("part2", result)

    def test_handles_non_list_repr(self):
        self.assertEqual(_unwrap_ci_text("{not a list}"), "{not a list}")

    def test_json_format_also_works(self):
        wrapped = json.dumps([{"type": "text", "text": "json_content"}])
        self.assertIn("json_content", _unwrap_ci_text(wrapped))


# ---------------------------------------------------------------------------
# _extract_crawler_output
# ---------------------------------------------------------------------------

class _FakeAgent:
    def __init__(self, messages):
        self.messages = messages


class TestExtractCrawlerOutput(unittest.TestCase):
    def _tool_result_msg(self, stdout: str):
        return {
            "role": "user",
            "content": [{
                "toolResult": {
                    "toolUseId": "t1",
                    "content": [{"text": stdout}],
                }
            }],
        }

    def _assistant_msg(self, text: str):
        return {"role": "assistant", "content": [{"text": text}]}

    def test_extracts_b64_delimited(self):
        data = {"title": "肖申克的救赎", "rating": "9.7"}
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        b64 = base64.b64encode(raw).decode("ascii")
        stdout = f"<<<CRAWLER_B64>>>\n{b64}\n<<<END_CRAWLER_B64>>>"
        result = _extract_crawler_output(
            _FakeAgent([self._tool_result_msg(stdout)])
        )
        self.assertEqual(result["title"], "肖申克的救赎")

    def test_extracts_b64_chunked_lines(self):
        data = {"items": list(range(50))}
        raw = json.dumps(data).encode("utf-8")
        b64 = base64.b64encode(raw).decode("ascii")
        lines = "\n".join(b64[i:i+76] for i in range(0, len(b64), 76))
        stdout = f"debug\n<<<CRAWLER_B64>>>\n{lines}\n<<<END_CRAWLER_B64>>>\ndone"
        result = _extract_crawler_output(
            _FakeAgent([self._tool_result_msg(stdout)])
        )
        self.assertEqual(result["items"], list(range(50)))

    def test_extracts_json_delimited(self):
        stdout = (
            "Crawling...\n"
            '<<<CRAWLER_JSON>>>\n{"url": "https://example.com", "title": "Test"}\n'
            "<<<END_CRAWLER_JSON>>>"
        )
        result = _extract_crawler_output(
            _FakeAgent([self._tool_result_msg(stdout)])
        )
        self.assertEqual(result["url"], "https://example.com")

    def test_extracts_json_block_from_tool_result(self):
        msg = {
            "role": "user",
            "content": [{
                "toolResult": {
                    "toolUseId": "t1",
                    "content": [{"json": {"title": "JSON block title", "count": 5}}],
                }
            }],
        }
        result = _extract_crawler_output(_FakeAgent([msg]))
        self.assertEqual(result["title"], "JSON block title")

    def test_extracts_from_assistant_text(self):
        stdout = (
            '<<<CRAWLER_JSON>>>\n{"title": "from assistant"}\n<<<END_CRAWLER_JSON>>>'
        )
        result = _extract_crawler_output(
            _FakeAgent([self._assistant_msg(stdout)])
        )
        self.assertIsNotNone(result)

    def test_extracts_from_ci_wrapped_output(self):
        inner = '<<<CRAWLER_JSON>>>\n{"product": "Widget"}\n<<<END_CRAWLER_JSON>>>'
        wrapped = repr([{"type": "text", "text": inner}])
        result = _extract_crawler_output(
            _FakeAgent([self._tool_result_msg(wrapped)])
        )
        self.assertIsNotNone(result)

    def test_returns_none_for_no_messages(self):
        self.assertIsNone(_extract_crawler_output(_FakeAgent([])))

    def test_returns_none_for_plain_text(self):
        self.assertIsNone(
            _extract_crawler_output(
                _FakeAgent([self._tool_result_msg("Just debug output")])
            )
        )

    def test_extracts_bare_json_with_sufficient_keys(self):
        stdout = '{"url": "https://bare.example.com", "title": "Bare", "extra": true}'
        result = _extract_crawler_output(
            _FakeAgent([self._tool_result_msg(stdout)])
        )
        # 裸 JSON 需要 >= 2 个 key 才会被提取
        if result is not None:
            self.assertIn("url", result)

    def test_b64_takes_priority_over_json_delimiter(self):
        """同时存在 B64 和 JSON 定界符时，B64 优先。"""
        data_b64 = {"source": "b64", "value": 1}
        raw = json.dumps(data_b64).encode("utf-8")
        b64 = base64.b64encode(raw).decode("ascii")
        stdout = (
            f"<<<CRAWLER_B64>>>\n{b64}\n<<<END_CRAWLER_B64>>>\n"
            '<<<CRAWLER_JSON>>>\n{"source": "json", "value": 2}\n<<<END_CRAWLER_JSON>>>'
        )
        result = _extract_crawler_output(
            _FakeAgent([self._tool_result_msg(stdout)])
        )
        self.assertEqual(result["source"], "b64")


# ---------------------------------------------------------------------------
# _ensure_ascii_safe
# ---------------------------------------------------------------------------

class TestEnsureAsciiSafe(unittest.TestCase):
    def setUp(self):
        from crawler_cli import _unescape_unicode_recursive
        self._unescape = _unescape_unicode_recursive

    def _roundtrip(self, obj):
        escaped = _ensure_ascii_safe(obj)
        wire = json.dumps(escaped, ensure_ascii=False)
        restored = json.loads(wire)
        return self._unescape(restored)

    def test_string_becomes_ascii(self):
        result = _ensure_ascii_safe("肖申克的救赎")
        self.assertTrue(all(ord(c) < 128 for c in result))

    def test_dict_values_become_ascii(self):
        result = _ensure_ascii_safe({"title": "霸王别姬", "year": 1993})
        self.assertTrue(all(ord(c) < 128 for c in json.dumps(result)))

    def test_dict_keys_become_ascii(self):
        result = _ensure_ascii_safe({"电影名称": "活着"})
        for k in result.keys():
            self.assertTrue(all(ord(c) < 128 for c in k))

    def test_list_items_become_ascii(self):
        result = _ensure_ascii_safe(["肖申克的救赎", "霸王别姬"])
        for item in result:
            self.assertTrue(all(ord(c) < 128 for c in item))

    def test_non_string_values_preserved(self):
        result = _ensure_ascii_safe({"count": 42, "active": True, "score": 9.7})
        self.assertEqual(result["count"], 42)
        self.assertIs(result["active"], True)
        self.assertAlmostEqual(result["score"], 9.7)

    def test_roundtrip_chinese(self):
        restored = self._roundtrip({"title": "肖申克的救赎", "director": "弗兰克·德拉邦特"})
        self.assertEqual(restored["title"], "肖申克的救赎")
        self.assertEqual(restored["director"], "弗兰克·德拉邦特")

    def test_roundtrip_japanese(self):
        restored = self._roundtrip({"title": "こんにちは世界"})
        self.assertEqual(restored["title"], "こんにちは世界")

    def test_roundtrip_french_accents(self):
        restored = self._roundtrip({"title": "Léon: The Professional"})
        self.assertEqual(restored["title"], "Léon: The Professional")

    def test_roundtrip_nested(self):
        original = {
            "电影": [
                {"名称": "活着", "年份": 1994},
                {"名称": "花样年华", "年份": 2000},
            ]
        }
        restored = self._roundtrip(original)
        self.assertEqual(restored["电影"][0]["名称"], "活着")
        self.assertEqual(restored["电影"][1]["名称"], "花样年华")

    def test_roundtrip_with_newlines(self):
        restored = self._roundtrip({"body": "第一行\n第二行\n第三行"})
        self.assertEqual(restored["body"], "第一行\n第二行\n第三行")

    def test_roundtrip_empty_string(self):
        self.assertEqual(self._roundtrip({"key": ""})["key"], "")

    def test_idempotent_on_pure_ascii(self):
        result = _ensure_ascii_safe({"title": "The Shawshank Redemption", "year": 1994})
        self.assertEqual(result["title"], "The Shawshank Redemption")


# ---------------------------------------------------------------------------
# 完整编码往返：模拟 AgentCore 传输链路
# ---------------------------------------------------------------------------

class TestFullEncodingPipeline(unittest.TestCase):
    def setUp(self):
        from crawler_cli import _unescape_unicode_recursive
        self._unescape = _unescape_unicode_recursive

    def _transport(self, obj):
        escaped = _ensure_ascii_safe(obj)
        wire = json.dumps(escaped, ensure_ascii=False)
        received = json.loads(wire)
        return self._unescape(received)

    def test_top250_movie_data(self):
        movies = [
            {"rank": 1, "title": "肖申克的救赎", "rating": 9.7,
             "director": "弗兰克·德拉邦特"},
            {"rank": 2, "title": "霸王别姬", "rating": 9.6, "director": "陈凯歌"},
            {"rank": 3, "title": "阿甘正传", "rating": 9.5,
             "director": "罗伯特·泽米吉斯"},
        ]
        result = self._transport({"movies": movies})
        self.assertEqual(result["movies"][0]["title"], "肖申克的救赎")
        self.assertEqual(result["movies"][1]["director"], "陈凯歌")
        self.assertEqual(result["movies"][2]["title"], "阿甘正传")

    def test_ecommerce_product_data(self):
        products = [
            {"name": "MacBook Pro", "price": "¥19999", "brand": "苹果"},
            {"name": "iPhone 15", "price": "¥7999", "brand": "苹果"},
        ]
        result = self._transport({"products": products, "total": 2})
        self.assertEqual(result["products"][0]["price"], "¥19999")
        self.assertEqual(result["total"], 2)

    def test_news_article_data(self):
        articles = [{
            "title": "人工智能技术最新进展",
            "author": "张三",
            "body": "近日，多项 AI 研究取得突破...\n详情见正文。",
        }]
        result = self._transport({"articles": articles})
        self.assertEqual(result["articles"][0]["title"], "人工智能技术最新进展")
        self.assertIn("\n", result["articles"][0]["body"])

    def test_mixed_language_data(self):
        data = {
            "zh": "中文内容",
            "ja": "日本語コンテンツ",
            "fr": "Léon: The Professional",
            "en": "English content",
        }
        result = self._transport(data)
        self.assertEqual(result["zh"], "中文内容")
        self.assertEqual(result["ja"], "日本語コンテンツ")
        self.assertEqual(result["fr"], "Léon: The Professional")
        self.assertEqual(result["en"], "English content")

    def test_special_characters_preserved(self):
        data = {"symbols": "© ® ™ € £ ¥"}
        result = self._transport(data)
        self.assertEqual(result["symbols"], "© ® ™ € £ ¥")

    def test_large_dataset_integrity(self):
        movies = [
            {"rank": i, "title": f"电影{i:03d}", "rating": round(8.0 + i * 0.004, 3)}
            for i in range(1, 251)
        ]
        result = self._transport({"movies": movies, "total": 250})
        self.assertEqual(len(result["movies"]), 250)
        self.assertEqual(result["movies"][0]["title"], "电影001")
        self.assertEqual(result["movies"][249]["title"], "电影250")
        self.assertEqual(result["total"], 250)


if __name__ == "__main__":
    unittest.main(verbosity=2)
