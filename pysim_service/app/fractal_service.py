"""
Fractal Service - Fractals and cellular automata visualization.

Uses Claude to generate numba-accelerated scripts for Mandelbrot sets,
Julia sets, Game of Life, and L-systems.
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
OUTPUT_DIR = Path("/videos")
FRAMES_DIR = OUTPUT_DIR / "frames"
VIDEOS_DIR = OUTPUT_DIR / "videos"


FRACTAL_PROMPT = """You are an expert Python programmer specializing in fractal visualization and cellular automata using numba for performance.
Generate a complete, self-contained Python script that creates mesmerizing fractal or cellular automata animations.

CRITICAL DURATION REQUIREMENTS:
- Target video duration: {duration} seconds
- Frame rate: 30 FPS
- EXACT frame count required: {frames} frames
- You MUST generate EXACTLY {frames} PNG files, no more, no less
- Frame naming: frame_00000.png, frame_00001.png, etc. (5-digit zero-padded)

VIDEO FORMAT: VERTICAL (9:16 for Shorts/Reels/TikTok)
- Output resolution: 1080x1920 pixels (portrait)
- Use figsize=(6, 10.67) or vertical image dimensions

**NUMBA JIT COMPILATION (CRITICAL FOR PERFORMANCE):**
```python
from numba import jit, prange
import numpy as np

@jit(nopython=True, parallel=True)
def compute_mandelbrot(xmin, xmax, ymin, ymax, width, height, max_iter):
    result = np.zeros((height, width))
    for j in prange(height):
        for i in range(width):
            x0 = xmin + (xmax - xmin) * i / width
            y0 = ymin + (ymax - ymin) * j / height
            x, y = 0.0, 0.0
            iteration = 0
            while x*x + y*y <= 4 and iteration < max_iter:
                xtemp = x*x - y*y + x0
                y = 2*x*y + y0
                x = xtemp
                iteration += 1
            result[j, i] = iteration
    return result
```

**FRACTAL TYPES:**

1. **Mandelbrot Zoom:**
```python
# Animate zoom into interesting region
center_x, center_y = -0.743643887037151, 0.131825904205330  # Famous spiral
for frame_num in range(TOTAL_FRAMES):
    t = frame_num / TOTAL_FRAMES
    zoom = 4.0 * (0.5 ** (t * 10))  # Exponential zoom
    xmin, xmax = center_x - zoom, center_x + zoom
    ymin, ymax = center_y - zoom * 1.78, center_y + zoom * 1.78  # 9:16 aspect
```

2. **Julia Set Animation (varying c parameter):**
```python
@jit(nopython=True, parallel=True)
def julia(c_real, c_imag, xmin, xmax, ymin, ymax, width, height, max_iter):
    # Similar to Mandelbrot but z starts at the pixel, c is constant
    ...

# Animate c along a path in complex plane
for frame_num in range(TOTAL_FRAMES):
    t = frame_num / TOTAL_FRAMES
    c_real = 0.7885 * np.cos(t * 2 * np.pi)
    c_imag = 0.7885 * np.sin(t * 2 * np.pi)
```

3. **Conway's Game of Life:**
```python
@jit(nopython=True)
def step(grid):
    rows, cols = grid.shape
    new_grid = np.zeros_like(grid)
    for i in range(rows):
        for j in range(cols):
            neighbors = (grid[(i-1)%rows,(j-1)%cols] + grid[(i-1)%rows,j] + 
                        grid[(i-1)%rows,(j+1)%cols] + grid[i,(j-1)%cols] +
                        grid[i,(j+1)%cols] + grid[(i+1)%rows,(j-1)%cols] +
                        grid[(i+1)%rows,j] + grid[(i+1)%rows,(j+1)%cols])
            if grid[i,j] == 1:
                new_grid[i,j] = 1 if neighbors in (2, 3) else 0
            else:
                new_grid[i,j] = 1 if neighbors == 3 else 0
    return new_grid
```

4. **L-System (Fractal Plants):**
```python
def apply_rules(axiom, rules, iterations):
    result = axiom
    for _ in range(iterations):
        result = ''.join(rules.get(c, c) for c in result)
    return result

def draw_lsystem(commands, angle, length):
    # Turtle graphics to generate points
    ...
```

**COLORMAPS:**
- Use 'hot', 'magma', 'plasma', 'twilight' for fractals
- Or create custom: `colors = plt.cm.hot(iterations / max_iter)`

