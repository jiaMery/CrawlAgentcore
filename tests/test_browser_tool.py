"""browser_tool.py 完整单元测试（mock boto3，无需真实 AWS 资源）

覆盖范围：
- 会话生命周期（启动 / 停止）
- automation stream 状态轮询
- CDP JS 注入（Runtime.evaluate）
- 截图 base64 编码
- 导航流程
- _browser_crawl_impl 正常路径 + 错误路径
- browser_crawl Strands tool 包装器
- BROWSER_ID / REGION 环境变量读取
"""

import base64
import json
import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# 通用 boto3 mock 工厂
# ---------------------------------------------------------------------------

def _make_boto3_client_mock(
    session_id="session-abc123",
    stream_endpoint="wss://automation.example.com/cdp",
    screenshot_bytes=b"\x89PNG\r\n",
):
    """构造一个覆盖 browser_tool 所有 boto3 调用的 mock 客户端。"""
    mock_client = MagicMock()

    mock_client.start_browser_session.return_value = {"sessionId": session_id}

    mock_client.update_browser_stream.return_value = {
        "streams": {
            "automationStream": {
                "streamEndpoint": stream_endpoint,
                "streamStatus": "ENABLED",
            }
        }
    }

    mock_client.get_browser_session.return_value = {
        "streams": {
            "automationStream": {
                "streamEndpoint": stream_endpoint,
                "streamStatus": "ENABLED",
            }
        }
    }

    mock_client.invoke_browser.return_value = {
        "result": {
            "screenshot": {"data": screenshot_bytes}
        }
    }

    mock_client.stop_browser_session.return_value = {}
    return mock_client


# ---------------------------------------------------------------------------
# _rt_client
# ---------------------------------------------------------------------------

class TestRtClient(unittest.TestCase):
    """_rt_client() 每次调用都创建一个新的 boto3 客户端。"""

    @patch("boto3.client")
    def test_returns_boto3_client(self, mock_boto3_client):
        from src.browser_tool import _rt_client
        client = _rt_client()
        mock_boto3_client.assert_called_once()
        self.assertIsNotNone(client)

    @patch("boto3.client")
    def test_uses_configured_region(self, mock_boto3_client):
        with patch.dict(os.environ, {"AWS_REGION": "ap-northeast-1"}):
            # 重新导入以获取新的 REGION 值
            import importlib
            import src.browser_tool as bt
            importlib.reload(bt)
            bt._rt_client()
            mock_boto3_client.assert_called_with(
                "bedrock-agentcore", region_name="ap-northeast-1"
            )


# ---------------------------------------------------------------------------
# _start_session
# ---------------------------------------------------------------------------

class TestStartSession(unittest.TestCase):
    def test_returns_session_id(self):
        from src.browser_tool import _start_session
        mock_client = _make_boto3_client_mock(session_id="sess-001")
        result = _start_session(mock_client, "browser-123")
        self.assertEqual(result, "sess-001")

    def test_passes_correct_browser_id(self):
        from src.browser_tool import _start_session
        mock_client = _make_boto3_client_mock()
        _start_session(mock_client, "browser-XYZ")
        call_kwargs = mock_client.start_browser_session.call_args[1]
        self.assertEqual(call_kwargs["browserIdentifier"], "browser-XYZ")

    def test_sets_viewport(self):
        from src.browser_tool import _start_session
        mock_client = _make_boto3_client_mock()
        _start_session(mock_client, "browser-XYZ")
        call_kwargs = mock_client.start_browser_session.call_args[1]
        self.assertIn("viewPort", call_kwargs)
        self.assertEqual(call_kwargs["viewPort"]["width"], 1280)
        self.assertEqual(call_kwargs["viewPort"]["height"], 900)

    def test_session_name_is_unique(self):
        """每次调用生成不同的 session name（含 uuid）。"""
        from src.browser_tool import _start_session
        mock_client = _make_boto3_client_mock()
        _start_session(mock_client, "b-1")
        _start_session(mock_client, "b-1")
        calls = mock_client.start_browser_session.call_args_list
        name1 = calls[0][1]["name"]
        name2 = calls[1][1]["name"]
        self.assertNotEqual(name1, name2)


