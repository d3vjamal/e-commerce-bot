#!/usr/bin/env bash
# Apply infra/agentcore-role.yaml to the commerce-bot-agentcore-role stack.
set -euo pipefail
cd "$(dirname "$0")/.."

aws cloudformation update-stack \
  --stack-name commerce-bot-agentcore-role \
  --region ap-south-1 \
  --template-body file://infra/agentcore-role.yaml \
  --parameters ParameterKey=KnowledgeBaseId,ParameterValue=WAGW4RXPZ7 \
  --capabilities CAPABILITY_NAMED_IAM

aws cloudformation wait stack-update-complete \
  --stack-name commerce-bot-agentcore-role \
  --region ap-south-1

aws cloudformation describe-stacks \
  --stack-name commerce-bot-agentcore-role \
  --region ap-south-1 \
  --query 'Stacks[0].StackStatus' --output text
