"""CloudFormation Custom Resource Handler 完整单元测试（mock boto3 + 无网络）

覆盖范围：
- cfn_send：HTTP PUT 回调格式
- wait_status：READY / FAILED / 超时
- create_code_interpreter / delete_code_interpreter
- create_browser / delete_browser
- create_agent_runtime / delete_agent_runtime（含 endpoint 清理）
- create_agent_runtime_endpoint / delete_agent_runtime_endpoint
- setup_xray_cloudwatch（X-Ray → CloudWatch 轮询）
- create_cw_resource_policy / delete_cw_resource_policy
- handler 分发：Create / Update / Delete / 未知资源类型
"""

import json
import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# deploy/ 目录不在 sys.path，手动添加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "deploy"))


# ---------------------------------------------------------------------------
# boto3 mock 辅助
# ---------------------------------------------------------------------------

def _make_control_client(
    ci_id="ci-001",
    ci_arn="arn:aws:bedrock-agentcore:us-east-1:123:code-interpreter/ci-001",
    browser_id="br-001",
    browser_arn="arn:aws:bedrock-agentcore:us-east-1:123:browser/br-001",
    rt_id="rt-001",
    rt_arn="arn:aws:bedrock-agentcore:us-east-1:123:runtime/rt-001",
    ep_arn="arn:aws:bedrock-agentcore:us-east-1:123:endpoint/ep-001",
):
    mock = MagicMock()

    mock.create_code_interpreter.return_value = {
        "codeInterpreterId": ci_id,
        "codeInterpreterArn": ci_arn,
    }
    mock.get_code_interpreter.return_value = {"status": "READY"}

    mock.create_browser.return_value = {
        "browserId": browser_id,
        "browserArn": browser_arn,
    }
    mock.get_browser.return_value = {"status": "READY"}

    mock.create_agent_runtime.return_value = {
        "agentRuntimeId": rt_id,
        "agentRuntimeArn": rt_arn,
    }
    mock.get_agent_runtime.return_value = {"status": "READY"}

    mock.list_agent_runtime_endpoints.return_value = {"agentRuntimeEndpoints": []}

    mock.create_agent_runtime_endpoint.return_value = {
        "agentRuntimeEndpointArn": ep_arn,
    }
    mock.get_agent_runtime_endpoint.return_value = {"status": "READY"}

    # exceptions namespace
    mock.exceptions.ResourceNotFoundException = type(
        "ResourceNotFoundException", (Exception,), {}
    )
    return mock


def _make_cfn_event(request_type, resource_type, props=None, physical_id=None):
    return {
        "RequestType": request_type,
        "ResponseURL": "https://cfn.example.com/response",
        "StackId": "arn:aws:cloudformation:us-east-1:123:stack/test/abc",
        "RequestId": "req-001",
        "LogicalResourceId": "TestResource",
        "PhysicalResourceId": physical_id or "",
        "Properties": {"ResourceType": resource_type, **(props or {})},
    }


# ---------------------------------------------------------------------------
# cfn_send
# ---------------------------------------------------------------------------

class TestCfnSend(unittest.TestCase):
    def test_puts_success_status(self):
        import cfn_handler
        with patch("urllib.request.urlopen") as mock_urlopen:
            cfn_handler.cfn_send(
                _make_cfn_event("Create", "CodeInterpreter"),
                "SUCCESS",
                data={"PhysicalResourceId": "ci-001"},
            )
        mock_urlopen.assert_called_once()
        req = mock_urlopen.call_args[0][0]
        body = json.loads(req.data.decode())
        self.assertEqual(body["Status"], "SUCCESS")
        self.assertEqual(body["PhysicalResourceId"], "ci-001")

    def test_puts_failed_status_with_reason(self):
        import cfn_handler
        with patch("urllib.request.urlopen") as mock_urlopen:
            cfn_handler.cfn_send(
                _make_cfn_event("Create", "CodeInterpreter"),
                "FAILED",
                reason="Something went wrong",
            )
        body = json.loads(mock_urlopen.call_args[0][0].data.decode())
        self.assertEqual(body["Status"], "FAILED")
        self.assertEqual(body["Reason"], "Something went wrong")

    def test_includes_stack_and_request_ids(self):
        import cfn_handler
        with patch("urllib.request.urlopen") as mock_urlopen:
            cfn_handler.cfn_send(
                _make_cfn_event("Create", "CodeInterpreter"),
                "SUCCESS",
                data={"PhysicalResourceId": "x"},
            )
        body = json.loads(mock_urlopen.call_args[0][0].data.decode())
        self.assertEqual(body["StackId"],
                         "arn:aws:cloudformation:us-east-1:123:stack/test/abc")
        self.assertEqual(body["RequestId"], "req-001")
        self.assertEqual(body["LogicalResourceId"], "TestResource")


