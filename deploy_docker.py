"""Build the ARM64 Docker image, push it to ECR and (create|update) the
AgentCore runtime, injecting app config from ``.env``.

Usage:
    AGENTCORE_ROLE_ARN=<arn> uv run deploy_docker.py            # build + push + deploy
    AGENTCORE_ROLE_ARN=<arn> uv run deploy_docker.py --dry-run  # show what would happen
    uv run deploy_docker.py --skip-build                        # redeploy image TAG only
    ENV_FILE=.env.prod IMAGE_TAG=v3 uv run deploy_docker.py

``.env`` is never baked into the image (see ``.dockerignore``); only the
allow-listed, non-secret keys below are sent as runtime environment variables.
"""

import argparse
import base64
import os
import subprocess
import time
from pathlib import Path

import boto3
from dotenv import dotenv_values

ROOT = Path(__file__).parent
REGION = os.getenv("REGION", "ap-south-1")
REPO_NAME = "agentcore-commerce-bot"
# Container runtime; the older code-based "agentcore_commerce_agent" can't be
# switched to a container artifact, so this one is created separately.
RUNTIME_NAME = "agentcore_commerce_agent_docker"
ENV_FILE = ROOT / os.getenv("ENV_FILE", ".env")

# Non-secret app config forwarded to the runtime (matches configs/settings.py).
ENV_KEYS = [
    "APP_ENV", "LOG_LEVEL", "BRAND_NAME", "REGION",
    "ORCHESTRATOR_MODEL_ID", "SPECIALIST_MODEL_ID", "AUTH_MODEL_ID",
    "GUARDRAIL_ID", "GUARDRAIL_VERSION",
    "KNOWLEDGE_BASE_ID", "KNOWLEDGE_BASE_TOP_K",
    "SUPPORT_PAGE_URLS", "SUPPORT_PAGE_CACHE_TTL", "SUPPORT_PAGE_TIMEOUT",
    "SUPPORT_PAGE_MAX_CHARS",
    "AGENTCORE_MEMORY_ID",
    "ECOMMERCE_API_BASE_URL", "ECOMMERCE_AUTH_SCHEME", "ECOMMERCE_TOKEN_HEADER",
    "ECOMMERCE_API_TIMEOUT",
]
REQUIRED = ["REGION", "ORCHESTRATOR_MODEL_ID", "ECOMMERCE_API_BASE_URL"]


def load_env() -> dict[str, str]:
    values = dotenv_values(ENV_FILE)
    env = {k: str(values[k]) for k in ENV_KEYS if values.get(k) not in (None, "")}
    missing = [k for k in REQUIRED if k not in env]
    if missing:
        raise SystemExit(f"Missing in {ENV_FILE.name}: {', '.join(missing)}")
    return env


def image_tag() -> str:
    if os.getenv("IMAGE_TAG"):
        return os.environ["IMAGE_TAG"]
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT, check=True, capture_output=True, text=True,
        ).stdout.strip()
    except Exception:  # noqa: BLE001
        sha = "nogit"
    # unique per run so AgentCore always sees a changed image and rolls out
    return f"{sha}-{time.strftime('%Y%m%d%H%M%S')}"


def ensure_repo(ecr) -> None:
    try:
        ecr.describe_repositories(repositoryNames=[REPO_NAME])
    except ecr.exceptions.RepositoryNotFoundException:
        ecr.create_repository(
            repositoryName=REPO_NAME,
            imageScanningConfiguration={"scanOnPush": True},
        )
        print(f"Created ECR repo {REPO_NAME}")


def docker_login(ecr, registry: str) -> None:
    token = ecr.get_authorization_token()["authorizationData"][0]["authorizationToken"]
    user, password = base64.b64decode(token).decode().split(":", 1)
    subprocess.run(
        ["docker", "login", "--username", user, "--password-stdin", registry],
        input=password, text=True, check=True,
    )


def build_and_push(image_uri: str) -> None:
    subprocess.run(
        ["docker", "buildx", "build", "--platform", "linux/arm64",
         "-t", image_uri, "--push", str(ROOT)],
        check=True,
    )


def deploy(image_uri: str, role_arn: str, env: dict[str, str]) -> None:
    client = boto3.client("bedrock-agentcore-control", region_name=REGION)
    existing = next(
        (r for r in client.list_agent_runtimes().get("agentRuntimes", [])
         if r["agentRuntimeName"] == RUNTIME_NAME),
        None,
    )
    common = dict(
        agentRuntimeArtifact={"containerConfiguration": {"containerUri": image_uri}},
        networkConfiguration={"networkMode": "PUBLIC"},
        roleArn=role_arn,
        environmentVariables=env,
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
    print("Test:  AGENT_RUNTIME_ARN=%s uv run invoke_agent.py" % resp["agentRuntimeArn"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-build", action="store_true",
                        help="deploy an already-pushed image (set IMAGE_TAG)")
    args = parser.parse_args()

    env = load_env()
    account = boto3.client("sts", region_name=REGION).get_caller_identity()["Account"]
    registry = f"{account}.dkr.ecr.{REGION}.amazonaws.com"
    tag = os.environ["IMAGE_TAG"] if args.skip_build else image_tag()
    image_uri = f"{registry}/{REPO_NAME}:{tag}"
    role_arn = os.environ.get("AGENTCORE_ROLE_ARN", "")

    print(f"Image : {image_uri}")
    print(f"Env   : {sorted(env)}  (from {ENV_FILE.name})")
    if args.dry_run:
        return
    if not role_arn:
        raise SystemExit("Set AGENTCORE_ROLE_ARN (infra/agentcore-role.yaml output).")

    if not args.skip_build:
        ecr = boto3.client("ecr", region_name=REGION)
        ensure_repo(ecr)
        docker_login(ecr, registry)
        build_and_push(image_uri)
    deploy(image_uri, role_arn, env)


if __name__ == "__main__":
    main()
