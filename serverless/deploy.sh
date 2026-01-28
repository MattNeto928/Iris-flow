#!/bin/bash
# Deploy CDK stack for Iris Flow serverless infrastructure

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CDK_DIR="$SCRIPT_DIR/cdk"

echo "=== Deploying Iris Flow Serverless Stack ==="

cd "$CDK_DIR"

# Install dependencies if needed
if [ ! -d "node_modules" ]; then
    echo "Installing CDK dependencies..."
    npm install
fi

# Build TypeScript
echo "Building TypeScript..."
npm run build

# Bootstrap CDK (needed for first-time deployment)
echo "Bootstrapping CDK (if needed)..."
npx cdk bootstrap --region us-east-1 2>/dev/null || true

# Deploy
echo "Deploying stack..."
npx cdk deploy --require-approval never

echo ""
echo "=== Deployment Complete ==="
echo ""
echo "Next steps:"
echo "1. Add API keys to Secrets Manager:"
echo "   aws secretsmanager put-secret-value \\"
echo "     --secret-id iris-flow/api-keys \\"
echo '     --secret-string '"'"'{'
echo '       "GOOGLE_AI_API_KEY": "your-gemini-key",'
echo '       "ANTHROPIC_API_KEY": "your-anthropic-key",'
echo '       "GCP_SERVICE_ACCOUNT_KEY": "base64-encoded-json-key",'
echo '       "METRICOOL_API_KEY": "your-metricool-key",'
echo '       "METRICOOL_USER_ID": "your-user-id",'
echo '       "METRICOOL_BLOG_ID": "your-blog-id"'
echo "     }'"
echo ""
echo "2. Build and push Docker image:"
echo "   ./build-and-push.sh"