# ---------------------------------------------------------------------------
# wait_status
# ---------------------------------------------------------------------------

class TestWaitStatus(unittest.TestCase):
    def test_returns_immediately_when_ready(self):
        import cfn_handler
        mock_client = MagicMock()
        mock_client.get_resource.return_value = {"status": "READY", "data": "ok"}
        result = cfn_handler.wait_status(
            mock_client.get_resource, "id", "res-001",
            ready="READY", fail="FAILED", max_wait=60, interval=1
        )
        self.assertEqual(result["status"], "READY")

    def test_raises_on_failed_status(self):
        import cfn_handler
        mock_client = MagicMock()
        mock_client.get_resource.return_value = {
            "status": "FAILED", "failureReason": "disk full"
        }
        with self.assertRaises(RuntimeError) as ctx:
            cfn_handler.wait_status(
                mock_client.get_resource, "id", "res-001",
                ready="READY", fail="FAILED", max_wait=60, interval=1
            )
        self.assertIn("disk full", str(ctx.exception))

    def test_raises_timeout_when_never_ready(self):
        import cfn_handler
        mock_client = MagicMock()
        mock_client.get_resource.return_value = {"status": "CREATING"}
        with patch("cfn_handler.time"):
            with self.assertRaises(TimeoutError):
                cfn_handler.wait_status(
                    mock_client.get_resource, "id", "res-001",
                    ready="READY", fail="FAILED", max_wait=30, interval=15
                )

    def test_polls_multiple_times_before_ready(self):
        import cfn_handler
        mock_client = MagicMock()
        mock_client.get_resource.side_effect = [
            {"status": "CREATING"},
            {"status": "CREATING"},
            {"status": "READY"},
        ]
        with patch("cfn_handler.time"):
            cfn_handler.wait_status(
                mock_client.get_resource, "id", "res-001",
                ready="READY", fail="FAILED", max_wait=60, interval=15
            )
        self.assertEqual(mock_client.get_resource.call_count, 3)


# ---------------------------------------------------------------------------
# create_code_interpreter
# ---------------------------------------------------------------------------

class TestCreateCodeInterpreter(unittest.TestCase):
    def _run(self, props=None):
        import cfn_handler
        mock_ctrl = _make_control_client()
        with patch.object(cfn_handler, "client", mock_ctrl):
            with patch("cfn_handler.time"):
                result = cfn_handler.create_code_interpreter(
                    props or {
                        "Name": "test-ci",
                        "ExecutionRoleArn": "arn:aws:iam::123:role/ci-role",
                        "NetworkMode": "PUBLIC",
                    }
                )
        return result, mock_ctrl

    def test_returns_physical_resource_id(self):
        result, _ = self._run()
        self.assertEqual(result["PhysicalResourceId"], "ci-001")

    def test_returns_ci_arn(self):
        result, _ = self._run()
        self.assertIn("CodeInterpreterArn", result)

    def test_calls_create_with_correct_params(self):
        _, mock_ctrl = self._run()
        call_kwargs = mock_ctrl.create_code_interpreter.call_args[1]
        self.assertEqual(call_kwargs["name"], "test-ci")
        self.assertEqual(
            call_kwargs["networkConfiguration"]["networkMode"], "PUBLIC"
        )

    def test_waits_for_ready_status(self):
        _, mock_ctrl = self._run()
        mock_ctrl.get_code_interpreter.assert_called()

    def test_delete_swallows_not_found(self):
        import cfn_handler
        mock_ctrl = _make_control_client()
        mock_ctrl.delete_code_interpreter.side_effect = (
            mock_ctrl.exceptions.ResourceNotFoundException()
        )
        with patch.object(cfn_handler, "client", mock_ctrl):
            # 不应该抛出异常
            cfn_handler.delete_code_interpreter("ci-999")


