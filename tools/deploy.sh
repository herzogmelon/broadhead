#!/usr/bin/env bash
# ── Broadhead Automations — Lambda Deploy Script ─────────────────────────────
# Deploys chat-server to AWS Lambda + API Gateway (HTTP API)
#
# Prerequisites:
#   - AWS CLI installed (aws --version)
#   - AWS CLI configured (aws configure)
#   - Node.js 20+ installed
#
# Usage (from the Broadhead project root):
#   bash tools/deploy.sh
# ─────────────────────────────────────────────────────────────────────────────

set -e  # Exit on any error

# ── Config — edit these if needed ────────────────────────────────────────────
FUNCTION_NAME="broadhead-aria-chat"
REGION="us-east-1"          # Change to your preferred AWS region
RUNTIME="nodejs20.x"
MEMORY=256
TIMEOUT=30                  # seconds (Claude API can take a few seconds)

# ── Load env vars from .env ───────────────────────────────────────────────────
if [ ! -f .env ]; then
  echo "ERROR: .env file not found. Run this script from the Broadhead project root."
  exit 1
fi

# Read env vars (skip comment lines and blanks)
ANTHROPIC_API_KEY=$(grep '^ANTHROPIC_API_KEY=' .env | cut -d'=' -f2-)
GMAIL_USER=$(grep '^GMAIL_USER=' .env | cut -d'=' -f2-)
GMAIL_APP_PASS=$(grep '^GMAIL_APP_PASS=' .env | cut -d'=' -f2-)
LEAD_EMAIL_TO=$(grep '^LEAD_EMAIL_TO=' .env | cut -d'=' -f2-)
NOTION_API_KEY=$(grep '^NOTION_API_KEY=' .env | cut -d'=' -f2-)
NOTION_LEADS_DB_ID=$(grep '^NOTION_LEADS_DB_ID=' .env | cut -d'=' -f2-)

# Validate required vars are present
for VAR in ANTHROPIC_API_KEY GMAIL_USER GMAIL_APP_PASS LEAD_EMAIL_TO; do
  if [ -z "${!VAR}" ]; then
    echo "ERROR: $VAR is empty in .env — fill it in before deploying."
    exit 1
  fi
done

echo "==> Building Lambda package..."

# ── Build in a temp directory ─────────────────────────────────────────────────
BUILD_DIR=".lambda-build"
rm -rf "$BUILD_DIR"
mkdir "$BUILD_DIR"

# Copy Lambda handler and package.json
cp tools/lambda.js "$BUILD_DIR/lambda.js"
cp package.json "$BUILD_DIR/package.json"

# Install production dependencies only
cd "$BUILD_DIR"
npm install --omit=dev --silent
cd ..

# Zip it up
ZIP_FILE="aria-lambda.zip"
rm -f "$ZIP_FILE"
cd "$BUILD_DIR"
zip -r "../$ZIP_FILE" . --quiet
cd ..
rm -rf "$BUILD_DIR"

echo "==> Package built: $ZIP_FILE ($(du -sh $ZIP_FILE | cut -f1))"

# ── Check if IAM role exists, create if not ───────────────────────────────────
ROLE_NAME="broadhead-lambda-role"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"

if ! aws iam get-role --role-name "$ROLE_NAME" &>/dev/null; then
  echo "==> Creating IAM role: $ROLE_NAME..."
  aws iam create-role \
    --role-name "$ROLE_NAME" \
    --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}' \
    --output text --query 'Role.Arn' > /dev/null

  aws iam attach-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-arn "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"

  echo "==> Waiting for role to propagate..."
  sleep 10
fi

# ── Deploy Lambda function ────────────────────────────────────────────────────
ENV_VARS="Variables={ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY,GMAIL_USER=$GMAIL_USER,GMAIL_APP_PASS=$GMAIL_APP_PASS,LEAD_EMAIL_TO=$LEAD_EMAIL_TO,NOTION_API_KEY=$NOTION_API_KEY,NOTION_LEADS_DB_ID=$NOTION_LEADS_DB_ID}"

if aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" &>/dev/null; then
  echo "==> Updating existing Lambda function..."
  aws lambda update-function-code \
    --function-name "$FUNCTION_NAME" \
    --zip-file "fileb://$ZIP_FILE" \
    --region "$REGION" \
    --output text --query 'FunctionArn' > /dev/null

  aws lambda wait function-updated \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION"

  aws lambda update-function-configuration \
    --function-name "$FUNCTION_NAME" \
    --environment "$ENV_VARS" \
    --region "$REGION" \
    --output text --query 'FunctionArn' > /dev/null
else
  echo "==> Creating Lambda function..."
  aws lambda create-function \
    --function-name "$FUNCTION_NAME" \
    --runtime "$RUNTIME" \
    --role "$ROLE_ARN" \
    --handler "lambda.handler" \
    --zip-file "fileb://$ZIP_FILE" \
    --memory-size "$MEMORY" \
    --timeout "$TIMEOUT" \
    --environment "$ENV_VARS" \
    --region "$REGION" \
    --output text --query 'FunctionArn' > /dev/null

  aws lambda wait function-active \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION"
fi

echo "==> Lambda deployed."

# ── Create or retrieve API Gateway HTTP API ───────────────────────────────────
API_ID=$(aws apigatewayv2 get-apis --region "$REGION" \
  --query "Items[?Name=='broadhead-aria-api'].ApiId" \
  --output text)

if [ -z "$API_ID" ]; then
  echo "==> Creating API Gateway..."
  API_ID=$(aws apigatewayv2 create-api \
    --name "broadhead-aria-api" \
    --protocol-type HTTP \
    --cors-configuration \
      AllowOrigins='["*"]',AllowMethods='["POST","OPTIONS"]',AllowHeaders='["Content-Type"]' \
    --region "$REGION" \
    --query 'ApiId' --output text)

  # Create Lambda integration
  FUNCTION_ARN=$(aws lambda get-function \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION" \
    --query 'Configuration.FunctionArn' --output text)

  INTEGRATION_ID=$(aws apigatewayv2 create-integration \
    --api-id "$API_ID" \
    --integration-type AWS_PROXY \
    --integration-uri "$FUNCTION_ARN" \
    --payload-format-version "2.0" \
    --region "$REGION" \
    --query 'IntegrationId' --output text)

  # Create routes
  aws apigatewayv2 create-route \
    --api-id "$API_ID" \
    --route-key "POST /chat" \
    --target "integrations/$INTEGRATION_ID" \
    --region "$REGION" > /dev/null

  aws apigatewayv2 create-route \
    --api-id "$API_ID" \
    --route-key "GET /health" \
    --target "integrations/$INTEGRATION_ID" \
    --region "$REGION" > /dev/null

  # Create default stage with auto-deploy
  aws apigatewayv2 create-stage \
    --api-id "$API_ID" \
    --stage-name '$default' \
    --auto-deploy \
    --region "$REGION" > /dev/null

  # Grant API Gateway permission to invoke Lambda
  aws lambda add-permission \
    --function-name "$FUNCTION_NAME" \
    --statement-id "apigateway-invoke" \
    --action "lambda:InvokeFunction" \
    --principal "apigateway.amazonaws.com" \
    --source-arn "arn:aws:execute-api:${REGION}:${ACCOUNT_ID}:${API_ID}/*/*" \
    --region "$REGION" > /dev/null
fi

# ── Get the live URL ──────────────────────────────────────────────────────────
API_URL=$(aws apigatewayv2 get-api \
  --api-id "$API_ID" \
  --region "$REGION" \
  --query 'ApiEndpoint' --output text)

# ── Cleanup ───────────────────────────────────────────────────────────────────
rm -f "$ZIP_FILE"

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "✓ Aria is live!"
echo ""
echo "  API URL: $API_URL"
echo ""
echo "  Next step — update index.html:"
echo "  Change:  const API_BASE = 'http://localhost:3001';"
echo "  To:      const API_BASE = '$API_URL';"
echo ""
echo "  Test it:  curl -X POST $API_URL/chat \\"
echo "    -H 'Content-Type: application/json' \\"
echo "    -d '{\"messages\":[{\"role\":\"user\",\"content\":\"hello\"}]}'"