**STYLE GUIDE:**
- Black or very dark background
- Vibrant, saturated colors for fractals
- For Game of Life: white/bright cells on dark background
- Smooth color transitions

**REQUIRED TEMPLATE:**
```python
import sys
import os
import numpy as np
from numba import jit, prange
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

@jit(nopython=True, parallel=True)
def compute_fractal(...):
    # JIT-compiled fractal computation
    ...

def main(output_dir):
    os.makedirs(output_dir, exist_ok=True)
    TOTAL_FRAMES = {frames}
    
    # Image dimensions (9:16 vertical)
    width, height = 1080, 1920
    
    for frame_num in range(TOTAL_FRAMES):
        t = frame_num / TOTAL_FRAMES
        
        # Compute fractal for this frame
        result = compute_fractal(...)
        
        # Create image
        fig = plt.figure(figsize=(width/180, height/180), dpi=180)
        ax = fig.add_axes([0, 0, 1, 1])
        ax.imshow(result, cmap='magma', origin='lower')
        ax.axis('off')
        
        plt.savefig(os.path.join(output_dir, f"frame_{{frame_num:05d}}.png"),
                    dpi=180, bbox_inches='tight', pad_inches=0)
        plt.close()
    
    print(f"Generated {{TOTAL_FRAMES}} frames")

if __name__ == "__main__":
    main(sys.argv[1])
```

Description: {description}

GENERATE ONLY PYTHON CODE (no markdown, no explanation):
"""


class FractalService:
    def __init__(self):
        FRAMES_DIR.mkdir(parents=True, exist_ok=True)
        VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    
    async def generate(self, description: str, duration: float, previous_error: str = None) -> str:
        """
        Generate a fractal visualization video from description.
        
        1. Generate fractal script with Claude
        2. Run script to generate frames
        3. Compile frames to video
        
        Returns path to generated video.
        """
        video_id = str(uuid.uuid4())[:8]
        fps = 30
        frames = int(duration * fps)
        
        logger.info(f"[Fractal] Generating {frames} frames for {duration}s video")
        if previous_error:
            logger.info(f"[Fractal] Retrying with error context: {previous_error}")
        
        # Step 1: Generate script
        script = await self._generate_script(description, duration, frames, previous_error)
        logger.info(f"[Fractal] Script generated ({len(script)} chars)")
        
        # Step 2: Run visualization
        frames_path = FRAMES_DIR / f"fractal_{video_id}"
        frames_path.mkdir(exist_ok=True)
        
        await self._run_visualization(script, str(frames_path))
        
        # Step 3: Compile to video
        video_path = VIDEOS_DIR / f"fractal_{video_id}.mp4"
        await self._compile_video(str(frames_path), str(video_path), fps)
        
        return str(video_path)
    
    async def _generate_script(self, description: str, duration: float, frames: int, previous_error: str = None) -> str:
        """Generate fractal script using Claude."""
        
        error_context = ""
        if previous_error:
            error_context = f"""
*** PREVIOUS ATTEMPT FAILED WITH ERROR: ***
{previous_error}
*** YOU MUST FIX THIS ERROR IN THE NEW SCRIPT ***
"""
        
        final_prompt = FRACTAL_PROMPT.replace("{description}", description).replace("{duration}", str(duration)).replace("{frames}", str(frames)) + error_context
        
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
        """Run the fractal script."""
        script_path = Path(output_dir) / "visualization.py"
        
        with open(script_path, "w") as f:
            f.write(script)
        
        logger.info(f"[Fractal] Running visualization...")
        
        process = await asyncio.create_subprocess_exec(
            "python", str(script_path), output_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            error_msg = stderr.decode() if stderr else "Unknown error"
            raise RuntimeError(f"Fractal visualization failed: {error_msg}")
        
        logger.info(f"[Fractal] Visualization complete")
    
    async def _compile_video(self, frames_dir: str, output_path: str, fps: int = 30):
        """Compile frames to video using FFmpeg."""
        from pathlib import Path
        frames_path = Path(frames_dir)
        frame_files = sorted(frames_path.glob("frame_*.png"))
        
        if not frame_files:
            raise RuntimeError(f"No frames found in {frames_dir}")
        
        logger.info(f"[Fractal] Compiling {len(frame_files)} frames to video")
        
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
            logger.error(f"[Fractal] FFmpeg failed: {stderr_text}")
            raise RuntimeError(f"FFmpeg compilation failed: {stderr_text}")
        
        logger.info(f"[Fractal] Video compiled: {output_path}")
