"""Invoke the deployed commerce-bot on the Bedrock AgentCore runtime.

Set AGENT_RUNTIME_ARN (from `deploy_agent.py` output / the AgentCore console) and
a RUNTIME_SESSION_ID of 33+ chars.
"""

import json
import os
import uuid

import boto3

REGION = os.getenv("REGION", "ap-south-1")
RUNTIME_ARN = os.environ["AGENT_RUNTIME_ARN"]
SESSION_ID = os.getenv("RUNTIME_SESSION_ID",
                       uuid.uuid4().hex + uuid.uuid4().hex[:5])

client = boto3.client("bedrock-agentcore", region_name=REGION)

payload = json.dumps(
    {
        "input": {
            "prompt": "show me wireless earbuds under 3000",
            "details": {"channel": "CHAT", "role": "customer"},
        }
    }
)

response = client.invoke_agent_runtime(
    agentRuntimeArn=RUNTIME_ARN,
    runtimeSessionId=SESSION_ID,
    payload=payload,
    qualifier="DEFAULT",
)

print("Agent Response:", json.loads(response["response"].read()))
