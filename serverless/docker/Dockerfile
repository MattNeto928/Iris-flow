# Iris Flow Video Generator - Serverless Container
# Based on Manim Community image with all rendering dependencies

FROM manimcommunity/manim:v0.19.0

# Switch to root for package installation
USER root

# Install system dependencies
# - sox: audio processing for manim-voiceover
# - tzdata: timezone support
# - libsndfile1: audio file handling
# - xvfb: virtual framebuffer for pygame/matplotlib
# NOTE: Node.js/pnpm and Google Chrome were previously installed here for the
# Remotion engine and Kaleido v1. Both are now removed: the live engines are
# matplotlib/manim/plotly only (Remotion is not in worker.py's SERVICE_MAP), and
# the pinned kaleido==0.2.1 bundles its own headless Chromium. Dropping them also
# removes the build's dependency on deb.nodesource.com / npm registry / dl.google.com,
# which are not reliably reachable from the build sandbox.
RUN apt-get update && apt-get install -y \
    ffmpeg \
    sox \
    tzdata \
    libsndfile1 \
    xvfb \
    python3-tk \
    wget \
    gnupg \
    libgeos-dev \
    libproj-dev \
    curl \
    build-essential \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Install Python packages for the pipeline
# Organized by service to match local containers

# Layer 1: Core Scientific & Data
# numpy/scipy/pandas/matplotlib come pre-installed in the manim base image; only add what's missing
RUN pip install --no-cache-dir \
    boto3 \
    httpx \
    Pillow \
    aiofiles==23.2.1

# Layer 2: ML & AI integration
# google-genai>=1.73 required for gemini-3.1-flash-tts-preview (Algenib voice).
RUN pip install --no-cache-dir \
    "google-genai>=1.73" \
    google-cloud-texttospeech \
    anthropic>=0.79.0 \
    fal-client

# Layer 3: Simulation & Visualization
# NOTE: plotly==5.24.1 + kaleido==0.2.1 are PINNED on purpose. Kaleido 0.2.1 bundles
# its own headless Chromium and supports fig.write_image(engine='kaleido'), which is
# fast and hang-free for the per-frame 3D export this pipeline does. Kaleido v1.x
# dropped the bundled Chrome, deprecated the engine= arg, and has documented hangs on
# 3D-figure export in headless containers — leaving these unpinned would let a rebuild
# pull v1 and silently break every Plotly segment. See src/services/plotly_service.py.
RUN pip install --no-cache-dir \
    mesa==2.1.4 \
    pymunk==6.6.0 \
    simpy \
    "plotly==5.24.1" \
    "kaleido==0.2.1" \
    networkx \
    seaborn \
    statsmodels \
    numba \
    manim-voiceover \
    cartopy \
    geopandas \
    shapely

# Layer 4: Audio & Signal Processing
RUN pip install --no-cache-dir \
    librosa \
    soundfile \
    mutagen

# (Remotion base app pre-bake removed: Remotion is dead code — not in
# worker.py's SERVICE_MAP — and its npm install needs registry egress the
# build sandbox lacks. Live engines are matplotlib/manim/plotly only.)

# Set working directory
WORKDIR /app

# Copy source code
COPY src/ ./src/

# Set Python path and environment
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV CI=true

# Create output directories matching local container paths
RUN mkdir -p /app/output /app/output/audio /app/output/videos /app/output/combined \
    /app/output/frames /app/output/manim_scripts /app/output/manim_videos \
    /app/media /app/generated_files /app/videos

# Entry point - Batch worker (routes by JOB_TYPE env var)
CMD ["python", "-m", "src.worker"]
