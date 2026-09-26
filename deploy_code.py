"""Code-based AgentCore Runtime deploy (no Docker/ECR): package -> S3 -> runtime.

Usage: AGENTCORE_ROLE_ARN=<arn> uv run deploy_code.py
"""

import os
import shutil
import subprocess
import zipfile
from pathlib import Path

import boto3
from dotenv import dotenv_values

REGION = os.getenv("REGION", "ap-south-1")
ROLE_ARN = os.environ["AGENTCORE_ROLE_ARN"]
ACCOUNT_ID = boto3.client("sts", region_name=REGION).get_caller_identity()["Account"]
BUCKET = os.getenv("CODE_BUCKET", f"commerce-bot-agentcore-code-{ACCOUNT_ID}")
KEY = "commerce-bot/deployment_package.zip"
RUNTIME_NAME = "agentcore_commerce_agent"

ROOT = Path(__file__).parent
BUILD = ROOT / ".build"
APP_DIRS = ["agents", "configs", "models", "services", "sops", "tools", "utils"]
APP_FILES = ["main.py", "__init__.py"]

# Only the non-secret config keys are injected into the runtime.
ENV_KEYS = [
    "REGION", "ORCHESTRATOR_MODEL_ID", "SPECIALIST_MODEL_ID", "AUTH_MODEL_ID",
    "GUARDRAIL_ID", "GUARDRAIL_VERSION", "KNOWLEDGE_BASE_ID", "BRAND_NAME",
    "ECOMMERCE_API_BASE_URL", "ECOMMERCE_AUTH_SCHEME", "ECOMMERCE_API_TIMEOUT",
]


def build_package() -> Path:
    shutil.rmtree(BUILD, ignore_errors=True)
    deps = BUILD / "deps"
    deps.mkdir(parents=True)
    subprocess.run(
        ["uv", "export", "--frozen", "--no-dev", "--no-hashes", "--no-emit-project",
         "-o", str(BUILD / "requirements.txt")],
        check=True,
    )
    subprocess.run(
        ["uv", "pip", "install", "--target", str(deps),
         "--python-platform", "aarch64-manylinux2014", "--python-version", "3.13",
         "--only-binary", ":all:", "-r", str(BUILD / "requirements.txt")],
        check=True,
    )
    zip_path = BUILD / "deployment_package.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for f in deps.rglob("*"):
            if f.is_file():
                z.write(f, f.relative_to(deps))
        for name in APP_FILES:
            z.write(ROOT / name, name)
        for d in APP_DIRS:
            for f in (ROOT / d).rglob("*"):
                if f.is_file() and "__pycache__" not in f.parts:
                    z.write(f, f.relative_to(ROOT))
    print(f"Built {zip_path} ({zip_path.stat().st_size / 1e6:.1f} MB)")
    return zip_path


def upload(zip_path: Path) -> str:
    s3 = boto3.client("s3", region_name=REGION)
    try:
        s3.head_bucket(Bucket=BUCKET)
    except Exception:
        s3.create_bucket(
            Bucket=BUCKET,
            CreateBucketConfiguration={"LocationConstraint": REGION},
        )
        s3.put_public_access_block(
            Bucket=BUCKET,
            PublicAccessBlockConfiguration={
                "BlockPublicAcls": True, "IgnorePublicAcls": True,
                "BlockPublicPolicy": True, "RestrictPublicBuckets": True,
            },
        )
        s3.put_bucket_versioning(
            Bucket=BUCKET, VersioningConfiguration={"Status": "Enabled"}
        )
    s3.upload_file(str(zip_path), BUCKET, KEY)
    version = s3.head_object(Bucket=BUCKET, Key=KEY)["VersionId"]
    print(f"Uploaded s3://{BUCKET}/{KEY} (version {version})")
    return version


def deploy(version: str) -> None:
    env = dotenv_values(ROOT / ".env")
    env_vars = {k: env[k] for k in ENV_KEYS if env.get(k)}
    artifact = {
        "codeConfiguration": {
            "code": {"s3": {"bucket": BUCKET, "prefix": KEY, "versionId": version}},
            "runtime": "PYTHON_3_13",
            "entryPoint": ["main.py"],
        }
    }
    client = boto3.client("bedrock-agentcore-control", region_name=REGION)
    existing = next(
        (r for r in client.list_agent_runtimes().get("agentRuntimes", [])
         if r["agentRuntimeName"] == RUNTIME_NAME),
        None,
    )
    common = dict(
        agentRuntimeArtifact=artifact,
        roleArn=ROLE_ARN,
        networkConfiguration={"networkMode": "PUBLIC"},
        environmentVariables=env_vars,
    )
    if existing:
        resp = client.update_agent_runtime(
            agentRuntimeId=existing["agentRuntimeId"], **common
        )
        print("Updated runtime", existing["agentRuntimeId"])
    else:
        resp = client.create_agent_runtime(agentRuntimeName=RUNTIME_NAME, **common)
        print("Created runtime", resp["agentRuntimeId"])
    print("ARN:", resp["agentRuntimeArn"], "| status:", resp["status"])


if __name__ == "__main__":
    deploy(upload(build_package()))
