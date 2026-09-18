import os

import boto3

REGION = os.getenv("REGION", "ap-south-1")
ACCOUNT_ID = boto3.client("sts", region_name=REGION).get_caller_identity()["Account"]
REPO_NAME = "agentcore-commerce-bot"
# AgentCore runtime service role in this account (must be able to call Bedrock,
# the guardrail and the knowledge base in REGION).
ROLE_ARN = os.environ["AGENTCORE_ROLE_ARN"]

client = boto3.client("bedrock-agentcore-control", region_name=REGION)

image_uri = f"{ACCOUNT_ID}.dkr.ecr.{REGION}.amazonaws.com/{REPO_NAME}:latest"

runtime_name = "agentcore_commerce_agent"


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
        )

        runtime_id = response["agentRuntimeId"]
        print(f"✅ Created runtime ID: {runtime_id}")

except Exception as e:
    print("❌ Deployment error:", str(e))
    raise

print("✅ Deployment complete")