# ---------------------------------------------------------------------------
# create_browser
# ---------------------------------------------------------------------------

class TestCreateBrowser(unittest.TestCase):
    def _run(self, props=None):
        import cfn_handler
        mock_ctrl = _make_control_client()
        with patch.object(cfn_handler, "client", mock_ctrl):
            with patch("cfn_handler.time"):
                result = cfn_handler.create_browser(
                    props or {
                        "Name": "test-browser",
                        "ExecutionRoleArn": "arn:aws:iam::123:role/br-role",
                    }
                )
        return result, mock_ctrl

    def test_returns_browser_id(self):
        result, _ = self._run()
        self.assertEqual(result["BrowserId"], "br-001")

    def test_returns_browser_arn(self):
        result, _ = self._run()
        self.assertIn("BrowserArn", result)

    def test_waits_for_ready(self):
        _, mock_ctrl = self._run()
        mock_ctrl.get_browser.assert_called()

    def test_delete_swallows_not_found(self):
        import cfn_handler
        mock_ctrl = _make_control_client()
        mock_ctrl.delete_browser.side_effect = (
            mock_ctrl.exceptions.ResourceNotFoundException()
        )
        with patch.object(cfn_handler, "client", mock_ctrl):
            cfn_handler.delete_browser("br-999")


# ---------------------------------------------------------------------------
# create_agent_runtime
# ---------------------------------------------------------------------------

class TestCreateAgentRuntime(unittest.TestCase):
    _props = {
        "Name": "test-runtime",
        "ContainerUri": "123.dkr.ecr.us-east-1.amazonaws.com/crawler:latest",
        "RoleArn": "arn:aws:iam::123:role/rt-role",
        "NetworkMode": "PUBLIC",
        "ServerProtocol": "HTTP",
        "EnvironmentVariablesJson": '{"CODE_INTERPRETER_ID": "ci-001"}',
    }

    def _run(self):
        import cfn_handler
        mock_ctrl = _make_control_client()
        with patch.object(cfn_handler, "client", mock_ctrl):
            with patch("cfn_handler.time"):
                result = cfn_handler.create_agent_runtime(self._props)
        return result, mock_ctrl

    def test_returns_runtime_id(self):
        result, _ = self._run()
        self.assertEqual(result["AgentRuntimeId"], "rt-001")

    def test_passes_env_vars(self):
        _, mock_ctrl = self._run()
        call_kwargs = mock_ctrl.create_agent_runtime.call_args[1]
        self.assertEqual(
            call_kwargs["environmentVariables"],
            {"CODE_INTERPRETER_ID": "ci-001"},
        )

    def test_passes_container_uri(self):
        _, mock_ctrl = self._run()
        call_kwargs = mock_ctrl.create_agent_runtime.call_args[1]
        uri = call_kwargs["agentRuntimeArtifact"]["containerConfiguration"]["containerUri"]
        self.assertIn("crawler:latest", uri)

    def test_delete_cleans_endpoints_first(self):
        import cfn_handler
        mock_ctrl = _make_control_client()
        mock_ctrl.list_agent_runtime_endpoints.return_value = {
            "agentRuntimeEndpoints": [{"name": "ep1"}, {"name": "ep2"}]
        }
        with patch.object(cfn_handler, "client", mock_ctrl):
            with patch("cfn_handler.time"):
                cfn_handler.delete_agent_runtime("rt-001")
        self.assertEqual(
            mock_ctrl.delete_agent_runtime_endpoint.call_count, 2
        )
        mock_ctrl.delete_agent_runtime.assert_called_once_with(
            agentRuntimeId="rt-001"
        )

    def test_delete_swallows_not_found(self):
        import cfn_handler
        mock_ctrl = _make_control_client()
        mock_ctrl.delete_agent_runtime.side_effect = (
            mock_ctrl.exceptions.ResourceNotFoundException()
        )
        with patch.object(cfn_handler, "client", mock_ctrl):
            with patch("cfn_handler.time"):
                cfn_handler.delete_agent_runtime("rt-999")


