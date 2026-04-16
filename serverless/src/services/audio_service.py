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


AUDIO_PROMPT = """# Audio Segment Generation

Audio segments visualize sound, signal processing, and acoustics concepts as animated PNG frames. Claude generates a complete Python script producing `N = int(duration * 30)` frames at 1080×1920 using matplotlib Agg.

Most educational audio visuals use **synthetic signals** (numpy-generated sine waves, noise, chirps) rather than real audio files — this is the default unless the description specifies a real audio file.

## Mandatory Structure

```python
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import os

OUTPUT_DIR = os.environ.get('OUTPUT_DIR', '/tmp/frames')
os.makedirs(OUTPUT_DIR, exist_ok=True)
DURATION = float(os.environ.get('DURATION', '8'))
FPS = 30
N_FRAMES = int(DURATION * FPS)
SAMPLE_RATE = 44100

plt.rcParams.update({
    'font.family': 'sans-serif',
    'font.sans-serif': ['Roboto', 'Helvetica Neue', 'DejaVu Sans'],
    'axes.facecolor': '#0D0D0D',
    'figure.facecolor': '#0D0D0D',
})

fig, ax = plt.subplots(figsize=(9, 16), dpi=120)
fig.patch.set_facecolor('#0D0D0D')
```

## Synthetic Signal Generation

```python
t_audio = np.linspace(0, DURATION, int(DURATION * SAMPLE_RATE), endpoint=False)

# Pure tone
sine = np.sin(2 * np.pi * 440 * t_audio)

# Chord (A major: A4 + C#5 + E5)
chord = (np.sin(2*np.pi*440*t_audio)
       + np.sin(2*np.pi*554.37*t_audio)
       + np.sin(2*np.pi*659.25*t_audio)) / 3

# Chirp (frequency sweeps from f0 to f1)
from scipy.signal import chirp
sweep = chirp(t_audio, f0=100, f1=2000, t1=DURATION, method='logarithmic')

# AM modulation
carrier = np.sin(2*np.pi*1000*t_audio)
modulator = 0.5 * (1 + np.sin(2*np.pi*5*t_audio))
am_signal = carrier * modulator

# Noise + filtered signal
noise = np.random.randn(len(t_audio)) * 0.3
from scipy.signal import butter, filtfilt
b, a = butter(4, 0.1, btype='low')
filtered = filtfilt(b, a, noise)

# Harmonic series (Fourier overtones)
harmonics = sum(
    np.sin(2*np.pi*n*220*t_audio) / n
    for n in range(1, 8)
)
```

## Scrolling Waveform Animation

```python
# Waveform scroll: show a moving window of the audio signal
WINDOW_SAMPLES = int(SAMPLE_RATE * 0.05)  # 50ms window

ax.set_xlim(0, WINDOW_SAMPLES)
ax.set_ylim(-1.5, 1.5)
ax.set_facecolor('#0D0D0D')
ax.spines[['top','right','left','bottom']].set_visible(False)
ax.set_xticks([])
ax.set_yticks([])

# Glow effect: draw multiple layers with decreasing alpha
line_glow2, = ax.plot([], [], color='#4FC3F7', lw=8, alpha=0.04)
line_glow1, = ax.plot([], [], color='#4FC3F7', lw=4, alpha=0.1)
line_main,  = ax.plot([], [], color='#4FC3F7', lw=1.8, alpha=0.95)
zero_line   = ax.axhline(0, color='#1E1E1E', lw=1, zorder=0)

x_vals = np.arange(WINDOW_SAMPLES)

for frame_idx in range(N_FRAMES):
    sample_start = int(frame_idx / FPS * SAMPLE_RATE)
    sample_end = sample_start + WINDOW_SAMPLES
    if sample_end > len(signal):
        sample_end = len(signal)
        sample_start = max(0, sample_end - WINDOW_SAMPLES)
    window = signal[sample_start:sample_end]
    n = min(len(window), WINDOW_SAMPLES)

    line_main.set_data(x_vals[:n], window[:n])
    line_glow1.set_data(x_vals[:n], window[:n])
    line_glow2.set_data(x_vals[:n], window[:n])

    fig.savefig(os.path.join(OUTPUT_DIR, f'frame_{frame_idx:04d}.png'),
                dpi=120, bbox_inches='tight', pad_inches=0,
                facecolor='#0D0D0D')
```

## FFT Frequency Bar Animation

```python
FFT_SIZE = 2048
N_BARS = 64  # number of display bars
SMOOTHING = 0.75  # exponential moving average alpha (0=no smooth, 1=freeze)

# Logarithmically-spaced frequency bins (sounds more natural)
freq_bins = np.logspace(np.log10(80), np.log10(SAMPLE_RATE//2), N_BARS+1)

ax.set_xlim(-0.5, N_BARS - 0.5)
ax.set_ylim(0, 1.2)
ax.set_facecolor('#0D0D0D')
ax.axis('off')

x_positions = np.arange(N_BARS)
bar_heights = np.zeros(N_BARS)
bars = ax.bar(x_positions, bar_heights, width=0.85,
              color='#4FC3F7', alpha=0.9, linewidth=0)

# Color bars by frequency range (bass=warm, treble=cool)
colors = plt.cm.plasma(np.linspace(0, 1, N_BARS))
for bar, color in zip(bars, colors):
    bar.set_facecolor(color)

def ease_out_expo(t):
    return 1 - 2**(-10 * t) if t > 0 else 0

prev_heights = np.zeros(N_BARS)

for frame_idx in range(N_FRAMES):
    sample_center = int(frame_idx / FPS * SAMPLE_RATE)
    start = max(0, sample_center - FFT_SIZE//2)
    chunk = signal[start:start + FFT_SIZE]
    if len(chunk) < FFT_SIZE:
        chunk = np.pad(chunk, (0, FFT_SIZE - len(chunk)))

    # Windowed FFT
    window = np.hanning(FFT_SIZE)
    spectrum = np.abs(np.fft.rfft(chunk * window))
    freqs = np.fft.rfftfreq(FFT_SIZE, 1/SAMPLE_RATE)

    # Map to log-spaced bins
    new_heights = np.zeros(N_BARS)
    for i in range(N_BARS):
        mask = (freqs >= freq_bins[i]) & (freqs < freq_bins[i+1])
        if mask.sum() > 0:
            new_heights[i] = np.mean(spectrum[mask])

    # Normalize + smooth (EMA)
    if new_heights.max() > 0:
        new_heights /= (new_heights.max() + 1e-8)
    bar_heights = SMOOTHING * prev_heights + (1 - SMOOTHING) * new_heights
    prev_heights = bar_heights.copy()

    for bar, h in zip(bars, bar_heights):
        bar.set_height(h)

    fig.savefig(os.path.join(OUTPUT_DIR, f'frame_{frame_idx:04d}.png'),
                dpi=120, bbox_inches='tight', pad_inches=0,
                facecolor='#0D0D0D')
```

## Spectrogram (Static + Animated Playhead)

```python
import librosa
import librosa.display

# Generate or load signal
y = signal.astype(np.float32)
sr = SAMPLE_RATE

# Compute spectrogram
D = librosa.amplitude_to_db(
    np.abs(librosa.stft(y, n_fft=2048, hop_length=512)),
    ref=np.max
)

# Plot once
librosa.display.specshow(D, sr=sr, hop_length=512,
                          x_axis='time', y_axis='mel',
                          ax=ax, cmap='inferno')
ax.set_facecolor('#0D0D0D')

# Animated playhead
playhead, = ax.plot([0, 0], [ax.get_ylim()[0], ax.get_ylim()[1]],
                    color='#FFD54F', lw=2, alpha=0.85)

total_time = len(y) / sr
for frame_idx in range(N_FRAMES):
    t_sec = frame_idx / FPS
    playhead.set_xdata([t_sec, t_sec])
    fig.savefig(os.path.join(OUTPUT_DIR, f'frame_{frame_idx:04d}.png'),
                dpi=120, bbox_inches='tight', pad_inches=0,
                facecolor='#0D0D0D')
```

## Harmonic Decomposition (Stacked Sine Waves)

```python
# Show fundamental + harmonics building up
n_harmonics = 7
t_display = np.linspace(0, 2*np.pi, 500)
fundamental_freq = 1.0

fig, axes = plt.subplots(n_harmonics + 1, 1, figsize=(9, 16), dpi=120)
fig.patch.set_facecolor('#0D0D0D')
for a in axes:
    a.set_facecolor('#0D0D0D')
    a.axis('off')

harmonic_lines = []
for i, a in enumerate(axes[:-1]):
    line, = a.plot(t_display, np.zeros_like(t_display),
                   color=plt.cm.plasma(i/n_harmonics), lw=2)
    harmonic_lines.append(line)
sum_line, = axes[-1].plot(t_display, np.zeros_like(t_display),
                           color='#F5F5F5', lw=2.5)

for frame_idx in range(N_FRAMES):
    t = frame_idx / max(N_FRAMES - 1, 1)
    t_phase = frame_idx / FPS * 0.5  # slow scroll

    running_sum = np.zeros_like(t_display)
    for i, line in enumerate(harmonic_lines):
        n = i + 1
        # Reveal harmonics one by one in first half of animation
        reveal_t = i / n_harmonics
        alpha = np.clip((t - reveal_t) / (1/n_harmonics), 0, 1)
        y_vals = (np.sin(n * (t_display - t_phase * n)) / n) * alpha
        line.set_ydata(y_vals)
        running_sum += y_vals

    sum_line.set_ydata(running_sum)
    fig.savefig(...)
```

## Glow Effect Pattern

Use 3 layers with decreasing line width and increasing transparency for a neon/glow look:

```python
def plot_glowing_line(ax, x, y, color, lw_main=2, alpha_main=0.9):
    \"\"\"Return list of artists for a glowing line.\"\"\"
    outer = ax.plot(x, y, color=color, lw=lw_main*6, alpha=0.03)[0]
    mid   = ax.plot(x, y, color=color, lw=lw_main*3, alpha=0.08)[0]
    inner = ax.plot(x, y, color=color, lw=lw_main,   alpha=alpha_main)[0]
    return [outer, mid, inner]

# Update all three with same data
def update_glowing_line(artists, x, y):
    for a in artists:
        a.set_data(x, y)
```

CRITICAL DYNAMIC REQUIREMENTS:
- Target Duration: {duration} seconds
- Exact frames required: {frames}
- Description: {description}

GENERATE ONLY PYTHON CODE. Be concise — use loops, helper functions, and avoid repeating similar code blocks. No markdown, no explanation:
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
        
        self._last_prompt = final_prompt
        
        self._last_model = 'claude-opus-4-7'
        
        message = client.messages.create(
            model="claude-opus-4-7",
            max_tokens=16384,
            messages=[{"role": "user", "content": final_prompt}]
        )
        
        response_text = message.content[0].text
        if message.stop_reason == "max_tokens":
            raise RuntimeError("Code generation was truncated (hit max_tokens). The description may be too complex for a single segment.")
        
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
        
        env = os.environ.copy()
        env["OUTPUT_DIR"] = output_dir
        env["DURATION"] = str(float(env.get("DURATION", "8")))
        process = await asyncio.create_subprocess_exec(
            "python", str(script_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
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
            "-i", f"{frames_dir}/frame_%04d.png",
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
