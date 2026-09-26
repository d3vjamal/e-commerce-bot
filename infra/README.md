# Deployment infra — runbook + concepts

This folder holds the CI/CD pipeline (`pipeline.yaml`) that builds
commerce-bot's container image and deploys it to Amazon Bedrock AgentCore
Runtime. This doc explains the AWS pieces involved (ECR especially, since
that's the first thing you'll hit permission gaps on) and how to run the
deploy.

## What is ECR, and why does this project need it?

**ECR (Elastic Container Registry)** is AWS's storage service for Docker
images — think of it as a private version of Docker Hub, one per AWS
account/region.

commerce-bot ships as a Docker image (see `Dockerfile` at the repo root).
Amazon Bedrock **AgentCore Runtime** — the service that actually runs your
agent — doesn't accept a Dockerfile or source code directly. Its
`create_agent_runtime` API takes a `containerConfiguration.containerUri`
field: an image that already exists somewhere AgentCore can pull from. ECR is
that "somewhere" here.

So the flow is:

```
Dockerfile  →  docker build  →  push to ECR  →  AgentCore pulls from ECR and runs it
```

Concretely in this repo: `deploy_agent.py` builds this URI —

```python
image_uri = f"{ACCOUNT_ID}.dkr.ecr.{REGION}.amazonaws.com/agentcore-commerce-bot:latest"
```

— and hands it to `create_agent_runtime`/`update_agent_runtime`. If that
image isn't in ECR yet (or isn't up to date), the runtime has nothing to run
or is running stale code.

### Core ECR concepts

| Term | Meaning |
|---|---|
| **Registry** | The account-level container for all your repos: `<account-id>.dkr.ecr.<region>.amazonaws.com`. One per account+region, created automatically — you never create this yourself. |
| **Repository** | A named collection of images, like a folder — e.g. `agentcore-commerce-bot`. This is the thing `ecr:CreateRepository` creates. Analogous to a repo on Docker Hub. |
| **Image** | A built container image — the actual filesystem + entrypoint from your `Dockerfile`. |
| **Tag** | A human-readable pointer to a specific image, e.g. `:latest`, `:v1.2.0`, or a git SHA. Pushing to the same tag again just moves the pointer — the old image digest still exists until garbage-collected. |
| **Digest** | The immutable content hash of an image (`sha256:...`) — the real identity of an image; tags are mutable labels on top of it. |
| **Repository policy** | A resource-based policy (like an S3 bucket policy) controlling *who/what* can pull or push *this specific repo*, separate from IAM identity policies. `pipeline.yaml` attaches one allowing the `bedrock-agentcore.amazonaws.com` service principal to pull — without it, AgentCore can create the runtime but fail at pull time. |
| **Lifecycle policy** | Auto-expiry rules for old images/tags, so the repo doesn't grow forever. `pipeline.yaml` keeps the last 10. |

### The permission split (why "why do I need X" kept coming up)

Two different roles touch ECR here, needing different permissions:

1. **Whoever/whatever *creates* the repository** (one-time, done by
   CloudFormation using the `hatbazar-api` credentials) needs
   `ecr:CreateRepository`, `SetRepositoryPolicy`, `PutLifecyclePolicy`,
   `PutImageScanningConfiguration`, `TagResource`.
2. **CodeBuild**, which runs on every pipeline trigger, only needs to
   *push* — `ecr:GetAuthorizationToken`, `BatchCheckLayerAvailability`,
   `PutImage`, `InitiateLayerUpload`, `UploadLayerPart`,
   `CompleteLayerUpload` (already scoped into `CodeBuildRole` in
   `pipeline.yaml` — nothing more to do there).

That's why attaching `AmazonEC2ContainerRegistryFullAccess` (or an
equivalent policy) to `hatbazar-api` unblocks step 1 — CodeBuild's own
narrower permissions were already set up correctly in the template.

### Handy commands, once the repo exists