# ---------------------------------------------------------------------------
# create_agent_runtime_endpoint
# ---------------------------------------------------------------------------

class TestCreateAgentRuntimeEndpoint(unittest.TestCase):
    _props = {
        "AgentRuntimeId": "rt-001",
        "EndpointName": "myEndpoint",
        "AgentRuntimeVersion": "LATEST",
    }

    def _run(self):
        import cfn_handler
        mock_ctrl = _make_control_client()
        with patch.object(cfn_handler, "client", mock_ctrl):
            with patch("cfn_handler.time"):
                result = cfn_handler.create_agent_runtime_endpoint(self._props)
        return result, mock_ctrl

    def test_returns_endpoint_arn(self):
        result, _ = self._run()
        self.assertIn("EndpointArn", result)

    def test_physical_resource_id_format(self):
        result, _ = self._run()
        self.assertEqual(result["PhysicalResourceId"], "rt-001/myEndpoint")

    def test_waits_for_ready(self):
        _, mock_ctrl = self._run()
        mock_ctrl.get_agent_runtime_endpoint.assert_called()

    def test_raises_on_failed_endpoint(self):
        import cfn_handler
        mock_ctrl = _make_control_client()
        mock_ctrl.get_agent_runtime_endpoint.return_value = {
            "status": "FAILED",
            "failureReason": "image pull error",
        }
        with patch.object(cfn_handler, "client", mock_ctrl):
            with patch("cfn_handler.time"):
                with self.assertRaises(RuntimeError) as ctx:
                    cfn_handler.create_agent_runtime_endpoint(self._props)
        self.assertIn("image pull error", str(ctx.exception))

    def test_delete_parses_physical_id(self):
        import cfn_handler
        mock_ctrl = _make_control_client()
        with patch.object(cfn_handler, "client", mock_ctrl):
            cfn_handler.delete_agent_runtime_endpoint("rt-001/myEndpoint")
        mock_ctrl.delete_agent_runtime_endpoint.assert_called_once_with(
            agentRuntimeId="rt-001", endpointName="myEndpoint"
        )

    def test_delete_swallows_not_found(self):
        import cfn_handler
        mock_ctrl = _make_control_client()
        mock_ctrl.delete_agent_runtime_endpoint.side_effect = (
            mock_ctrl.exceptions.ResourceNotFoundException()
        )
        with patch.object(cfn_handler, "client", mock_ctrl):
            cfn_handler.delete_agent_runtime_endpoint("rt-001/missing")


# ---------------------------------------------------------------------------
# setup_xray_cloudwatch
# ---------------------------------------------------------------------------

