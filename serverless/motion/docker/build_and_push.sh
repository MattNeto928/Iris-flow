#!/usr/bin/env bash
#
# Build the iris-motion renderer and push it to ECR.
#
#   ./docker/build_and_push.sh            # tags <short-sha> and latest
#   ./docker/build_and_push.sh v3         # tags v3 and latest
#
# Safe to re-run: the repository is created only when it is missing, the login is
# stateless, and the build is an ordinary cached docker build. Nothing here
# deploys — the CDK stack owns Batch, Step Functions and the job definitions.
#
# Never add `set -x`. The ECR authorization token crosses this script on a pipe
# and tracing would print it into the terminal scrollback and any CI log.

set -euo pipefail

ACCOUNT=482625028438
REGION="${AWS_REGION:-us-east-1}"
REPO=iris-motion-renderer
REGISTRY="${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com"
IMAGE="${REGISTRY}/${REPO}"

# Context is motion/: the Dockerfile COPYs app/, a sibling of docker/.
cd "$(dirname "$0")/.."

# Tag with the commit so a Batch job definition can be pinned to an exact build.
# :latest moves too, because that is what the stack references.
TAG="${1:-}"
if [ -z "${TAG}" ]; then
  TAG="$(git rev-parse --short HEAD 2>/dev/null || echo nogit)"
  git diff --quiet HEAD 2>/dev/null || TAG="${TAG}-dirty"
fi

# The image's CMD is `python3 /app/worker.py`. Pushing without it produces an
# image that pulls fine and then dies on the first Batch job.
if [ ! -f app/worker.py ]; then
  echo "ERROR: app/worker.py is missing — nothing to run in the container." >&2
  exit 1
fi

# docker reads an ignore file at the context root or named after the Dockerfile,
# never docker/.dockerignore. Regenerate the name it does read, every run, so the
# two can never drift apart.
cp -f docker/.dockerignore docker/Dockerfile.dockerignore

echo "==> account ${ACCOUNT}  region ${REGION}  repo ${REPO}"
echo "==> tags   ${TAG}, latest"

# Refuse to push into the wrong account. Whatever credentials are in the
# environment win over anything written here, and iris-flow-generator — the
# production STEM image — lives one repository away.
CALLER_ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
if [ "${CALLER_ACCOUNT}" != "${ACCOUNT}" ]; then
  echo "ERROR: credentials are for account ${CALLER_ACCOUNT}, expected ${ACCOUNT}." >&2
  exit 1
fi

# describe-repositories is the idempotency check; the create is still guarded
# because two concurrent runs can both see it missing and only one wins.
if ! aws ecr describe-repositories --region "${REGION}" \
       --repository-names "${REPO}" > /dev/null 2>&1; then
  echo "==> creating ECR repository ${REPO}"
  aws ecr create-repository \
    --region "${REGION}" \
    --repository-name "${REPO}" \
    --image-tag-mutability MUTABLE \
    --image-scanning-configuration scanOnPush=true \
    > /dev/null \
  || aws ecr describe-repositories --region "${REGION}" \
       --repository-names "${REPO}" > /dev/null
fi

# --password-stdin: the token must never reach argv, where any process on the box
# can read it out of `ps`.
echo "==> docker login ${REGISTRY}"
aws ecr get-login-password --region "${REGION}" \
  | docker login --username AWS --password-stdin "${REGISTRY}"

# --platform linux/amd64 explicitly: Fargate runs x86_64 and this is normally
# built on an arm64 Mac, where the default would silently produce an arm64 image
# that Batch rejects at pull time with a manifest error. Chrome's postinst and
# npm run under QEMU, so a cold build takes minutes; the layer cache makes an
# app-only rebuild fast.
echo "==> building ${IMAGE}:${TAG} for linux/amd64"
docker build \
  --platform linux/amd64 \
  -f docker/Dockerfile \
  -t "${IMAGE}:${TAG}" \
  .

docker tag "${IMAGE}:${TAG}" "${IMAGE}:latest"

echo "==> pushing"
docker push "${IMAGE}:${TAG}"
docker push "${IMAGE}:latest"

echo "==> pushed ${IMAGE}:${TAG}"

# The one thing this script cannot verify from a Mac: that Chrome comes up on
# SwiftShader. QEMU-emulating a headless Chrome proves nothing either way, so
# check it on real x86_64 — a scratch Batch job, or an amd64 host:
#
#   docker run --rm ${IMAGE}:${TAG} node -e "const p=require('/app/node_modules/puppeteer-core');\
#   (async()=>{const b=await p.launch({executablePath:process.env.CHROME_PATH,headless:'shell'});\
#   const g=await (await b.newPage()).evaluate(()=>{const c=document.createElement('canvas');\
#   const x=c.getContext('webgl2');return x?x.getParameter(x.RENDERER):'NO WEBGL'});\
#   console.log(g);await b.close()})()"
#
# Expect a SwiftShader/ANGLE renderer string. 'NO WEBGL' means the GL flags did
# not take; a launch timeout means --no-sandbox did not.

# imageSizeInBytes is the compressed layer total — the number that decides how
# long each of the 8 render shards waits on its pull.
aws ecr describe-images \
  --region "${REGION}" \
  --repository-name "${REPO}" \
  --image-ids "imageTag=${TAG}" \
  --query 'imageDetails[0].{pushedAt:imagePushedAt,compressedBytes:imageSizeInBytes}' \
  --output table