# ---------------------------------------------------------------------------
# _enable_automation_stream
# ---------------------------------------------------------------------------

class TestEnableAutomationStream(unittest.TestCase):
    def test_returns_stream_endpoint(self):
        from src.browser_tool import _enable_automation_stream
        mock_client = _make_boto3_client_mock(stream_endpoint="wss://ep.example.com")
        ep = _enable_automation_stream(mock_client, "browser-1", "sess-1")
        self.assertEqual(ep, "wss://ep.example.com")

    def test_sends_enabled_status(self):
        from src.browser_tool import _enable_automation_stream
        mock_client = _make_boto3_client_mock()
        _enable_automation_stream(mock_client, "browser-1", "sess-1")
        call_kwargs = mock_client.update_browser_stream.call_args[1]
        stream_update = call_kwargs["streamUpdate"]
        status = stream_update["automationStreamUpdate"]["streamStatus"]
        self.assertEqual(status, "ENABLED")


# ---------------------------------------------------------------------------
# _wait_stream_ready
# ---------------------------------------------------------------------------

class TestWaitStreamReady(unittest.TestCase):
    def test_returns_immediately_when_enabled(self):
        from src.browser_tool import _wait_stream_ready
        mock_client = _make_boto3_client_mock(stream_endpoint="wss://ready.example.com")
        ep = _wait_stream_ready(mock_client, "b-1", "s-1", retries=3)
        self.assertEqual(ep, "wss://ready.example.com")
        mock_client.get_browser_session.assert_called_once()

    def test_raises_after_retries_exhausted(self):
        from src.browser_tool import _wait_stream_ready
        mock_client = MagicMock()
        mock_client.get_browser_session.return_value = {
            "streams": {"automationStream": {"streamStatus": "PENDING"}}
        }
        with self.assertRaises(RuntimeError):
            _wait_stream_ready(mock_client, "b-1", "s-1", retries=2)

    def test_polls_until_enabled(self):
        """前两次返回 PENDING，第三次返回 ENABLED。"""
        from src.browser_tool import _wait_stream_ready
        mock_client = MagicMock()
        mock_client.get_browser_session.side_effect = [
            {"streams": {"automationStream": {"streamStatus": "PENDING"}}},
            {"streams": {"automationStream": {"streamStatus": "PENDING"}}},
            {"streams": {"automationStream": {
                "streamStatus": "ENABLED",
                "streamEndpoint": "wss://now-ready.example.com",
            }}},
        ]
        ep = _wait_stream_ready(mock_client, "b-1", "s-1", retries=5)
        self.assertEqual(ep, "wss://now-ready.example.com")
        self.assertEqual(mock_client.get_browser_session.call_count, 3)


# ---------------------------------------------------------------------------
# _screenshot_b64
# ---------------------------------------------------------------------------

class TestScreenshotB64(unittest.TestCase):
    def test_returns_base64_string(self):
        from src.browser_tool import _screenshot_b64
        png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
        mock_client = _make_boto3_client_mock(screenshot_bytes=png_bytes)
        result = _screenshot_b64(mock_client, "b-1", "s-1")
        self.assertIsInstance(result, str)
        decoded = base64.b64decode(result)
        self.assertEqual(decoded[:8], b"\x89PNG\r\n\x1a\n")

    def test_empty_when_no_screenshot_data(self):
        from src.browser_tool import _screenshot_b64
        mock_client = MagicMock()
        mock_client.invoke_browser.return_value = {"result": {}}
        result = _screenshot_b64(mock_client, "b-1", "s-1")
        self.assertEqual(result, "")

    def test_handles_bytes_from_api(self):
        """invoke_browser 可能返回 bytes 或 bytearray。"""
        from src.browser_tool import _screenshot_b64
        mock_client = MagicMock()
        for data_type in [b"PNG_DATA", bytearray(b"PNG_DATA")]:
            mock_client.invoke_browser.return_value = {
                "result": {"screenshot": {"data": data_type}}
            }
            result = _screenshot_b64(mock_client, "b-1", "s-1")
            self.assertIsInstance(result, str)
            self.assertGreater(len(result), 0)


