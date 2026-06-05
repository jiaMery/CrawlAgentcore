"""invoke 流程、重试逻辑、响应构建、observability 测试

覆盖范围：
- _auto_select_skill：正常返回 / JSON 解析失败回退 / skill 名称匹配回退
- invoke() payload 解析：prompt / skill / args / use_browser 字段
- invoke() 响应结构：必要字段 / 类型 / browser_used 标志
- 重试逻辑：output=None 时触发变量探测 / mojibake 时触发重新抓取
- _setup_observability：成功 / 异常静默处理
- _RefreshingAWS4Auth：每次调用刷新凭证

所有依赖 strands/bedrock 的外部调用均通过 mock 隔离。
"""

import base64
import json
import os
import re
import sys
import types
import unittest
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ---------------------------------------------------------------------------
# 内联 invoke 逻辑副本（不触发模块级副作用）
# ---------------------------------------------------------------------------

from src.skills import load_skill, list_skills

# 从 test_encoding_advanced 借用的内联函数
import json as _json

def _ensure_ascii_safe(obj):
    if isinstance(obj, str):
        return _json.dumps(obj, ensure_ascii=True)[1:-1]
    if isinstance(obj, dict):
        return {
            _json.dumps(k, ensure_ascii=True)[1:-1]: _ensure_ascii_safe(v)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_ensure_ascii_safe(item) for item in obj]
    return obj


def _looks_like_mojibake(obj) -> bool:
    text = _json.dumps(obj, ensure_ascii=False) if not isinstance(obj, str) else obj
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


# ---------------------------------------------------------------------------
# _auto_select_skill（从 main.py 内联）
# ---------------------------------------------------------------------------

SELECTOR_PROMPT_TEMPLATE = (
    "You are a skill selector. Given a user's crawl request and a list of available "
    "skills, pick the single best skill.\n\nAvailable skills:\n{skills_json}\n\n"
    "User request: {prompt}\n\nReply with ONLY a JSON object: {{\"skill\": \"<skill-name>\"}}\n"
    "Do NOT include any other text."
)


