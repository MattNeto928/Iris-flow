"""
Audio Service - Sound and signal visualization using librosa.

Uses Claude to generate librosa scripts that visualize audio waveforms,
spectrograms, FFT, and music theory concepts.
"""

import os
import uuid
import logging
import asyncio
from pathlib import Path
import anthropic

logger = logging.getLogger(__name__)

# Initialize Anthropic client
client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

# Output directories
OUTPUT_DIR = Path("/app/output")
FRAMES_DIR = OUTPUT_DIR / "frames"
VIDEOS_DIR = OUTPUT_DIR / "videos"


AUDIO_PROMPT = """You are an expert Python programmer specializing in audio/signal processing visualization using librosa and matplotlib.
Generate a complete, self-contained Python script that creates stunning audio visualizations.

CRITICAL DURATION REQUIREMENTS:
- Target video duration: {duration} seconds
- Frame rate: 30 FPS
- EXACT frame count required: {frames} frames
- You MUST generate EXACTLY {frames} PNG files, no more, no less
- Frame naming: frame_00000.png, frame_00001.png, etc. (5-digit zero-padded)

VIDEO FORMAT: VERTICAL (9:16 for Shorts/Reels/TikTok)
- Output resolution: 1080x1920 pixels (portrait)
- Use figsize=(6, 10.67) or similar vertical aspect ratio

**IMPORTANT: SYNTHESIZE AUDIO, DON'T LOAD FILES**
Since we don't have access to audio files, you MUST generate/synthesize audio signals programmatically:
- Use numpy to generate sine waves, square waves, etc.
- Create musical notes using frequencies (A4=440Hz, etc.)
- Combine harmonics to create complex tones
- Add noise, modulation, or effects mathematically

**LIBROSA BEST PRACTICES:**
1. Use `librosa.display` for spectrogram plotting
2. For FFT visualization: `np.fft.fft()` and `np.abs()`
3. Use `librosa.amplitude_to_db()` for dB scale
4. Pre-compute all spectral features before animation

**SYNTHESIZING AUDIO SIGNALS:**
```python
import numpy as np

sr = 22050  # Sample rate
duration = 3.0  # seconds
t = np.linspace(0, duration, int(sr * duration))

# Pure sine wave (A4 = 440 Hz)
signal = np.sin(2 * np.pi * 440 * t)

# Chord (A major: A4, C#5, E5)
signal = np.sin(2 * np.pi * 440 * t) + np.sin(2 * np.pi * 554.37 * t) + np.sin(2 * np.pi * 659.25 * t)

# Add harmonics
fundamental = 440
signal = sum(np.sin(2 * np.pi * fundamental * (n+1) * t) / (n+1) for n in range(5))

# Frequency sweep (chirp)
signal = np.sin(2 * np.pi * (200 + 600 * t/duration) * t)
```

**VISUALIZATION TYPES:**
1. **Waveform**: `ax.plot(time, signal)`
2. **Spectrogram**: `librosa.display.specshow(S_db, sr=sr, x_axis='time', y_axis='hz')`
3. **FFT/Spectrum**: `ax.plot(freqs, magnitudes)`
4. **Mel spectrogram**: `librosa.feature.melspectrogram(y=signal, sr=sr)`
5. **Chromagram**: `librosa.feature.chroma_stft(y=signal, sr=sr)`

**ANIMATION APPROACH:**
- For waveforms: slide a window through the signal
- For spectrograms: reveal columns progressively
- For FFT: animate frequency response changing over time

**STYLE GUIDE:**
- Dark background: '#1a1a2e'
- Use vibrant colormaps: 'magma', 'plasma', 'viridis'
- Waveform colors: '#00d4ff', '#ff6b6b'
- White text and labels

**REQUIRED TEMPLATE:**
```python
import sys
import os
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import librosa
import librosa.display

def main(output_dir):
    os.makedirs(output_dir, exist_ok=True)
    TOTAL_FRAMES = {frames}
    
    # Synthesize audio signal
    sr = 22050
    duration_audio = 3.0
    t = np.linspace(0, duration_audio, int(sr * duration_audio))
    signal = np.sin(2 * np.pi * 440 * t)  # Example: 440 Hz sine wave
    
    # Compute spectrogram
    S = librosa.stft(signal)
    S_db = librosa.amplitude_to_db(np.abs(S), ref=np.max)
    
    fig, ax = plt.subplots(figsize=(6, 10.67))
    
    for frame_num in range(TOTAL_FRAMES):
        ax.clear()
        t_progress = frame_num / TOTAL_FRAMES
        
        # Animation logic
        # ...
        
        ax.set_facecolor('#1a1a2e')
        fig.patch.set_facecolor('#1a1a2e')
        ax.tick_params(colors='white')
        ax.set_title("Audio Visualization", color='white', fontsize=14)
        
        plt.savefig(os.path.join(output_dir, f"frame_{{frame_num:05d}}.png"),
                    dpi=180, bbox_inches='tight', pad_inches=0.1,
                    facecolor='#1a1a2e')
    
    plt.close()
    print(f"Generated {{TOTAL_FRAMES}} frames")

if __name__ == "__main__":
    main(sys.argv[1])
```

Description: {description}

GENERATE ONLY PYTHON CODE (no markdown, no explanation):
"""