# ---------------------------------------------------------------------------
# _cdp_eval
# ---------------------------------------------------------------------------

class TestCdpEval(unittest.TestCase):
    """_cdp_eval 在函数内部 lazy-import websocket，通过 sys.modules 注入 mock。"""

    def _patch_websocket(self, mock_ws=None, side_effect=None):
        """返回一个 sys.modules['websocket'] 的 MagicMock patch context。"""
        mock_module = MagicMock()
        if side_effect:
            mock_module.create_connection.side_effect = side_effect
        elif mock_ws:
            mock_module.create_connection.return_value = mock_ws
        return patch.dict(sys.modules, {"websocket": mock_module}), mock_module

    def test_returns_value_from_cdp_response(self):
        from src.browser_tool import _cdp_eval

        mock_ws = MagicMock()
        mock_ws.recv.return_value = json.dumps({
            "id": 1,
            "result": {"result": {"value": "My Page Title"}},
        })

        ctx, _ = self._patch_websocket(mock_ws=mock_ws)
        with ctx:
            result = _cdp_eval("wss://endpoint.example.com", "document.title")
        self.assertEqual(result, "My Page Title")

    def test_returns_empty_string_on_error(self):
        from src.browser_tool import _cdp_eval
        ctx, _ = self._patch_websocket(side_effect=ConnectionRefusedError)
        with ctx:
            result = _cdp_eval("wss://bad-endpoint.example.com", "document.title")
        self.assertEqual(result, "")

    def test_handles_timeout_gracefully(self):
        from src.browser_tool import _cdp_eval
        mock_ws = MagicMock()
        # recv 永远返回不匹配的 id
        mock_ws.recv.return_value = json.dumps({
            "id": 99,
            "result": {"result": {"value": "wrong"}},
        })
        ctx, _ = self._patch_websocket(mock_ws=mock_ws)
        with ctx:
            with patch("src.browser_tool.time") as mock_time:
                mock_time.time.side_effect = [0.0, 100.0]
                result = _cdp_eval("wss://endpoint.example.com", "document.title", timeout=1)
        self.assertEqual(result, "")


# ---------------------------------------------------------------------------
# _navigate
# ---------------------------------------------------------------------------

class TestNavigate(unittest.TestCase):
    def test_sends_keyboard_actions(self):
        from src.browser_tool import _navigate
        mock_client = MagicMock()
        mock_client.invoke_browser.return_value = {"result": {}}

        with patch("src.browser_tool.time"):
            _navigate(mock_client, "b-1", "s-1", "https://example.com")

        # 验证键盘操作序列
        calls = mock_client.invoke_browser.call_args_list
        actions = [c[1]["action"] for c in calls]

        # 第1步：Ctrl+L（聚焦地址栏）
        self.assertIn("keyShortcut", actions[0])
        self.assertIn("l", actions[0]["keyShortcut"]["keys"])

        # 第3步：keyType（输入 URL）
        key_type_actions = [a for a in actions if "keyType" in a]
        self.assertTrue(any("https://example.com" in a["keyType"]["text"]
                            for a in key_type_actions))

        # 最后：Enter
        key_press_actions = [a for a in actions if "keyPress" in a]
        self.assertTrue(any(a["keyPress"]["key"] == "Return"
                            for a in key_press_actions))


# ---------------------------------------------------------------------------
# _stop_session
# ---------------------------------------------------------------------------

