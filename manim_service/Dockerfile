FROM python:3.11

WORKDIR /app

# Install system dependencies for Manim
# Using texlive-latex-extra instead of texlive-full to reduce image size (~500MB vs ~5GB)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libcairo2-dev \
    libpango1.0-dev \
    texlive-latex-base \
    texlive-latex-extra \
    texlive-fonts-recommended \
    texlive-science \
    dvipng \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ .

EXPOSE 8002

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002", "--reload"]