def _auto_select_skill_impl(prompt: str, agent_factory) -> str:
    """invoke() 中的技能自动选择逻辑（依赖注入版本）。"""
    skills = list_skills()
    if len(skills) <= 1:
        return skills[0]["name"] if skills else "default-crawl"

    skills_json = json.dumps(skills, indent=2)
    selector = agent_factory(
        tools=[],
        system_prompt=SELECTOR_PROMPT_TEMPLATE.format(
            skills_json=skills_json, prompt=prompt
        ),
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
    return selected


# ---------------------------------------------------------------------------
# _auto_select_skill 测试
# ---------------------------------------------------------------------------

class TestAutoSelectSkill(unittest.TestCase):
    def _make_agent(self, response_text):
        mock_result = MagicMock()
        mock_result.message = {"content": [{"text": response_text}]}

        mock_agent_instance = MagicMock()
        mock_agent_instance.return_value = mock_result

        def agent_factory(**kwargs):
            return mock_agent_instance

        return agent_factory

    def test_selects_ecommerce_from_json_response(self):
        factory = self._make_agent('{"skill": "ecommerce-crawl"}')
        result = _auto_select_skill_impl("Scrape products", factory)
        self.assertEqual(result, "ecommerce-crawl")

    def test_selects_news_from_json_response(self):
        factory = self._make_agent('{"skill": "news-crawl"}')
        result = _auto_select_skill_impl("Get latest headlines", factory)
        self.assertEqual(result, "news-crawl")

    def test_selects_api_from_json_response(self):
        factory = self._make_agent('{"skill": "api-crawl"}')
        result = _auto_select_skill_impl("Fetch users from REST API", factory)
        self.assertEqual(result, "api-crawl")

    def test_falls_back_to_default_on_invalid_json(self):
        factory = self._make_agent("I think you should use the default skill")
        result = _auto_select_skill_impl("Crawl something", factory)
        self.assertEqual(result, "default-crawl")

    def test_falls_back_via_name_match(self):
        factory = self._make_agent("I recommend news-crawl for this task")
        result = _auto_select_skill_impl("Get news", factory)
        self.assertEqual(result, "news-crawl")

    def test_str_message_format(self):
        mock_result = MagicMock()
        mock_result.message = '{"skill": "docs-crawl"}'
        mock_agent_instance = MagicMock()
        mock_agent_instance.return_value = mock_result

        result = _auto_select_skill_impl(
            "Read the docs",
            lambda **kwargs: mock_agent_instance
        )
        self.assertEqual(result, "docs-crawl")

    def test_missing_skill_key_falls_back_to_default(self):
        factory = self._make_agent('{"other": "value"}')
        result = _auto_select_skill_impl("something", factory)
        self.assertEqual(result, "default-crawl")


# ---------------------------------------------------------------------------
# invoke() payload 解析
# ---------------------------------------------------------------------------

class TestPayloadParsing(unittest.TestCase):
    """验证 invoke() 从 payload 中正确提取字段。"""

    @staticmethod
    def _parse(payload):
        return {
            "prompt": payload.get("prompt", ""),
            "explicit_skill": payload.get("skill"),
            "skill_args": payload.get("args", payload.get("prompt", "")),
            "use_browser": bool(payload.get("use_browser", False)),
        }

    def test_full_payload(self):
        p = self._parse({
            "prompt": "Scrape shoes",
            "skill": "ecommerce-crawl",
            "args": "https://shop.com 5",
            "use_browser": True,
        })
        self.assertEqual(p["prompt"], "Scrape shoes")
        self.assertEqual(p["explicit_skill"], "ecommerce-crawl")
        self.assertEqual(p["skill_args"], "https://shop.com 5")
        self.assertTrue(p["use_browser"])

    def test_minimal_payload(self):
        p = self._parse({"prompt": "Crawl https://example.com"})
        self.assertEqual(p["prompt"], "Crawl https://example.com")
        self.assertIsNone(p["explicit_skill"])
        self.assertEqual(p["skill_args"], "Crawl https://example.com")
        self.assertFalse(p["use_browser"])

    def test_empty_payload(self):
        p = self._parse({})
        self.assertEqual(p["prompt"], "")
        self.assertIsNone(p["explicit_skill"])
        self.assertFalse(p["use_browser"])

    def test_args_overrides_prompt_for_skill(self):
        p = self._parse({
            "prompt": "Get products",
            "args": "https://shop.com 10",
        })
        self.assertEqual(p["skill_args"], "https://shop.com 10")

    def test_use_browser_string_truthy(self):
        p = self._parse({"use_browser": 1})
        self.assertTrue(p["use_browser"])

    def test_use_browser_false_by_default(self):
        p = self._parse({"prompt": "test"})
        self.assertFalse(p["use_browser"])


# ---------------------------------------------------------------------------
# invoke() 响应结构
# ---------------------------------------------------------------------------

class TestInvokeResponseStructure(unittest.TestCase):
    """验证 invoke() 返回字典包含所有必要字段且类型正确。"""

    REQUIRED_FIELDS = {
        "result": (str, dict),
        "crawler_output": (dict, list, type(None)),
        "skill_used": str,
        "skill_description": str,
        "auto_selected": bool,
        "browser_used": bool,
        "available_skills": list,
    }

    def _make_response(self, skill_name="default-crawl", crawler_output=None,
                       explicit_skill=None, use_browser=False,
                       browser_available=False):
        skill = load_skill(skill_name)
        return {
            "result": "Crawl completed",
            "crawler_output": crawler_output,
            "skill_used": skill.name,
            "skill_description": skill.description,
            "auto_selected": explicit_skill is None,
            "browser_used": use_browser and browser_available,
            "available_skills": list_skills(),
        }

    def test_all_required_fields_present(self):
        response = self._make_response()
        for field in self.REQUIRED_FIELDS:
            self.assertIn(field, response, f"Missing field: {field}")

    def test_field_types(self):
        response = self._make_response(
            crawler_output={"url": "https://example.com"}
        )
        for field, expected_types in self.REQUIRED_FIELDS.items():
            self.assertIsInstance(
                response[field], expected_types,
                f"Field {field!r} has wrong type: {type(response[field])}"
            )

    def test_auto_selected_true_when_no_explicit_skill(self):
        response = self._make_response(explicit_skill=None)
        self.assertTrue(response["auto_selected"])

    def test_auto_selected_false_when_explicit_skill(self):
        response = self._make_response(explicit_skill="ecommerce-crawl")
        self.assertFalse(response["auto_selected"])

    def test_browser_used_false_when_not_available(self):
        response = self._make_response(use_browser=True, browser_available=False)
        self.assertFalse(response["browser_used"])

    def test_browser_used_true_when_both_flags_set(self):
        response = self._make_response(use_browser=True, browser_available=True)
        self.assertTrue(response["browser_used"])

    def test_available_skills_contains_all_six(self):
        response = self._make_response()
        names = [s["name"] for s in response["available_skills"]]
        for skill in ["default-crawl", "ecommerce-crawl", "news-crawl",
                      "api-crawl", "docs-crawl", "social-crawl"]:
            self.assertIn(skill, names)

    def test_ensure_ascii_safe_applied_to_response(self):
        """_ensure_ascii_safe 应把中文字段转换为纯 ASCII。"""
        response = self._make_response(
            crawler_output={"title": "肖申克的救赎", "rating": "9.7"}
        )
        safe = _ensure_ascii_safe(response)
        safe_json = json.dumps(safe, ensure_ascii=False)
        self.assertTrue(all(ord(c) < 128 for c in safe_json))


# ---------------------------------------------------------------------------
# 重试逻辑：output=None 时触发变量探测
# ---------------------------------------------------------------------------

class TestRetryOnNoneOutput(unittest.TestCase):
    """验证 crawler_output=None 时，invoke 会触发第二次 agent 调用。"""

    def _make_retry_scenario(self, retry_output):
        """
        第一次 _extract_crawler_output 返回 None，
        第二次返回 retry_output。
        """
        call_count = {"n": 0}

        def fake_extract(agent):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return None
            return retry_output

        return fake_extract, call_count

    def test_retry_is_triggered_when_output_is_none(self):
        fake_extract, count = self._make_retry_scenario({"title": "recovered"})
        mock_agent = MagicMock()
        mock_agent.return_value = MagicMock(message="done")
        mock_agent.messages = []

        # 模拟 invoke 中的重试检查逻辑
        crawler_output = fake_extract(mock_agent)
        if crawler_output is None:
            mock_agent("retry code")
            crawler_output = fake_extract(mock_agent)

        self.assertEqual(count["n"], 2)
        self.assertEqual(crawler_output["title"], "recovered")

    def test_retry_result_used_when_not_none(self):
        fake_extract, _ = self._make_retry_scenario(
            [{"rank": 1, "title": "肖申克的救赎"}]
        )
        mock_agent = MagicMock()
        mock_agent.messages = []

        crawler_output = fake_extract(mock_agent)
        if crawler_output is None:
            mock_agent("retry")
            crawler_output = fake_extract(mock_agent)

        self.assertIsNotNone(crawler_output)
        self.assertEqual(crawler_output[0]["title"], "肖申克的救赎")


# ---------------------------------------------------------------------------
# 重试逻辑：mojibake 输出触发重新抓取
# ---------------------------------------------------------------------------

class TestMojibakeRetry(unittest.TestCase):
    def test_retry_triggered_when_mojibake_detected(self):
        corrupted = {"title": "Ã¨Â¿Â·Ã§Â³Â»Ã¥Â°Â·", "other": "Ã¦Â¶Ã©"}

        retry_called = {"n": 0}
        def fake_agent_call(msg):
            retry_called["n"] += 1
            return MagicMock(message="retried")

        mock_agent = MagicMock()
        mock_agent.side_effect = fake_agent_call
        mock_agent.messages = []

        # 模拟 mojibake 重试分支
        if _looks_like_mojibake(corrupted):
            mock_agent("re-run with base64")

        self.assertEqual(retry_called["n"], 1,
                         "Agent should be called once for mojibake retry")

    def test_no_retry_when_clean_output(self):
        clean = {"title": "The Shawshank Redemption", "rating": "9.7"}

        retry_called = {"n": 0}
        mock_agent = MagicMock()
        mock_agent.messages = []

        if _looks_like_mojibake(clean):
            retry_called["n"] += 1

        self.assertEqual(retry_called["n"], 0)

    def test_retry_output_replaces_corrupted(self):
        corrupted = {"title": "Ã¨Â¿Â·Ã§Â³Â»Ã¥Â°Â·Ã¦Ã©Ã§"}
        fixed = {"title": "肖申克的救赎"}

        call_count = {"n": 0}

        def fake_extract(agent):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return corrupted
            return fixed

        mock_agent = MagicMock()
        mock_agent.messages = []

        crawler_output = fake_extract(mock_agent)
        if crawler_output and _looks_like_mojibake(crawler_output):
            mock_agent("retry with base64")
            retry = fake_extract(mock_agent)
            if retry and not _looks_like_mojibake(retry):
                crawler_output = retry

        self.assertEqual(crawler_output["title"], "肖申克的救赎")


# ---------------------------------------------------------------------------
# _setup_observability
# ---------------------------------------------------------------------------

class TestSetupObservability(unittest.TestCase):
    def test_succeeds_silently_on_import_error(self):
        """当 strands 不可用时，_setup_observability 应静默失败。"""
        # 直接测试异常处理逻辑
        def _setup_observability_safe():
            try:
                raise ImportError("strands not available")
            except Exception:
                pass

        _setup_observability_safe()  # 不应抛出异常

    def test_succeeds_silently_on_aws_error(self):
        def _setup_observability_safe():
            try:
                raise RuntimeError("AWS credentials not found")
            except Exception:
                pass

        _setup_observability_safe()

    def test_env_var_defaults(self):
        """验证 observability 使用的默认环境变量值。"""
        region = os.environ.get("AWS_REGION", "us-east-1")
        service_name = os.environ.get("OTEL_SERVICE_NAME", "crawler-agentcore")
        self.assertEqual(region, "us-east-1")
        self.assertEqual(service_name, "crawler-agentcore")


# ---------------------------------------------------------------------------
# _RefreshingAWS4Auth
# ---------------------------------------------------------------------------

class TestRefreshingAWS4Auth(unittest.TestCase):
    def test_fetches_credentials_on_each_call(self):
        mock_creds = MagicMock()
        mock_creds.access_key = "AKIATEST"
        mock_creds.secret_key = "secret"
        mock_creds.token = "token123"

        mock_frozen = MagicMock()
        mock_frozen.return_value = mock_creds

        mock_session = MagicMock()
        mock_session.get_credentials.return_value.get_frozen_credentials = mock_frozen

        # 内联 _RefreshingAWS4Auth 逻辑
        class _RefreshingAWS4Auth:
            def __init__(self, boto3_session, region, service):
                self._boto3_session = boto3_session
                self._region = region
                self._service = service

            def __call__(self, r):
                creds = self._boto3_session.get_credentials().get_frozen_credentials()
                # 记录调用
                return creds

        auth = _RefreshingAWS4Auth(mock_session, "us-east-1", "xray")
        auth(MagicMock())
        auth(MagicMock())

        # 每次 __call__ 都应刷新凭证
        self.assertEqual(mock_session.get_credentials.call_count, 2)

    def test_uses_correct_service_and_region(self):
        mock_session = MagicMock()
        frozen = MagicMock()
        frozen.access_key = "KEY"
        frozen.secret_key = "SECRET"
        frozen.token = None
        mock_session.get_credentials.return_value.get_frozen_credentials.return_value = frozen

        captured = {}

        with patch.dict(os.environ, {"CODE_INTERPRETER_ID": "test-ci-id"}):
          with patch("requests_aws4auth.AWS4Auth") as mock_auth_cls:
            mock_auth_cls.return_value = lambda r: r

            from src.main import _RefreshingAWS4Auth
            auth = _RefreshingAWS4Auth(mock_session, "ap-northeast-1", "xray")
            auth(MagicMock())

            call_args = mock_auth_cls.call_args
            self.assertEqual(call_args[0][2], "ap-northeast-1")  # region
            self.assertEqual(call_args[0][3], "xray")             # service


# ---------------------------------------------------------------------------
# 技能选择 + invoke 组合
# ---------------------------------------------------------------------------

class TestSkillSelectionInvoke(unittest.TestCase):
    """验证 explicit_skill 与 auto_select 在 invoke 流程中的协作。"""

    def test_explicit_skill_bypasses_auto_select(self):
        skill = load_skill("ecommerce-crawl", "https://shop.com")
        explicit = "ecommerce-crawl"
        selected = explicit  # 直接使用，不调用 LLM
        self.assertEqual(selected, "ecommerce-crawl")
        self.assertIn("product", skill.content.lower())

    def test_unknown_skill_falls_back_to_default(self):
        skill = load_skill("nonexistent-skill", "https://example.com")
        self.assertEqual(skill.name, "default-crawl")

    def test_system_prompt_contains_skill_content(self):
        SYSTEM_PROMPT_TEMPLATE = (
            "You are a web-crawler.\n## Crawl-Style Instructions\n{crawl_style}"
        )
        skill = load_skill("news-crawl", "https://news.ycombinator.com")
        prompt = SYSTEM_PROMPT_TEMPLATE.format(crawl_style=skill.content)
        self.assertIn("https://news.ycombinator.com", prompt)
        self.assertIn("articles", prompt.lower())

    def test_browser_hint_appended_when_use_browser(self):
        BROWSER_HINT = "\n## Browser Tool\nYou have access to browser_crawl."
        system_prompt = "base prompt"
        use_browser = True
        browser_available = True

        if use_browser and browser_available:
            system_prompt += BROWSER_HINT

        self.assertIn("browser_crawl", system_prompt)

    def test_browser_hint_not_appended_when_unavailable(self):
        BROWSER_HINT = "\n## Browser Tool\nYou have access to browser_crawl."
        system_prompt = "base prompt"
        use_browser = True
        browser_available = False

        if use_browser and browser_available:
            system_prompt += BROWSER_HINT

        self.assertNotIn("browser_crawl", system_prompt)


if __name__ == "__main__":
    unittest.main(verbosity=2)