class TestStopSession(unittest.TestCase):
    def test_calls_stop_browser_session(self):
        from src.browser_tool import _stop_session
        mock_client = MagicMock()
        _stop_session(mock_client, "b-1", "s-1")
        mock_client.stop_browser_session.assert_called_once_with(
            browserIdentifier="b-1", sessionId="s-1"
        )

    def test_swallows_exceptions(self):
        from src.browser_tool import _stop_session
        mock_client = MagicMock()
        mock_client.stop_browser_session.side_effect = RuntimeError("network error")
        # 不应该抛出异常
        _stop_session(mock_client, "b-1", "s-1")


# ---------------------------------------------------------------------------
# _browser_crawl_impl — happy path
# ---------------------------------------------------------------------------

class TestBrowserCrawlImpl(unittest.TestCase):
    def _make_full_mock(self):
        """构造 _browser_crawl_impl 完整正常路径所需的所有 mock。"""
        mock_client = _make_boto3_client_mock(
            session_id="test-sess",
            stream_endpoint="wss://cdp.example.com",
            screenshot_bytes=b"\x89PNG",
        )

        cdp_responses = {
            "document.title": "Test Page Title",
            "document.body ? document.body.innerText.slice(0, 50000) : ''":
                "Main page content here",
        }

        def fake_cdp_eval(endpoint, js_expression, timeout=10):
            for key, val in cdp_responses.items():
                if key in js_expression:
                    return val
            # links 表达式
            if "querySelectorAll" in js_expression:
                return json.dumps([
                    {"text": "Click here", "href": "https://example.com/page"}
                ])
            return ""

        return mock_client, fake_cdp_eval

    @patch("src.browser_tool.time")
    def test_returns_all_expected_keys(self, mock_time):
        from src.browser_tool import _browser_crawl_impl
        mock_client, fake_cdp_eval = self._make_full_mock()

        with patch("src.browser_tool._rt_client", return_value=mock_client):
            with patch("src.browser_tool._cdp_eval", side_effect=fake_cdp_eval):
                result = _browser_crawl_impl("https://example.com", wait_seconds=0.0)

        for key in ("url", "title", "text_content", "links", "screenshot_b64", "method"):
            self.assertIn(key, result, f"Missing key: {key}")

    @patch("src.browser_tool.time")
    def test_url_preserved_in_result(self, mock_time):
        from src.browser_tool import _browser_crawl_impl
        mock_client, fake_cdp_eval = self._make_full_mock()

        with patch("src.browser_tool._rt_client", return_value=mock_client):
            with patch("src.browser_tool._cdp_eval", side_effect=fake_cdp_eval):
                result = _browser_crawl_impl("https://specific.example.com/path")

        self.assertEqual(result["url"], "https://specific.example.com/path")

    @patch("src.browser_tool.time")
    def test_method_is_browser(self, mock_time):
        from src.browser_tool import _browser_crawl_impl
        mock_client, fake_cdp_eval = self._make_full_mock()

        with patch("src.browser_tool._rt_client", return_value=mock_client):
            with patch("src.browser_tool._cdp_eval", side_effect=fake_cdp_eval):
                result = _browser_crawl_impl("https://example.com")

        self.assertEqual(result["method"], "browser")

    @patch("src.browser_tool.time")
    def test_session_always_stopped(self, mock_time):
        """即使中间抛出异常，stop_browser_session 也必须被调用。"""
        from src.browser_tool import _browser_crawl_impl
        mock_client = _make_boto3_client_mock()
        # 导航时抛出异常
        mock_client.invoke_browser.side_effect = RuntimeError("network error")

        with patch("src.browser_tool._rt_client", return_value=mock_client):
            result = _browser_crawl_impl("https://example.com")

        mock_client.stop_browser_session.assert_called_once()
        self.assertIn("error", result)

    @patch("src.browser_tool.time")
    def test_error_result_structure(self, mock_time):
        from src.browser_tool import _browser_crawl_impl
        mock_client = MagicMock()
        mock_client.start_browser_session.side_effect = RuntimeError("AccessDenied")

        with patch("src.browser_tool._rt_client", return_value=mock_client):
            result = _browser_crawl_impl("https://example.com")

        self.assertEqual(result["url"], "https://example.com")
        self.assertEqual(result["method"], "browser")
        self.assertIn("error", result)
        self.assertIn("AccessDenied", result["error"])

    @patch("src.browser_tool.time")
    def test_links_parsed_from_cdp(self, mock_time):
        from src.browser_tool import _browser_crawl_impl
        mock_client = _make_boto3_client_mock()

        expected_links = [
            {"text": "Home", "href": "https://example.com/"},
            {"text": "About", "href": "https://example.com/about"},
        ]

        def fake_cdp(endpoint, js, timeout=10):
            if "querySelectorAll" in js:
                return json.dumps(expected_links)
            return "test-title" if "title" in js else "content text"

        with patch("src.browser_tool._rt_client", return_value=mock_client):
            with patch("src.browser_tool._cdp_eval", side_effect=fake_cdp):
                result = _browser_crawl_impl("https://example.com")

        self.assertEqual(result["links"], expected_links)

    @patch("src.browser_tool.time")
    def test_invalid_links_json_falls_back_to_empty(self, mock_time):
        from src.browser_tool import _browser_crawl_impl
        mock_client = _make_boto3_client_mock()

        def fake_cdp(endpoint, js, timeout=10):
            if "querySelectorAll" in js:
                return "NOT_VALID_JSON{{{}"
            return ""

        with patch("src.browser_tool._rt_client", return_value=mock_client):
            with patch("src.browser_tool._cdp_eval", side_effect=fake_cdp):
                result = _browser_crawl_impl("https://example.com")

        self.assertEqual(result["links"], [])


