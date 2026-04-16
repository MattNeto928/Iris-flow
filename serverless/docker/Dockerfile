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
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && npm install -g pnpm \
    && rm -rf /var/lib/apt/lists/*

# Install Google Chrome for Kaleido
RUN wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update && apt-get install -y google-chrome-stable \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && npm install -g pnpm \
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
RUN pip install --no-cache-dir \
    mesa==2.1.4 \
    pymunk==6.6.0 \
    simpy \
    plotly \
    kaleido \
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

# Pre-bake Remotion base app — write project files directly (no interactive scaffolding)
RUN mkdir -p /app/output/remotion_projects/base_app/src && \
    cd /app/output/remotion_projects/base_app && \
    printf '{\n  "name": "iris-remotion","version":"1.0.0","private":true,\n  "scripts":{"build":"tsc","render":"remotion render"},\n  "dependencies":{\n    "remotion":"^4.0.0","@remotion/renderer":"^4.0.0","@remotion/cli":"^4.0.0","@remotion/three":"^4.0.0",\n    "three":"^0.160.0","@react-three/fiber":"^8.0.0","@react-three/drei":"^9.0.0",\n    "react":"^18.0.0","react-dom":"^18.0.0"\n  },\n  "devDependencies":{\n    "@types/react":"^18.0.0","@types/three":"^0.160.0","typescript":"^5.0.0"\n  }\n}\n' > package.json && \
    printf '{"compilerOptions":{"target":"ES2020","module":"ESNext","moduleResolution":"bundler","jsx":"react-jsx","strict":false,"esModuleInterop":true,"skipLibCheck":true},"include":["src"]}\n' > tsconfig.json && \
    printf 'import {registerRoot} from "remotion";\nimport {Root} from "./Root";\nregisterRoot(Root);\n' > src/index.ts && \
    printf 'import React from "react";\nimport {Composition} from "remotion";\nimport Scene from "./Scene";\nexport const Root: React.FC = () => {\n  const durFrames = parseInt(process.env.REMOTION_DURATION || "240");\n  return (<><Composition id="MyComp" component={Scene} durationInFrames={durFrames} width={1080} height={1920} fps={30} /></>);\n};\n' > src/Root.tsx && \
    printf 'import React from "react";\nimport {AbsoluteFill,useCurrentFrame} from "remotion";\nexport default function Scene(){const frame=useCurrentFrame();return <AbsoluteFill style={{backgroundColor:"#0D0D0D"}}/>}\n' > src/Scene.tsx && \
    npm install && \
    npm install @remotion/three three @react-three/fiber @react-three/drei && \
    npm install --save-dev @types/three

# Set working directory
WORKDIR /app

# Copy source code
COPY src/ ./src/
COPY iris-flow-plugin-staged/ ./iris-flow-plugin/

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
