#!/bin/bash
set -e

# Start Xvfb in background on display :99
Xvfb :99 -screen 0 1280x1024x24 -nolisten tcp &

# Wait for Xvfb to be ready
sleep 1

# Export DISPLAY for headless rendering
export DISPLAY=:99

# Run uvicorn as foreground process
exec uvicorn main:app --host 0.0.0.0 --port 8003 --reload