# ---------------------------------------------------------------------------
# browser_crawl Strands tool wrapper
# ---------------------------------------------------------------------------

class TestBrowserCrawlTool(unittest.TestCase):
    @patch("src.browser_tool.time")
    def test_returns_json_string(self, mock_time):
        from src.browser_tool import browser_crawl

        mock_client = _make_boto3_client_mock()

        with patch("src.browser_tool._rt_client", return_value=mock_client):
            with patch("src.browser_tool._cdp_eval", return_value=""):
                raw = browser_crawl(url="https://example.com", wait_seconds=0.0)

        self.assertIsInstance(raw, str)
        parsed = json.loads(raw)
        self.assertIn("url", parsed)
        self.assertIn("method", parsed)

    @patch("src.browser_tool.time")
    def test_json_string_is_parseable(self, mock_time):
        from src.browser_tool import browser_crawl
        mock_client = _make_boto3_client_mock()

        with patch("src.browser_tool._rt_client", return_value=mock_client):
            with patch("src.browser_tool._cdp_eval", return_value=""):
                raw = browser_crawl(url="https://test.example.com")

        data = json.loads(raw)
        self.assertEqual(data["url"], "https://test.example.com")


# ---------------------------------------------------------------------------
# 环境变量读取
# ---------------------------------------------------------------------------

class TestEnvironmentVariables(unittest.TestCase):
    def test_browser_id_from_env(self):
        import importlib
        with patch.dict(os.environ, {"BROWSER_ID": "custom-browser-999"}):
            import src.browser_tool as bt
            importlib.reload(bt)
            self.assertEqual(bt.BROWSER_ID, "custom-browser-999")

    def test_region_from_env(self):
        import importlib
        with patch.dict(os.environ, {"AWS_REGION": "eu-west-1"}):
            import src.browser_tool as bt
            importlib.reload(bt)
            self.assertEqual(bt.REGION, "eu-west-1")


if __name__ == "__main__":
    unittest.main(verbosity=2)
