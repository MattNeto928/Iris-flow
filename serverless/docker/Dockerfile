# Iris Flow Video Generator - Serverless Container
# Based on Manim Community image with all rendering dependencies

FROM manimcommunity/manim:stable

# Switch to root for package installation
USER root

# Install system dependencies
# - sox: audio processing for manim-voiceover
# - tzdata: timezone support
# - libsndfile1: audio file handling
# - xvfb: virtual framebuffer for pygame/matplotlib
RUN apt-get update && apt-get install -y \
    sox \
    tzdata \
    libsndfile1 \
    xvfb \
    python3-tk \
    && rm -rf /var/lib/apt/lists/*

# Install Python packages for the pipeline
# Organized by service to match local containers

RUN pip install --no-cache-dir \
    # === main_service packages === #
    # Google AI for Gemini and Veo
    google-generativeai \
    google-genai \
    # Google Cloud for Chirp 3 HD TTS
    google-cloud-texttospeech \
    # AWS SDK
    boto3 \
    # HTTP client
    httpx \
    # Image processing
    Pillow \
    # Manim voiceover (for sound wave visualization)
    manim-voiceover \
    \
    # === pysim_service packages === #
    # Anthropic for Claude (script generation for all services)
    anthropic==0.40.0 \
    # Scientific computing (core)
    numpy==1.26.3 \
    scipy==1.12.0 \
    pandas==2.1.4 \
    matplotlib==3.8.2 \
    # Agent-based modeling
    mesa==2.1.4 \
    # 2D Physics simulation
    pymunk==6.6.0 \
    \
    # === NEW NODE TYPE SERVICES === #
    # Discrete event simulation (simpy_service)
    simpy \
    \
    # 3D plotting with static export (plotly_service)
    plotly \
    kaleido \
    \
    # Graph algorithms (networkx_service)
    networkx \
    \
    # Audio/signal processing (audio_service)
    librosa \
    soundfile \
    \
    # Statistics & visualization (stats_service)
    seaborn \
    statsmodels \
    \
    # JIT compilation for fractals (fractal_service)
    numba \
    \
    # Geographic visualization (geo_service)
    cartopy \
    geopandas \
    \
    # Chemistry/molecular (chem_service) - PyPI version for easier install
    rdkit-pypi \
    \
    # Astronomy (astro_service)
    astropy \
    skyfield \
    \
    # === manim_service packages === #
    # manim already included in base image
    aiofiles==23.2.1

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

# Entry point - run the main handler
CMD ["python", "-m", "src.handler"]
