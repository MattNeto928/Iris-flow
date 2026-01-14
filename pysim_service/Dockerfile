FROM python:3.11

WORKDIR /app

# Install system dependencies for visualization and FFmpeg
RUN apt-get update && apt-get install -y \
    ffmpeg \
    xvfb \
    python3-tk \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ .

EXPOSE 8003

# Copy startup script that properly manages Xvfb + uvicorn
COPY start.sh /start.sh
RUN chmod +x /start.sh

CMD ["/start.sh"]
