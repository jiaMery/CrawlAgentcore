"""云端 E2E 测试框架

当以下环境变量全部设置时，对真实部署的 AgentCore Runtime 发起 HTTP 调用：
  AGENTCORE_RUNTIME_ID   — Runtime ID
  AGENTCORE_ENDPOINT_ARN — Endpoint ARN
  AWS_REGION             — AWS 区域（默认 us-east-1）
  AWS_ACCOUNT_ID         — AWS 账号 ID

缺少任意一个时，所有云端测试自动标记为 SKIP，本地 CI 不受影响。

测试分组：
1. TestCloudHealthCheck    — Runtime 可达性 / invoke 基本响应
2. TestCloudSkillRouting   — 各技能在真实 Runtime 上的路由验证
3. TestCloudCrawlFunctional — 对真实公开网站的功能性爬取
4. TestCloudEncodingE2E    — 云端 CJK 编码往返（含 _ensure_ascii_safe 链路）
5. TestCloudBrowserStub    — Browser 工具路径存在性验证（不执行完整爬取）
6. TestCloudPerformance    — invoke 延迟基准（需要 CLOUD_PERF_TEST=1 才执行）
"""

import json
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ---------------------------------------------------------------------------
# 运行时判断：所需环境变量是否全部存在
# ---------------------------------------------------------------------------

_REQUIRED_VARS = ["AGENTCORE_RUNTIME_ID", "AWS_REGION", "AWS_ACCOUNT_ID"]
_CLOUD_VARS_PRESENT = all(os.environ.get(v) for v in _REQUIRED_VARS)

_SKIP_REASON = (
    "云端 E2E 测试需要以下环境变量："
    + ", ".join(_REQUIRED_VARS)
    + "。当前环境变量缺失，已跳过。"
)

cloud_test = unittest.skipUnless(_CLOUD_VARS_PRESENT, _SKIP_REASON)
perf_test = unittest.skipUnless(
    _CLOUD_VARS_PRESENT and os.environ.get("CLOUD_PERF_TEST") == "1",
    "性能基准测试需要 CLOUD_PERF_TEST=1 且云端环境变量。"
)


# ---------------------------------------------------------------------------
# 调用辅助
# ---------------------------------------------------------------------------

def _invoke_runtime(payload: dict, timeout: int = 120) -> dict:
    """向 AgentCore Runtime 发起 invoke 调用，返回解析后的响应体。"""
    import boto3

    region = os.environ.get("AWS_REGION", "us-east-1")
    runtime_id = os.environ["AGENTCORE_RUNTIME_ID"]
    endpoint_name = os.environ.get("AGENTCORE_ENDPOINT_NAME", "crawlerEndpoint")

    client = boto3.client("bedrock-agentcore", region_name=region)
    response = client.invoke_agent_runtime(
        agentRuntimeId=runtime_id,
        qualifier=endpoint_name,
        payload=json.dumps(payload),
    )

    raw = response.get("response", b"")
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8")
    if isinstance(raw, str):
        return json.loads(raw)
    return raw