class TestSetupXrayCloudwatch(unittest.TestCase):
    def test_returns_physical_resource_id(self):
        import cfn_handler
        mock_xray = MagicMock()
        mock_xray.get_trace_segment_destination.return_value = {
            "destination": {"status": "ACTIVE"}
        }
        with patch.object(cfn_handler, "xray", mock_xray):
            with patch("cfn_handler.time"):
                result = cfn_handler.setup_xray_cloudwatch({})
        self.assertEqual(result["PhysicalResourceId"], "xray-cloudwatch-destination")

    def test_calls_update_destination(self):
        import cfn_handler
        mock_xray = MagicMock()
        mock_xray.get_trace_segment_destination.return_value = {
            "destination": {"status": "ACTIVE"}
        }
        with patch.object(cfn_handler, "xray", mock_xray):
            with patch("cfn_handler.time"):
                cfn_handler.setup_xray_cloudwatch({})
        mock_xray.update_trace_segment_destination.assert_called_once_with(
            Destination="CloudWatchLogs"
        )

    def test_polls_until_active(self):
        import cfn_handler
        mock_xray = MagicMock()
        mock_xray.get_trace_segment_destination.side_effect = [
            {"destination": {"status": "PENDING"}},
            {"destination": {"status": "PENDING"}},
            {"destination": {"status": "ACTIVE"}},
        ]
        with patch.object(cfn_handler, "xray", mock_xray):
            with patch("cfn_handler.time"):
                cfn_handler.setup_xray_cloudwatch({})
        self.assertEqual(mock_xray.get_trace_segment_destination.call_count, 3)


# ---------------------------------------------------------------------------
# create_cw_resource_policy
# ---------------------------------------------------------------------------

class TestCreateCwResourcePolicy(unittest.TestCase):
    def test_calls_put_resource_policy(self):
        import cfn_handler
        mock_logs = MagicMock()
        with patch.object(cfn_handler, "logs", mock_logs):
            cfn_handler.create_cw_resource_policy({"PolicyName": "my-policy"})
        mock_logs.put_resource_policy.assert_called_once()
        call_kwargs = mock_logs.put_resource_policy.call_args[1]
        self.assertEqual(call_kwargs["policyName"], "my-policy")

    def test_policy_doc_allows_xray(self):
        import cfn_handler
        mock_logs = MagicMock()
        with patch.object(cfn_handler, "logs", mock_logs):
            cfn_handler.create_cw_resource_policy({})
        policy_doc = json.loads(
            mock_logs.put_resource_policy.call_args[1]["policyDocument"]
        )
        stmt = policy_doc["Statement"][0]
        self.assertIn("xray.amazonaws.com", stmt["Principal"]["Service"])
        self.assertIn("logs:PutLogEvents", stmt["Action"])

    def test_physical_id_includes_policy_name(self):
        import cfn_handler
        mock_logs = MagicMock()
        with patch.object(cfn_handler, "logs", mock_logs):
            result = cfn_handler.create_cw_resource_policy({"PolicyName": "xray-pol"})
        self.assertIn("xray-pol", result["PhysicalResourceId"])

    def test_delete_calls_delete_resource_policy(self):
        import cfn_handler
        mock_logs = MagicMock()
        with patch.object(cfn_handler, "logs", mock_logs):
            cfn_handler.delete_cw_resource_policy("cw-policy/my-policy")
        mock_logs.delete_resource_policy.assert_called_once_with(
            policyName="my-policy"
        )

    def test_delete_swallows_exceptions(self):
        import cfn_handler
        mock_logs = MagicMock()
        mock_logs.delete_resource_policy.side_effect = RuntimeError("not found")
        with patch.object(cfn_handler, "logs", mock_logs):
            cfn_handler.delete_cw_resource_policy("cw-policy/missing")


# ---------------------------------------------------------------------------
# handler — dispatch table
# ---------------------------------------------------------------------------

