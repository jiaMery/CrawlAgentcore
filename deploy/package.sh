#!/usr/bin/env bash
# package.sh — Package the Lambda Custom Resource handler and upload to S3.
#
# Usage:
#   ./deploy/package.sh <S3_BUCKET> [S3_PREFIX] [REGION]
#
# This creates a ZIP of cfn_handler.py and uploads it to S3 so that
# cloudformation.yaml can reference it as the Lambda source.
# Run this ONCE before deploying the CloudFormation stack.

set -euo pipefail

S3_BUCKET="${1:?Usage: package.sh <S3_BUCKET> [S3_PREFIX] [REGION]}"
S3_PREFIX="${2:-crawl-agentcore/lambda}"
REGION="${3:-us-east-1}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ZIP_FILE="/tmp/cfn_handler.zip"

echo "Packaging Lambda handler..."
cd "$SCRIPT_DIR"
zip -j "$ZIP_FILE" cfn_handler.py
echo "Uploading to s3://${S3_BUCKET}/${S3_PREFIX}/cfn_handler.zip ..."
aws s3 cp "$ZIP_FILE" "s3://${S3_BUCKET}/${S3_PREFIX}/cfn_handler.zip" \
  --region "$REGION"

echo "Done."
echo ""
echo "Use these parameters when deploying cloudformation.yaml:"
echo "  LambdaS3Bucket=${S3_BUCKET}"
echo "  LambdaS3Key=${S3_PREFIX}/cfn_handler.zip"
