"""CloudFormation Custom Resource handler for Bedrock AgentCore resources.

Supported ResourceType values (passed as Properties.ResourceType):
  - CodeInterpreter
  - Browser
  - AgentRuntime
  - AgentRuntimeEndpoint
  - XRayCloudWatchSetup
  - CloudWatchResourcePolicy
"""
import json
import time
import os
import subprocess
import sys
import urllib.request
import traceback

# Ensure recent boto3 (Lambda runtime may have an older version)
try:
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "boto3>=1.35.0", "-q", "-t", "/tmp/libs"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    sys.path.insert(0, "/tmp/libs")
except Exception:
    pass  # proceed with built-in boto3

import boto3

REGION = os.environ.get("REGION", "us-east-1")
client = boto3.client("bedrock-agentcore-control", region_name=REGION)
xray   = boto3.client("xray",   region_name=REGION)
logs   = boto3.client("logs",   region_name=REGION)


# ── Response helper ────────────────────────────────────────────────────────────
def cfn_send(event, status, data=None, reason=""):
    body = json.dumps({
        "Status":             status,
        "Reason":             reason or "See CloudWatch Logs",
        "PhysicalResourceId": (data or {}).get(
            "PhysicalResourceId", event.get("PhysicalResourceId", "none")
        ),
        "StackId":            event["StackId"],
        "RequestId":          event["RequestId"],
        "LogicalResourceId":  event["LogicalResourceId"],
        "Data":               data or {},
    }).encode()
    req = urllib.request.Request(
        event["ResponseURL"],
        data=body,
        headers={"Content-Type": "", "Content-Length": len(body)},
        method="PUT",
    )
    urllib.request.urlopen(req)