class AudioService:
    def __init__(self):
        FRAMES_DIR.mkdir(parents=True, exist_ok=True)
        VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    
    async def generate(self, description: str, duration: float, previous_error: str = None) -> str:
        """
        Generate an audio visualization video from description.
        
        1. Generate librosa script with Claude
        2. Run script to generate frames
        3. Compile frames to video
        
        Returns path to generated video.
        """
        video_id = str(uuid.uuid4())[:8]
        fps = 30
        frames = int(duration * fps)
        
        logger.info(f"[Audio] Generating {frames} frames for {duration}s video")
        if previous_error:
            logger.info(f"[Audio] Retrying with error context: {previous_error}")
        
        # Step 1: Generate script
        script = await self._generate_script(description, duration, frames, previous_error)
        logger.info(f"[Audio] Script generated ({len(script)} chars)")
        
        # Step 2: Run visualization
        frames_path = FRAMES_DIR / f"audio_{video_id}"
        frames_path.mkdir(exist_ok=True)
        
        await self._run_visualization(script, str(frames_path))
        
        # Step 3: Compile to video
        video_path = VIDEOS_DIR / f"audio_{video_id}.mp4"
        await self._compile_video(str(frames_path), str(video_path), fps)
        
        return str(video_path)
    
    async def _generate_script(self, description: str, duration: float, frames: int, previous_error: str = None) -> str:
        """Generate audio visualization script using Claude."""
        
        error_context = ""
        if previous_error:
            error_context = f"""
*** PREVIOUS ATTEMPT FAILED WITH ERROR: ***
{previous_error}
*** YOU MUST FIX THIS ERROR IN THE NEW SCRIPT ***
"""
        
        final_prompt = AUDIO_PROMPT.replace("{description}", description).replace("{duration}", str(duration)).replace("{frames}", str(frames)) + error_context
        
        message = client.messages.create(
            model="claude-opus-4-5-20251101",
            max_tokens=4096,
            messages=[{"role": "user", "content": final_prompt}]
        )
        
        response_text = message.content[0].text
        
        # Clean markdown if present
        if "```python" in response_text:
            start = response_text.find("```python") + 9
            end = response_text.find("```", start)
            response_text = response_text[start:end].strip()
        elif "```" in response_text:
            start = response_text.find("```") + 3
            end = response_text.find("```", start)
            response_text = response_text[start:end].strip()
        
        return response_text
    
    async def _run_visualization(self, script: str, output_dir: str):
        """Run the audio visualization script."""
        script_path = Path(output_dir) / "visualization.py"
        
        with open(script_path, "w") as f:
            f.write(script)
        
        logger.info(f"[Audio] Running visualization...")
        
        process = await asyncio.create_subprocess_exec(
            "python", str(script_path), output_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            error_msg = stderr.decode() if stderr else "Unknown error"
            raise RuntimeError(f"Audio visualization failed: {error_msg}")
        
        logger.info(f"[Audio] Visualization complete")
    
    async def _compile_video(self, frames_dir: str, output_path: str, fps: int = 30):
        """Compile frames to video using FFmpeg."""
        from pathlib import Path
        frames_path = Path(frames_dir)
        frame_files = sorted(frames_path.glob("frame_*.png"))
        
        if not frame_files:
            raise RuntimeError(f"No frames found in {frames_dir}")
        
        logger.info(f"[Audio] Compiling {len(frame_files)} frames to video")
        
        cmd = [
            "ffmpeg", "-y",
            "-framerate", str(fps),
            "-i", f"{frames_dir}/frame_%05d.png",
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-preset", "fast",
            "-crf", "23",
            output_path
        ]
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            stderr_text = stderr.decode() if stderr else "Unknown error"
            logger.error(f"[Audio] FFmpeg failed: {stderr_text}")
            raise RuntimeError(f"FFmpeg compilation failed: {stderr_text}")
        
        logger.info(f"[Audio] Video compiled: {output_path}")