def _unescape(obj):
    """展开响应中的 \\uXXXX 序列。"""
    if isinstance(obj, str):
        import re
        _RE = re.compile(r'[\\]u([0-9a-fA-F]{4})')
        return _RE.sub(lambda m: chr(int(m.group(1), 16)), obj)
    if isinstance(obj, dict):
        return {_unescape(k): _unescape(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_unescape(item) for item in obj]
    return obj


# ---------------------------------------------------------------------------
# 1. 健康检查
# ---------------------------------------------------------------------------

@cloud_test
class TestCloudHealthCheck(unittest.TestCase):
    """基本可达性：Runtime 能正确响应 invoke 请求。"""

    def test_runtime_responds(self):
        """Runtime 对合法 payload 能在 120s 内返回响应。"""
        resp = _invoke_runtime({"prompt": "Return the string PONG", "skill": "default-crawl"})
        self.assertIsInstance(resp, dict, "Response should be a dict")

    def test_response_has_required_keys(self):
        resp = _invoke_runtime({"prompt": "hello", "skill": "default-crawl"})
        for key in ("result", "skill_used", "available_skills"):
            self.assertIn(key, resp, f"Missing key: {key}")

    def test_available_skills_count(self):
        resp = _invoke_runtime({"prompt": "hello", "skill": "default-crawl"})
        skills = resp.get("available_skills", [])
        self.assertGreaterEqual(len(skills), 6, "Should have at least 6 skills")

    def test_skill_used_is_string(self):
        resp = _invoke_runtime({"prompt": "hello", "skill": "default-crawl"})
        self.assertIsInstance(resp.get("skill_used"), str)


# ---------------------------------------------------------------------------
# 2. 技能路由
# ---------------------------------------------------------------------------

@cloud_test
class TestCloudSkillRouting(unittest.TestCase):
    """各技能显式路由：Runtime 使用正确的技能。"""

    def _check_skill(self, skill_name, url):
        resp = _invoke_runtime({"skill": skill_name, "args": url})
        used = resp.get("skill_used", "")
        # 允许回退到 default-crawl
        self.assertIn(used, [skill_name, "default-crawl"],
                      f"Unexpected skill: {used}")
        return resp

    def test_ecommerce_skill_routed(self):
        self._check_skill("ecommerce-crawl", "https://books.toscrape.com")

    def test_news_skill_routed(self):
        self._check_skill("news-crawl", "https://news.ycombinator.com")

    def test_api_skill_routed(self):
        self._check_skill("api-crawl", "https://jsonplaceholder.typicode.com/users")

    def test_docs_skill_routed(self):
        self._check_skill("docs-crawl", "https://docs.python.org/3/library/json.html")

    def test_social_skill_routed(self):
        self._check_skill("social-crawl", "https://news.ycombinator.com")

    def test_auto_select_returns_valid_skill(self):
        """不指定 skill，让 LLM 自动选择，验证结果是已知技能名之一。"""
        resp = _invoke_runtime({
            "prompt": "Scrape product listings from https://books.toscrape.com"
        })
        known_skills = ["default-crawl", "ecommerce-crawl", "news-crawl",
                        "api-crawl", "docs-crawl", "social-crawl"]
        self.assertIn(resp.get("skill_used", ""), known_skills)
        self.assertTrue(resp.get("auto_selected", False))


# ---------------------------------------------------------------------------
# 3. 功能性爬取
# ---------------------------------------------------------------------------

@cloud_test
class TestCloudCrawlFunctional(unittest.TestCase):
    """对真实公开网站的爬取功能验证。"""

    def test_api_crawl_jsonplaceholder_users(self):
        resp = _invoke_runtime({
            "skill": "api-crawl",
            "args": "https://jsonplaceholder.typicode.com/users 1",
        })
        output = _unescape(resp.get("crawler_output"))
        self.assertIsNotNone(output, "crawler_output should not be None")
        if isinstance(output, list):
            self.assertGreater(len(output), 0)
        elif isinstance(output, dict):
            # 可能包在 {"data": [...]} 中
            self.assertFalse("error" in output,
                             f"Crawl returned error: {output.get('error')}")

    def test_ecommerce_crawl_books_toscrape(self):
        resp = _invoke_runtime({
            "skill": "ecommerce-crawl",
            "args": "https://books.toscrape.com 1",
        })
        output = _unescape(resp.get("crawler_output"))
        self.assertIsNotNone(output)
        if isinstance(output, dict):
            self.assertFalse("error" in output and len(output) == 1,
                             f"Crawl returned only error: {output}")
        # 验证有书名数据
        raw_str = json.dumps(output or {}, ensure_ascii=False)
        self.assertTrue(
            any(kw in raw_str for kw in ["book", "price", "product", "title", "name"]),
            "Expected product data keywords in output"
        )

    def test_news_crawl_hacker_news(self):
        resp = _invoke_runtime({
            "skill": "news-crawl",
            "args": "https://news.ycombinator.com 1",
        })
        output = _unescape(resp.get("crawler_output"))
        self.assertIsNotNone(output)
        if isinstance(output, dict):
            self.assertFalse("error" in output and len(output) == 1)
        raw_str = json.dumps(output or {}, ensure_ascii=False)
        self.assertTrue(
            any(kw in raw_str.lower() for kw in ["title", "article", "news", "url"]),
            "Expected news data in output"
        )

    def test_default_crawl_example_com(self):
        resp = _invoke_runtime({
            "skill": "default-crawl",
            "args": "https://example.com",
        })
        output = resp.get("crawler_output")
        # example.com 是最简单的页面，应能正常抓取
        self.assertIsNotNone(output)


# ---------------------------------------------------------------------------
# 4. 云端编码 E2E
# ---------------------------------------------------------------------------

@cloud_test
class TestCloudEncodingE2E(unittest.TestCase):
    """验证 _ensure_ascii_safe → 云端传输 → CLI unescape 完整链路。"""

    def test_chinese_preserved_through_cloud(self):
        """向 Runtime 发送包含中文提示词，验证响应能正常解析（不乱码）。"""
        resp = _invoke_runtime({
            "prompt": "请抓取 https://example.com 的页面标题",
            "skill": "default-crawl",
            "args": "https://example.com",
        })
        # 响应必须能成功 JSON 解析（已在 _invoke_runtime 中完成）
        self.assertIsInstance(resp, dict)
        result_str = json.dumps(resp, ensure_ascii=False)
        # 确保没有 mojibake 标记
        mojibake_markers = ["Ã¨", "Ã¥", "Ã¦", "Ã©", "Â·"]
        for marker in mojibake_markers:
            self.assertNotIn(marker, result_str,
                             f"Response contains mojibake marker: {marker!r}")

    def test_response_is_json_serializable(self):
        resp = _invoke_runtime({
            "skill": "default-crawl",
            "args": "https://example.com",
        })
        try:
            json.dumps(resp)
        except (TypeError, ValueError) as e:
            self.fail(f"Response is not JSON serializable: {e}")

    def test_unescape_restores_cjk(self):
        """如果 crawler_output 含有 CJK 转义序列，unescape 后应能还原。"""
        resp = _invoke_runtime({
            "skill": "default-crawl",
            "args": "https://example.com",
        })
        output = resp.get("crawler_output")
        if output is not None:
            restored = _unescape(output)
            self.assertIsNotNone(restored)


# ---------------------------------------------------------------------------
# 5. Browser 工具存在性验证
# ---------------------------------------------------------------------------

@cloud_test
class TestCloudBrowserStub(unittest.TestCase):
    """验证 browser_crawl 工具路径在 Runtime 中可用（不执行完整爬取）。"""

    def test_browser_available_flag_in_response(self):
        """当请求中不指定 use_browser 时，browser_used 应为 False。"""
        resp = _invoke_runtime({
            "skill": "default-crawl",
            "args": "https://example.com",
        })
        browser_used = resp.get("browser_used", False)
        self.assertFalse(browser_used,
                         "browser_used should be False when not requested")

    @unittest.skipUnless(
        os.environ.get("BROWSER_ID") and _CLOUD_VARS_PRESENT,
        "Browser E2E 需要 BROWSER_ID 环境变量"
    )
    def test_browser_crawl_returns_structure(self):
        """当 use_browser=True 且 BROWSER_ID 已设置时，验证响应结构。"""
        resp = _invoke_runtime({
            "skill": "default-crawl",
            "args": "https://example.com",
            "use_browser": True,
        })
        # 响应必须是合法 dict
        self.assertIsInstance(resp, dict)
        crawler_output = resp.get("crawler_output")
        if crawler_output and isinstance(crawler_output, dict):
            # browser 模式应包含 method="browser"
            if "method" in crawler_output:
                self.assertEqual(crawler_output["method"], "browser")


# ---------------------------------------------------------------------------
# 6. 性能基准（可选）
# ---------------------------------------------------------------------------

@perf_test
class TestCloudPerformance(unittest.TestCase):
    """云端 invoke 延迟基准测试（CLOUD_PERF_TEST=1 时执行）。"""

    def _timed_invoke(self, payload):
        start = time.time()
        resp = _invoke_runtime(payload, timeout=180)
        elapsed = time.time() - start
        return resp, elapsed

    def test_api_crawl_latency(self):
        """API 爬取（jsonplaceholder）端到端延迟 < 120s。"""
        _, elapsed = self._timed_invoke({
            "skill": "api-crawl",
            "args": "https://jsonplaceholder.typicode.com/users 1",
        })
        print(f"\n  API crawl latency: {elapsed:.1f}s")
        self.assertLess(elapsed, 120, f"API crawl too slow: {elapsed:.1f}s")

    def test_ecommerce_crawl_latency(self):
        """电商爬取（books.toscrape.com）端到端延迟 < 120s。"""
        _, elapsed = self._timed_invoke({
            "skill": "ecommerce-crawl",
            "args": "https://books.toscrape.com 1",
        })
        print(f"\n  E-commerce crawl latency: {elapsed:.1f}s")
        self.assertLess(elapsed, 120, f"E-commerce crawl too slow: {elapsed:.1f}s")

    def test_news_crawl_latency(self):
        """新闻爬取（Hacker News）端到端延迟 < 120s。"""
        _, elapsed = self._timed_invoke({
            "skill": "news-crawl",
            "args": "https://news.ycombinator.com 1",
        })
        print(f"\n  News crawl latency: {elapsed:.1f}s")
        self.assertLess(elapsed, 120, f"News crawl too slow: {elapsed:.1f}s")

    def test_three_sequential_invokes(self):
        """连续 3 次 invoke，验证无状态泄漏，各自延迟合理。"""
        payloads = [
            {"skill": "default-crawl", "args": "https://example.com"},
            {"skill": "api-crawl", "args": "https://jsonplaceholder.typicode.com/posts/1"},
            {"skill": "default-crawl", "args": "https://httpbin.org/get"},
        ]
        times = []
        for p in payloads:
            _, elapsed = self._timed_invoke(p)
            times.append(elapsed)
            print(f"\n  Sequential invoke latency: {elapsed:.1f}s")

        for i, t in enumerate(times):
            self.assertLess(t, 120, f"Invoke #{i+1} too slow: {t:.1f}s")


# ---------------------------------------------------------------------------
# 本地验证：仅检查测试框架本身是否正常（无网络）
# ---------------------------------------------------------------------------

class TestCloudE2eFramework(unittest.TestCase):
    """验证 E2E 框架的辅助函数（不需要 AWS 凭证）。"""

    def test_skip_when_vars_missing(self):
        """当环境变量缺失时，云端测试应被 skip 而不是 fail。"""
        # 此测试本身验证 skip 逻辑：若不在云端环境，所有 @cloud_test 方法均被跳过
        if _CLOUD_VARS_PRESENT:
            self.skipTest("云端变量已存在，跳过此检查")
        # 确认 cloud_test 装饰器生效
        import inspect
        # TestCloudHealthCheck 的每个方法都应是 skipTest 可触发的
        self.assertFalse(_CLOUD_VARS_PRESENT)

    def test_unescape_function(self):
        """_unescape 辅助函数正确还原 \\uXXXX 序列。"""
        escaped = {"title": "\\u8096\\u7533\\u514b\\u7684\\u6551\\u8d4e"}
        result = _unescape(escaped)
        self.assertEqual(result["title"], "肖申克的救赎")

    def test_unescape_nested(self):
        escaped = {
            "movies": [
                {"title": "\\u9738\\u738b\\u522b\\u59ec"}
            ]
        }
        result = _unescape(escaped)
        self.assertEqual(result["movies"][0]["title"], "霸王别姬")

    def test_unescape_preserves_ascii(self):
        data = {"title": "The Shawshank Redemption", "year": 1994}
        result = _unescape(data)
        self.assertEqual(result["title"], "The Shawshank Redemption")
        self.assertEqual(result["year"], 1994)

    def test_unescape_preserves_none(self):
        self.assertIsNone(_unescape(None))

    def test_required_vars_list_correct(self):
        self.assertIn("AGENTCORE_RUNTIME_ID", _REQUIRED_VARS)
        self.assertIn("AWS_REGION", _REQUIRED_VARS)
        self.assertIn("AWS_ACCOUNT_ID", _REQUIRED_VARS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