```bash
# Authenticate Docker to ECR (token expires after 12h)
aws ecr get-login-password --region ap-south-1 \
  | docker login --username AWS --password-stdin <account-id>.dkr.ecr.ap-south-1.amazonaws.com

# List images in the repo
aws ecr list-images --repository-name agentcore-commerce-bot --region ap-south-1

# Manually build + push (what buildspec.yml automates)
docker build -t agentcore-commerce-bot .
docker tag agentcore-commerce-bot:latest <account-id>.dkr.ecr.ap-south-1.amazonaws.com/agentcore-commerce-bot:latest
docker push <account-id>.dkr.ecr.ap-south-1.amazonaws.com/agentcore-commerce-bot:latest
```

## The rest of the pipeline, briefly

- **CodePipeline** watches GitHub (via a CodeStar/CodeConnections
  connection — see below) and runs the pipeline on every push to the
  configured branch.
- **CodeBuild** runs `buildspec.yml`: builds the ARM64 image, pushes it to
  ECR, then runs `deploy_agent.py`, which creates/updates the AgentCore
  Runtime to point at the new image.
- **Secrets Manager** (`commerce-bot/agent-config`) holds the app's non-local
  config (model ids, guardrail, knowledge base, backend API URL) instead of
  committing `.env`. `deploy_agent.py` reads it and passes the values to
  AgentCore as `environmentVariables`.
- **The AgentCore execution role** (`commerce-bot-agentcore-execution-role`)
  is what the *running agent* assumes to call Bedrock, the guardrail, and
  the knowledge base — separate from the CodeBuild/CodePipeline roles, which
  only exist to build and deploy.

## Deploying the stack

```bash
aws cloudformation deploy \
  --template-file infra/pipeline.yaml \
  --stack-name commerce-bot-pipeline \
  --region ap-south-1 \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides KnowledgeBaseId=<your-kb-id>
```

Required IAM permissions for whoever runs this (one-time bootstrap, not
needed by CodeBuild/CodePipeline afterward):
`AWSCloudFormationFullAccess`, `IAMFullAccess` (to create the 3 roles),
`AmazonS3FullAccess`, `AWSCodeBuildAdminAccess`, `AWSCodePipeline_FullAccess`,
`AmazonEC2ContainerRegistryFullAccess`, `SecretsManagerReadWrite`, and a
policy covering `codestar-connections:CreateConnection`/`TagConnection`.

### After the stack is up — two manual steps

1. **Authorize the GitHub connection.** The `GitHubConnectionArn` output
   will be in `PENDING` status — AWS Console → Developer Tools → Settings →
   Connections → find `commerce-bot-github` → "Update pending connection" →
   install/authorize the GitHub App for `d3vjamal/e-commerce-bot`. This is a
   one-time OAuth handshake AWS requires a human to click through; it can't
   be scripted.

2. **Populate the config secret** (placeholder value only exists after
   `deploy`):
   ```bash
   aws secretsmanager put-secret-value \
     --secret-id commerce-bot/agent-config \
     --region ap-south-1 \
     --secret-string file://agent-config.json
   ```
   where `agent-config.json` mirrors `.env`'s non-AWS-credential keys, e.g.:
   ```json
   {
     "REGION": "ap-south-1",
     "ORCHESTRATOR_MODEL_ID": "...",
     "GUARDRAIL_ID": "...",
     "GUARDRAIL_VERSION": "DRAFT",
     "KNOWLEDGE_BASE_ID": "...",
     "BRAND_NAME": "HatBazaar",
     "ECOMMERCE_API_BASE_URL": "...",
     "ECOMMERCE_AUTH_SCHEME": "Bearer",
     "ECOMMERCE_API_TIMEOUT": "30"
   }
   ```
   Don't commit `agent-config.json` — delete it locally after running the
   command, same as `.env`.

Once both are done, a push to the configured branch triggers the pipeline
end to end.
