import json
import os

import boto3

REGION = os.getenv("REGION", "ap-south-1")
ACCOUNT_ID = boto3.client("sts", region_name=REGION).get_caller_identity()["Account"]
REPO_NAME = "agentcore-commerce-bot"
# AgentCore runtime service role in this account (must be able to call Bedrock,
# the guardrail and the knowledge base in REGION).
ROLE_ARN = os.environ["AGENTCORE_ROLE_ARN"]
# Secrets Manager secret (infra/pipeline.yaml: AgentConfigSecret) holding the
# app's non-local config (model ids, guardrail, knowledge base, backend API
# url, ...). Optional so this script still works for a one-off manual deploy.
AGENT_CONFIG_SECRET_ARN = os.getenv("AGENT_CONFIG_SECRET_ARN")

client = boto3.client("bedrock-agentcore-control", region_name=REGION)

image_uri = f"{ACCOUNT_ID}.dkr.ecr.{REGION}.amazonaws.com/{REPO_NAME}:latest"

runtime_name = "agentcore_commerce_agent"


def load_environment_variables() -> dict[str, str]:
    """App config to inject into the AgentCore runtime, sourced from Secrets
    Manager rather than baked into the image. Empty dict if unset (manual
    runs / secret not yet populated)."""
    if not AGENT_CONFIG_SECRET_ARN:
        return {}
    secrets_client = boto3.client("secretsmanager", region_name=REGION)
    secret = secrets_client.get_secret_value(SecretId=AGENT_CONFIG_SECRET_ARN)
    config = json.loads(secret["SecretString"])
    return {k: str(v) for k, v in config.items()}


environment_variables = load_environment_variables()


try:

    #  list and find runtime
    runtimes = client.list_agent_runtimes()

    runtime_id = None

    for r in runtimes.get("agentRuntimes", []):
        if r["agentRuntimeName"] == runtime_name:
            runtime_id = r["agentRuntimeId"]
            break

    if runtime_id:
        print("✅ Runtime exists → updating...")

        response = client.update_agent_runtime(
            agentRuntimeId=runtime_id,
            agentRuntimeArtifact={
                "containerConfiguration": {"containerUri": image_uri}
            },
            networkConfiguration={"networkMode": "PUBLIC"},  # required
            roleArn=ROLE_ARN,  # required
            environmentVariables=environment_variables,
        )

    else:
        print("✅ Creating new runtime...")

        response = client.create_agent_runtime(
            agentRuntimeName=runtime_name,
            agentRuntimeArtifact={
                "containerConfiguration": {"containerUri": image_uri}
            },
            networkConfiguration={"networkMode": "PUBLIC"},
            roleArn=ROLE_ARN,
            environmentVariables=environment_variables,
        )

        runtime_id = response["agentRuntimeId"]
        print(f"✅ Created runtime ID: {runtime_id}")

except Exception as e:
    print("❌ Deployment error:", str(e))
    raise

print("✅ Deployment complete")
