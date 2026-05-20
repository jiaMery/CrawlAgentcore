#!/usr/bin/env bash
# deploy.sh — One-click deployment helper for CrawlAgentcore on AWS
#
# Usage:
#   ./deploy/deploy.sh [STACK_NAME] [REGION]
#
# Prerequisites:
#   - AWS CLI configured (aws configure)
#   - Docker with buildx (for local image builds)
#   - Git repository cloned locally
#
# What it does:
#   1. Validates the CloudFormation template
#   2. Deploys the stack (creates all AWS resources)
#   3. Triggers CodeBuild to build and push the arm64 Docker image
#   4. Waits for the image build to complete
#   5. Updates the AgentCore Runtime with the new image (via stack update)
#   6. Prints connection info and a sample invocation command
#
# Notes:
#   - First deployment takes ~15–20 minutes (CodeBuild arm64 build + AgentCore provision)
#   - AgentCore resources (Runtime, Browser, Code Interpreter) are provisioned
#     via Lambda-backed Custom Resources — they poll until READY.

set -euo pipefail

STACK_NAME="${1:-crawl-agentcore}"
REGION="${2:-us-east-1}"
LAMBDA_S3_BUCKET="${3:-}"  # Required: S3 bucket for Lambda ZIP
TEMPLATE="$(dirname "$0")/cloudformation.yaml"
PROJECT_NAME="${STACK_NAME}"

# ── Colors ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'

info()    { echo -e "${BLUE}[INFO]${NC} $*"; }
success() { echo -e "${GREEN}[OK]${NC}   $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
die()     { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

# ── Preflight ─────────────────────────────────────────────────────────────────
command -v aws    >/dev/null 2>&1 || die "aws CLI not found. Install from https://aws.amazon.com/cli/"
command -v docker >/dev/null 2>&1 || warn "docker not found — CodeBuild will build the image instead"
command -v zip    >/dev/null 2>&1 || die "zip not found. Install zip (e.g. apt install zip)."

[[ -n "$LAMBDA_S3_BUCKET" ]] || \
  die "Usage: $0 [STACK_NAME] [REGION] <LAMBDA_S3_BUCKET>\n  LAMBDA_S3_BUCKET: an existing S3 bucket to upload the Lambda handler ZIP."

ACCOUNT=$(aws sts get-caller-identity --query Account --output text --region "$REGION" 2>/dev/null) \
  || die "AWS credentials not configured. Run 'aws configure' first."

info "Deploying ${STACK_NAME} to account ${ACCOUNT} / ${REGION}"
info "Lambda artifacts bucket: ${LAMBDA_S3_BUCKET}"
info "Template: ${TEMPLATE}"

# ── Step 1: Package and upload Lambda handler ─────────────────────────────────
LAMBDA_S3_KEY="crawl-agentcore/lambda/cfn_handler.zip"
info "Packaging Lambda Custom Resource handler..."
"$(dirname "$0")/package.sh" "$LAMBDA_S3_BUCKET" "crawl-agentcore/lambda" "$REGION"
success "Lambda handler uploaded."

# ── Step 2: Validate template ─────────────────────────────────────────────────
info "Validating CloudFormation template..."
aws cloudformation validate-template \
  --template-body "file://${TEMPLATE}" \
  --region "$REGION" >/dev/null
success "Template valid."

# ── Step 3: Deploy stack ──────────────────────────────────────────────────────
info "Deploying CloudFormation stack '${STACK_NAME}'..."
info "(This creates IAM roles, ECR, Lambda handler, CloudWatch, CodeBuild.)"
info "(AgentCore resources are provisioned next — takes ~10 min.)"

aws cloudformation deploy \
  --template-file "$TEMPLATE" \
  --stack-name    "$STACK_NAME" \
  --region        "$REGION" \
  --capabilities  CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    "ProjectName=${PROJECT_NAME}" \
    "LambdaS3Bucket=${LAMBDA_S3_BUCKET}" \
    "LambdaS3Key=${LAMBDA_S3_KEY}" \
  --no-fail-on-empty-changeset

success "Stack deployed."

# ── Step 4: Get outputs ────────────────────────────────────────────────────────
info "Fetching stack outputs..."

get_output() {
  aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" \
    --output text
}

ECR_URI=$(get_output EcrRepositoryUri)
CODEBUILD_PROJECT=$(get_output CodeBuildProjectName)
RUNTIME_ARN=$(get_output AgentRuntimeArn)
ENDPOINT_NAME=$(get_output EndpointName)
CI_ID=$(get_output CodeInterpreterId)
BR_ID=$(get_output BrowserId)

success "ECR:           ${ECR_URI}"
success "CodeBuild:     ${CODEBUILD_PROJECT}"
success "Runtime ARN:   ${RUNTIME_ARN}"
success "Endpoint:      ${ENDPOINT_NAME}"
success "CI ID:         ${CI_ID}"
success "Browser ID:    ${BR_ID}"

# ── Step 5: Build Docker image ────────────────────────────────────────────────
info "Triggering CodeBuild to build the arm64 Docker image..."
BUILD_ID=$(aws codebuild start-build \
  --project-name "$CODEBUILD_PROJECT" \
  --region "$REGION" \
  --query 'build.id' \
  --output text)

info "Build ID: ${BUILD_ID}"
info "Waiting for build to complete (may take 10–15 minutes)..."

while true; do
  STATUS=$(aws codebuild batch-get-builds \
    --ids "$BUILD_ID" \
    --region "$REGION" \
    --query 'builds[0].buildStatus' \
    --output text)
  case "$STATUS" in
    SUCCEEDED)
      success "Docker image built and pushed to ECR."; break ;;
    FAILED|FAULT|STOPPED|TIMED_OUT)
      die "CodeBuild failed with status: ${STATUS}. Check the build logs in the AWS Console." ;;
    *)
      echo -n "."; sleep 20 ;;
  esac
done
echo

# ── Step 6: Print usage ───────────────────────────────────────────────────────
echo
echo -e "${GREEN}════════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  CrawlAgentcore deployed successfully!${NC}"
echo -e "${GREEN}════════════════════════════════════════════════════════════════${NC}"
echo
echo "  Runtime ARN : ${RUNTIME_ARN}"
echo "  Endpoint    : ${ENDPOINT_NAME}"
echo "  Region      : ${REGION}"
echo
echo "  Invoke example:"
echo "    python crawler_cli.py --cloud \"爬取豆瓣电影TOP250\""
echo
echo "  Or with boto3:"
echo "    import boto3, json"
echo "    client = boto3.client('bedrock-agentcore', region_name='${REGION}')"
echo "    resp = client.invoke_agent_runtime("
echo "        agentRuntimeArn='${RUNTIME_ARN}',"
echo "        qualifier='${ENDPOINT_NAME}',"
echo "        runtimeSessionId='session-1',"
echo "        contentType='application/json',"
echo "        accept='application/json',"
echo "        payload=json.dumps({'prompt': '爬取豆瓣TOP250'}).encode(),"
echo "    )"
echo
echo "  Update crawler_cli.py AGENT_RUNTIME_ARN and ENDPOINT_QUALIFIER with"
echo "  the values above, or pass them via environment variables:"
echo "    export AGENTCORE_RUNTIME_ARN='${RUNTIME_ARN}'"
echo "    export AGENTCORE_ENDPOINT='${ENDPOINT_NAME}'"
echo
