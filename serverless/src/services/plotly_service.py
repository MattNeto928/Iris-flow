"""
Plotly Service - 3D plots and animated data visualization.

Uses Claude to generate Plotly scripts that export frames via Kaleido
for 3D surfaces, animated scatter plots, and complex data visualizations.
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


PLOTLY_PROMPT = """You are an expert Python programmer specializing in Plotly for 3D visualization and animated plots.
Generate a complete, self-contained Python script that creates stunning Plotly visualizations exported as frames.

CRITICAL DURATION REQUIREMENTS:
- Target video duration: {duration} seconds
- Frame rate: 30 FPS
- EXACT frame count required: {frames} frames
- You MUST generate EXACTLY {frames} PNG files, no more, no less
- Frame naming: frame_00000.png, frame_00001.png, etc. (5-digit zero-padded)

VIDEO FORMAT: VERTICAL (9:16 for Shorts/Reels/TikTok)
- Output resolution: 1080x1920 pixels (portrait)
- Use width=1080, height=1920 in fig.write_image()

**PLOTLY + KALEIDO BEST PRACTICES:**
1. Use `plotly.graph_objects` for fine-grained control
2. Export frames with `fig.write_image(path, engine="kaleido")`
3. For 3D: Use `go.Surface`, `go.Scatter3d`, `go.Mesh3d`
4. For animations: Update figure data in a loop, export each frame

**CRITICAL - KALEIDO EXPORT:**
```python
import plotly.graph_objects as go
import plotly.io as pio
pio.kaleido.scope.default_format = "png"

# Export each frame
fig.write_image(f"frame_{{i:05d}}.png", width=1080, height=1920, engine="kaleido")
```

**3D SURFACE EXAMPLE:**
```python
import numpy as np
import plotly.graph_objects as go

x = np.linspace(-5, 5, 50)
y = np.linspace(-5, 5, 50)
X, Y = np.meshgrid(x, y)
Z = np.sin(np.sqrt(X**2 + Y**2))

fig = go.Figure(data=[go.Surface(z=Z, x=X, y=Y, colorscale='Viridis')])
fig.update_layout(
    scene=dict(
        camera=dict(eye=dict(x=1.5, y=1.5, z=1.5))
    ),
    paper_bgcolor='#1a1a2e',
    font=dict(color='white')
)
```

**ANIMATED CAMERA ROTATION (for 3D):**
```python
for frame_num in range(TOTAL_FRAMES):
    t = frame_num / TOTAL_FRAMES
    angle = t * 2 * np.pi
    camera = dict(
        eye=dict(
            x=2 * np.cos(angle),
            y=2 * np.sin(angle),
            z=1.5
        )
    )
    fig.update_layout(scene_camera=camera)
    fig.write_image(f"{{output_dir}}/frame_{{frame_num:05d}}.png", width=1080, height=1920, engine="kaleido")
```

**STYLE GUIDE:**
- Use dark theme: paper_bgcolor='#1a1a2e', plot_bgcolor='#1a1a2e'
- Use vibrant colorscales: 'Viridis', 'Plasma', 'Inferno', 'Turbo'
- White text and labels
- Smooth camera movements for 3D

**REQUIRED TEMPLATE:**
```python
import sys
import os
import numpy as np
import plotly.graph_objects as go
import plotly.io as pio

pio.kaleido.scope.default_format = "png"

def main(output_dir):
    os.makedirs(output_dir, exist_ok=True)
    TOTAL_FRAMES = {frames}
    
    # Create your data
    # ... data generation ...
    
    # Create figure
    fig = go.Figure(data=[...])
    
    fig.update_layout(
        paper_bgcolor='#1a1a2e',
        plot_bgcolor='#1a1a2e',
        font=dict(color='white', size=14),
        showlegend=True,
        margin=dict(l=20, r=20, t=60, b=20)
    )
    
    for frame_num in range(TOTAL_FRAMES):
        t = frame_num / TOTAL_FRAMES
        
        # Update figure for this frame
        # ... animation logic ...
        
        fig.write_image(
            os.path.join(output_dir, f"frame_{{frame_num:05d}}.png"),
            width=1080, height=1920, engine="kaleido"
        )
    
    print(f"Generated {{TOTAL_FRAMES}} frames")

if __name__ == "__main__":
    main(sys.argv[1])
```

Description: {description}

GENERATE ONLY PYTHON CODE (no markdown, no explanation):
"""


class PlotlyService:
    def __init__(self):
        FRAMES_DIR.mkdir(parents=True, exist_ok=True)
        VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    
    async def generate(self, description: str, duration: float, previous_error: str = None) -> str:
        """
        Generate a Plotly visualization video from description.
        
        1. Generate Plotly script with Claude
        2. Run script to generate frames
        3. Compile frames to video
        
        Returns path to generated video.
        """
        video_id = str(uuid.uuid4())[:8]
        fps = 30
        frames = int(duration * fps)
        
        logger.info(f"[Plotly] Generating {frames} frames for {duration}s video")
        if previous_error:
            logger.info(f"[Plotly] Retrying with error context: {previous_error}")
        
        # Step 1: Generate script
        script = await self._generate_script(description, duration, frames, previous_error)
        logger.info(f"[Plotly] Script generated ({len(script)} chars)")
        
        # Step 2: Run visualization
        frames_path = FRAMES_DIR / f"plotly_{video_id}"
        frames_path.mkdir(exist_ok=True)
        
        await self._run_visualization(script, str(frames_path))
        
        # Step 3: Compile to video
        video_path = VIDEOS_DIR / f"plotly_{video_id}.mp4"
        await self._compile_video(str(frames_path), str(video_path), fps)
        
        return str(video_path)
    
    async def _generate_script(self, description: str, duration: float, frames: int, previous_error: str = None) -> str:
        """Generate Plotly script using Claude."""
        
        error_context = ""
        if previous_error:
            error_context = f"""
*** PREVIOUS ATTEMPT FAILED WITH ERROR: ***
{previous_error}
*** YOU MUST FIX THIS ERROR IN THE NEW SCRIPT ***
"""
        
        final_prompt = PLOTLY_PROMPT.replace("{description}", description).replace("{duration}", str(duration)).replace("{frames}", str(frames)) + error_context
        
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
        """Run the Plotly script."""
        script_path = Path(output_dir) / "visualization.py"
        
        with open(script_path, "w") as f:
            f.write(script)
        
        logger.info(f"[Plotly] Running visualization...")
        
        process = await asyncio.create_subprocess_exec(
            "python", str(script_path), output_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            error_msg = stderr.decode() if stderr else "Unknown error"
            raise RuntimeError(f"Plotly visualization failed: {error_msg}")
        
        logger.info(f"[Plotly] Visualization complete")
    
    async def _compile_video(self, frames_dir: str, output_path: str, fps: int = 30):
        """Compile frames to video using FFmpeg."""
        from pathlib import Path
        frames_path = Path(frames_dir)
        frame_files = sorted(frames_path.glob("frame_*.png"))
        
        if not frame_files:
            raise RuntimeError(f"No frames found in {frames_dir}")
        
        logger.info(f"[Plotly] Compiling {len(frame_files)} frames to video")
        
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
            logger.error(f"[Plotly] FFmpeg failed: {stderr_text}")
            raise RuntimeError(f"FFmpeg compilation failed: {stderr_text}")
        
        logger.info(f"[Plotly] Video compiled: {output_path}")