# ── Polling helper ─────────────────────────────────────────────────────────────
def wait_status(get_fn, id_key, id_val, ready="READY", fail="FAILED",
                max_wait=600, interval=15):
    for _ in range(max_wait // interval):
        resp = get_fn(**{id_key: id_val})
        status = resp.get("status", "")
        if status == ready:
            return resp
        if status == fail:
            raise RuntimeError(
                f"Resource {id_val} status={fail}: {resp.get('failureReason', '')}"
            )
        time.sleep(interval)
    raise TimeoutError(f"Timed out waiting for {id_val} to become {ready}")


# ── CodeInterpreter ────────────────────────────────────────────────────────────
def create_code_interpreter(props):
    r = client.create_code_interpreter(
        name=props["Name"],
        executionRoleArn=props.get("ExecutionRoleArn", ""),
        networkConfiguration={"networkMode": props.get("NetworkMode", "PUBLIC")},
    )
    ci_id  = r["codeInterpreterId"]
    ci_arn = r["codeInterpreterArn"]
    wait_status(client.get_code_interpreter, "codeInterpreterId", ci_id)
    return {
        "PhysicalResourceId":  ci_id,
        "CodeInterpreterId":   ci_id,
        "CodeInterpreterArn":  ci_arn,
    }


def delete_code_interpreter(physical_id):
    try:
        client.delete_code_interpreter(codeInterpreterId=physical_id)
    except client.exceptions.ResourceNotFoundException:
        pass


# ── Browser ────────────────────────────────────────────────────────────────────
def create_browser(props):
    r = client.create_browser(
        name=props["Name"],
        executionRoleArn=props.get("ExecutionRoleArn", ""),
        networkConfiguration={"networkMode": props.get("NetworkMode", "PUBLIC")},
    )
    b_id  = r["browserId"]
    b_arn = r["browserArn"]
    wait_status(client.get_browser, "browserId", b_id)
    return {
        "PhysicalResourceId": b_id,
        "BrowserId":          b_id,
        "BrowserArn":         b_arn,
    }


def delete_browser(physical_id):
    try:
        client.delete_browser(browserId=physical_id)
    except client.exceptions.ResourceNotFoundException:
        pass


# ── AgentRuntime ───────────────────────────────────────────────────────────────
def create_agent_runtime(props):
    env_vars = json.loads(props.get("EnvironmentVariablesJson", "{}"))
    r = client.create_agent_runtime(
        agentRuntimeName=props["Name"],
        agentRuntimeArtifact={
            "containerConfiguration": {"containerUri": props["ContainerUri"]},
        },
        roleArn=props["RoleArn"],
        networkConfiguration={"networkMode": props.get("NetworkMode", "PUBLIC")},
        protocolConfiguration={"serverProtocol": props.get("ServerProtocol", "HTTP")},
        environmentVariables=env_vars,
    )
    rt_id  = r["agentRuntimeId"]
    rt_arn = r["agentRuntimeArn"]
    wait_status(client.get_agent_runtime, "agentRuntimeId", rt_id)
    return {
        "PhysicalResourceId": rt_id,
        "AgentRuntimeId":     rt_id,
        "AgentRuntimeArn":    rt_arn,
    }


def delete_agent_runtime(physical_id):
    try:
        # Try to delete endpoints first
        try:
            eps = client.list_agent_runtime_endpoints(agentRuntimeId=physical_id)
            for ep in eps.get("agentRuntimeEndpoints", []):
                try:
                    client.delete_agent_runtime_endpoint(
                        agentRuntimeId=physical_id, endpointName=ep["name"]
                    )
                    time.sleep(5)
                except Exception:
                    pass
        except Exception:
            pass
        client.delete_agent_runtime(agentRuntimeId=physical_id)
    except client.exceptions.ResourceNotFoundException:
        pass


# ── AgentRuntimeEndpoint ───────────────────────────────────────────────────────
def create_agent_runtime_endpoint(props):
    rt_id = props["AgentRuntimeId"]
    name  = props["EndpointName"]
    r = client.create_agent_runtime_endpoint(
        agentRuntimeId=rt_id,
        name=name,
        agentRuntimeVersion=props.get("AgentRuntimeVersion", "LATEST"),
    )
    ep_arn = r["agentRuntimeEndpointArn"]
    for _ in range(60):
        resp   = client.get_agent_runtime_endpoint(agentRuntimeId=rt_id, endpointName=name)
        status = resp.get("status", "")
        if status == "READY":
            break
        if status == "FAILED":
            raise RuntimeError(f"Endpoint failed: {resp.get('failureReason', '')}")
        time.sleep(15)
    return {
        "PhysicalResourceId": f"{rt_id}/{name}",
        "EndpointArn":        ep_arn,
        "EndpointName":       name,
    }


def delete_agent_runtime_endpoint(physical_id):
    try:
        rt_id, name = physical_id.split("/", 1)
        client.delete_agent_runtime_endpoint(agentRuntimeId=rt_id, endpointName=name)
    except (client.exceptions.ResourceNotFoundException, ValueError):
        pass


# ── X-Ray → CloudWatch ─────────────────────────────────────────────────────────
def setup_xray_cloudwatch(_props):
    xray.update_trace_segment_destination(Destination="CloudWatchLogs")
    for _ in range(20):
        resp = xray.get_trace_segment_destination()
        if resp.get("destination", {}).get("status") == "ACTIVE":
            break
        time.sleep(10)
    return {"PhysicalResourceId": "xray-cloudwatch-destination"}


# ── CloudWatch resource policy ─────────────────────────────────────────────────
def create_cw_resource_policy(props):
    policy_name = props.get("PolicyName", "xray-logs-policy")
    policy_doc  = json.dumps({
        "Version": "2012-10-17",
        "Statement": [{
            "Sid":       "AllowXRayPutLogEvents",
            "Effect":    "Allow",
            "Principal": {"Service": "xray.amazonaws.com"},
            "Action":    ["logs:PutLogEvents", "logs:CreateLogGroup"],
            "Resource":  "*",
        }],
    })
    logs.put_resource_policy(policyName=policy_name, policyDocument=policy_doc)
    return {"PhysicalResourceId": f"cw-policy/{policy_name}"}


def delete_cw_resource_policy(physical_id):
    try:
        policy_name = physical_id.split("/", 1)[-1]
        logs.delete_resource_policy(policyName=policy_name)
    except Exception:
        pass


# ── Dispatch table ─────────────────────────────────────────────────────────────
DISPATCH = {
    "CodeInterpreter":          (create_code_interpreter,        delete_code_interpreter),
    "Browser":                  (create_browser,                 delete_browser),
    "AgentRuntime":             (create_agent_runtime,           delete_agent_runtime),
    "AgentRuntimeEndpoint":     (create_agent_runtime_endpoint,  delete_agent_runtime_endpoint),
    "XRayCloudWatchSetup":      (setup_xray_cloudwatch,          lambda _: None),
    "CloudWatchResourcePolicy": (create_cw_resource_policy,      delete_cw_resource_policy),
}


# ── Handler ────────────────────────────────────────────────────────────────────
def handler(event, context):
    props   = event.get("Properties", {})
    rtype   = props.get("ResourceType", "")
    req     = event["RequestType"]
    phys_id = event.get("PhysicalResourceId", "")

    if rtype not in DISPATCH:
        cfn_send(event, "FAILED", reason=f"Unknown ResourceType: {rtype}")
        return

    create_fn, delete_fn = DISPATCH[rtype]

    try:
        if req == "Create":
            data = create_fn(props)
            cfn_send(event, "SUCCESS", data)
        elif req == "Update":
            # No-op: AgentCore resources use replacement for updates.
            cfn_send(event, "SUCCESS", {"PhysicalResourceId": phys_id})
        elif req == "Delete":
            delete_fn(phys_id)
            cfn_send(event, "SUCCESS", {"PhysicalResourceId": phys_id})
    except Exception as exc:
        cfn_send(event, "FAILED", reason=str(exc))
        traceback.print_exc()
