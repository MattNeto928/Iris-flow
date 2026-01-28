#!/bin/bash
# Build and push Docker image to ECR

set -e

echo "🐳 Building and Pushing Iris Flow Docker Image"
echo "================================================"

# Get AWS account and region
AWS_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
AWS_REGION=${AWS_REGION:-us-east-1}
ECR_REPO="${AWS_ACCOUNT}.dkr.ecr.${AWS_REGION}.amazonaws.com/iris-flow-generator"

echo "Account: ${AWS_ACCOUNT}"
echo "Region: ${AWS_REGION}"
echo "ECR Repo: ${ECR_REPO}"

# Login to ECR
echo "🔐 Logging in to ECR..."
aws ecr get-login-password --region ${AWS_REGION} | docker login --username AWS --password-stdin ${ECR_REPO}

# Build the image for linux/amd64 (required for Fargate)
# This is critical when building on Mac (arm64) for Linux containers
echo "🔨 Building Docker image for linux/amd64..."
cd "$(dirname "$0")"
docker build --platform linux/amd64 -f docker/Dockerfile -t iris-flow-generator .

# Tag and push
echo "📤 Pushing to ECR..."
docker tag iris-flow-generator:latest ${ECR_REPO}:latest
docker push ${ECR_REPO}:latest

echo ""
echo "✅ Docker image pushed successfully!"
echo "Image: ${ECR_REPO}:latest"