class TestHandler(unittest.TestCase):
    def _call_handler(self, event, mock_ctrl=None, mock_xray=None, mock_logs=None):
        import cfn_handler
        mock_ctrl = mock_ctrl or _make_control_client()
        mock_xray = mock_xray or MagicMock(
            get_trace_segment_destination=MagicMock(
                return_value={"destination": {"status": "ACTIVE"}}
            )
        )
        mock_logs = mock_logs or MagicMock()
        with patch.object(cfn_handler, "client", mock_ctrl):
            with patch.object(cfn_handler, "xray", mock_xray):
                with patch.object(cfn_handler, "logs", mock_logs):
                    with patch("cfn_handler.time"):
                        with patch("urllib.request.urlopen") as mock_urlopen:
                            cfn_handler.handler(event, {})
                            return mock_urlopen

    def test_create_code_interpreter_dispatches(self):
        event = _make_cfn_event("Create", "CodeInterpreter", {
            "Name": "test-ci", "ExecutionRoleArn": "arn:...:role/r",
        })
        mock_urlopen = self._call_handler(event)
        body = json.loads(mock_urlopen.call_args[0][0].data.decode())
        self.assertEqual(body["Status"], "SUCCESS")

    def test_create_browser_dispatches(self):
        event = _make_cfn_event("Create", "Browser", {
            "Name": "test-browser",
        })
        mock_urlopen = self._call_handler(event)
        body = json.loads(mock_urlopen.call_args[0][0].data.decode())
        self.assertEqual(body["Status"], "SUCCESS")

    def test_create_agent_runtime_dispatches(self):
        event = _make_cfn_event("Create", "AgentRuntime", {
            "Name": "rt",
            "ContainerUri": "123.dkr.ecr.us-east-1.amazonaws.com/img:v1",
            "RoleArn": "arn:...:role/r",
        })
        mock_urlopen = self._call_handler(event)
        body = json.loads(mock_urlopen.call_args[0][0].data.decode())
        self.assertEqual(body["Status"], "SUCCESS")

    def test_create_endpoint_dispatches(self):
        event = _make_cfn_event("Create", "AgentRuntimeEndpoint", {
            "AgentRuntimeId": "rt-001",
            "EndpointName": "ep",
        })
        mock_urlopen = self._call_handler(event)
        body = json.loads(mock_urlopen.call_args[0][0].data.decode())
        self.assertEqual(body["Status"], "SUCCESS")

    def test_create_xray_setup_dispatches(self):
        event = _make_cfn_event("Create", "XRayCloudWatchSetup")
        mock_urlopen = self._call_handler(event)
        body = json.loads(mock_urlopen.call_args[0][0].data.decode())
        self.assertEqual(body["Status"], "SUCCESS")

    def test_create_cw_policy_dispatches(self):
        event = _make_cfn_event("Create", "CloudWatchResourcePolicy", {
            "PolicyName": "pol"
        })
        mock_urlopen = self._call_handler(event)
        body = json.loads(mock_urlopen.call_args[0][0].data.decode())
        self.assertEqual(body["Status"], "SUCCESS")

    def test_update_is_noop(self):
        event = _make_cfn_event("Update", "CodeInterpreter",
                                physical_id="ci-existing")
        mock_urlopen = self._call_handler(event)
        body = json.loads(mock_urlopen.call_args[0][0].data.decode())
        self.assertEqual(body["Status"], "SUCCESS")
        self.assertEqual(body["PhysicalResourceId"], "ci-existing")

    def test_delete_dispatches(self):
        event = _make_cfn_event("Delete", "CodeInterpreter",
                                physical_id="ci-001")
        mock_urlopen = self._call_handler(event)
        body = json.loads(mock_urlopen.call_args[0][0].data.decode())
        self.assertEqual(body["Status"], "SUCCESS")

    def test_unknown_resource_type_returns_failed(self):
        event = _make_cfn_event("Create", "UnknownType")
        mock_urlopen = self._call_handler(event)
        body = json.loads(mock_urlopen.call_args[0][0].data.decode())
        self.assertEqual(body["Status"], "FAILED")
        self.assertIn("UnknownType", body["Reason"])

    def test_exception_in_create_returns_failed(self):
        import cfn_handler
        mock_ctrl = _make_control_client()
        mock_ctrl.create_code_interpreter.side_effect = RuntimeError("quota exceeded")
        event = _make_cfn_event("Create", "CodeInterpreter", {"Name": "ci"})
        mock_urlopen = self._call_handler(event, mock_ctrl=mock_ctrl)
        body = json.loads(mock_urlopen.call_args[0][0].data.decode())
        self.assertEqual(body["Status"], "FAILED")
        self.assertIn("quota exceeded", body["Reason"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
