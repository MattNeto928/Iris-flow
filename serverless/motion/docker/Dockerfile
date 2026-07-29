# iris-motion renderer — one image, three JOB_TYPEs (prep | render | stitch).
#
# Deliberately NOT built on manimcommunity/manim like serverless/docker/Dockerfile:
# that base is 5+ GB and nothing here uses manim. A render fans out to 8 Fargate
# shards and every one of them pays the ECR pull, so image size is both latency
# and money. This lands near 1.15 GB unpacked / ~460 MB pulled.
#
# Layer order is load-bearing: apt -> chrome -> node -> pip -> npm -> COPY app/.
# Editing a scene or worker.py rebuilds only the last two, ~200 kB layers.
#
# Build context is motion/ :  docker build -f docker/Dockerfile .

# Node 20 is lifted out of the official image rather than installed from the
# NodeSource apt repo: same bookworm glibc, no third-party apt source, and no
# gnupg/dirmngr chain (~25 MB) left behind in the runtime image.
FROM node:20-bookworm-slim AS node20

FROM python:3.12-slim-bookworm

ARG DEBIAN_FRONTEND=noninteractive

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

# ffmpeg carries ffprobe; narrate.py concatenates the voice segments with it and
# stitch encodes with it. Debian's build has libx264, which rule 7 needs.
# Fonts: the pieces draw captions onto a 2D canvas with
# '"Helvetica Neue", Helvetica, Arial, sans-serif' and fit them with measureText,
# so the substitute has to be metric-compatible or every fitted caption size
# shifts — that is fonts-liberation (fontconfig aliases Arial to it).
# fonts-dejavu-core is for glyph coverage, not metrics: arrows, °, ±, µ and Greek
# turn into tofu boxes on a science caption without it, and nothing in the gates
# can see that.
# tini: chrome forks a zygote plus a process per renderer and PID 1 here is
# python, which never reaps. tini also forwards SIGTERM to the whole tree, which
# is what a spot reclaim sends.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates \
      curl \
      ffmpeg \
      fonts-liberation \
      fonts-dejavu-core \
      tini \
 && rm -rf /var/lib/apt/lists/*

# Chrome from the direct .deb rather than dl.google.com's apt repo — same
# publisher, but it saves a second package index and the gnupg needed to verify
# the repo signature. apt still resolves the deb's own dependency tree, so the
# libnss3/libgbm1/libxkbcommon0 shopping list does not have to be maintained here.
# The locale paks are ~45 MB of UI strings for a browser that renders no UI.
# en-US.pak must stay: chrome aborts at startup when its own locale pak is absent.
# Do NOT prune /opt/google/chrome/libvk_swiftshader.so or vk_swiftshader_icd.json
# for the 40 MB they cost — Fargate has no GPU and they are the whole rasteriser.
RUN curl -fsSL -o /tmp/chrome.deb \
      https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
 && apt-get update \
 && apt-get install -y --no-install-recommends /tmp/chrome.deb \
 && rm -f /tmp/chrome.deb \
 && rm -rf /var/lib/apt/lists/* \
 && if [ -d /opt/google/chrome/locales ]; then \
      find /opt/google/chrome/locales -type f ! -name 'en-US.pak' -delete; \
    fi

# render.mjs hardcodes the macOS launch flags (--use-angle=metal) and never asks
# for --no-sandbox, so on Fargate chrome would refuse to start as root and, if it
# did start, would not be on a defined GL path. This wrapper appends the Linux
# flags from CONTRACT.md rule 6 after puppeteer's argv; base::CommandLine keeps
# the LAST occurrence of a switch, so --use-angle=swiftshader here beats the
# --use-angle=metal that render.mjs passes. Both /usr/bin names the deb installs
# are repointed at the wrapper because render.mjs probes those two paths by hand
# whenever CHROME_PATH is unset.
RUN printf '%s\n' \
      '#!/bin/sh' \
      'exec /opt/google/chrome/google-chrome "$@" --use-gl=angle --use-angle=swiftshader --enable-unsafe-swiftshader --no-sandbox --disable-dev-shm-usage' \
      > /usr/local/bin/chrome-swiftshader \
 && chmod +x /usr/local/bin/chrome-swiftshader \
 && ln -sf /usr/local/bin/chrome-swiftshader /usr/bin/google-chrome \
 && ln -sf /usr/local/bin/chrome-swiftshader /usr/bin/google-chrome-stable

# CHROME_PATH is the name render.mjs reads (CANDIDATES[0]), so a bare
# `node /app/render.mjs` gets the Linux flags with no Python in the loop.
# CHROME_BINARY is the name app/common.py reads: it builds its own launcher at
# runtime and would otherwise resolve "the real chrome" to the wrapper above and
# stack a second identical set of flags on top. Pointing it at the deb's own
# launcher keeps that chain one link long.
# PUPPETEER_DANGEROUS_NO_SANDBOX is puppeteer-core's switch for putting
# --no-sandbox into its default args; the wrapper covers it too, but this keeps
# the flag in the argv puppeteer prints when a launch fails.
ENV CHROME_PATH=/usr/local/bin/chrome-swiftshader \
    CHROME_BINARY=/opt/google/chrome/google-chrome \
    PUPPETEER_DANGEROUS_NO_SANDBOX=true

COPY --from=node20 /usr/local/bin/node /usr/local/bin/node
COPY --from=node20 /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm

# google-genai>=1.73 is the floor for gemini-3.1-flash-tts-preview (Algenib
# voice); anthropic>=0.79.0 the floor for Opus 5. numpy and Pillow are what
# check.py's gates run on.
RUN pip install --no-cache-dir \
      boto3 \
      "numpy>=1.26,<3" \
      "Pillow>=10" \
      "google-genai>=1.73" \
      "anthropic>=0.79.0"

WORKDIR /app

# package.json is copied alone so this layer survives an app-code edit.
COPY docker/package.json /app/package.json

# The /node_modules symlink is not a duplicate of /app/node_modules: render.mjs
# and serve.mjs both compute ROOT as dirname(<self>)/.., so with the app at /app
# the static server's document root is "/", and the piece's importmap asks the
# browser for "/node_modules/three/build/three.module.js". Without this the three
# import 404s, render.mjs collects the HTTP error and exits 1 before frame 0.
# Node needs no help — it resolves bare specifiers from /app/node_modules.
RUN npm install --omit=dev --no-audit --no-fund \
 && npm cache clean --force \
 && ln -s /app/node_modules /node_modules

# Last, so that a scene edit never rebuilds Chrome.
COPY app/ /app/

# Job scratch. Anything the browser has to fetch must sit under "/" — the
# document root above — which is why common.py's workdir() is SERVE_ROOT/work/<id>
# and it hands render.mjs the relative `--page work/<id>/piece.html`. Created
# here so the layout is visible in the image rather than only in the code.
RUN mkdir -p /work

# Fail the build instead of the first Fargate job. Syntax and presence only: no
# app code runs and Chrome is never launched here, because this image is built
# for linux/amd64 on an arm64 Mac and a real headless launch under QEMU proves
# nothing about Fargate either way. compileall doubles as the .pyc warm-up for a
# cold container; node_modules is excluded because third-party packages ship
# their own stray .py files.
RUN node --check /app/render.mjs \
 && node --check /app/serve.mjs \
 && python3 -m compileall -q /app -x 'node_modules' \
 # Only the WORKER modules: the lambdas run in Lambda, not in this image,
 # and they read their env at import time by design (fail fast on a cold
 # start). plan_shards carries its own env-free self-test, run separately.
 # compileall only COMPILES -- it never runs module scope, so a missing import
 # used at import time (a NameError on os.environ in a module constant) sails
 # through it and fails on the first Batch job instead. Importing every worker
 # module for real is the check that would have caught exactly that.
 && MOTION_BUCKET=build-check AWS_DEFAULT_REGION=us-east-1 AWS_REGION=us-east-1 \
    python3 -c "import sys; sys.path.insert(0,'/app'); \
      import common, tts, narrate, render_shard, stitch, postprocess, prep, worker, \
             postcopy, slides, metricool_client, compile_video, winners; \
      print('all worker modules import')" \
 && ffmpeg -version > /dev/null \
 && ffprobe -version > /dev/null

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python3", "/app/worker.py"]
