"""
SimPy Service - Discrete event simulation visualization.

Uses Claude to generate SimPy simulation scripts that output
Gantt charts, timeline visualizations, and queue length plots.
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


SIMPY_PROMPT = """You are an expert Python programmer specializing in discrete event simulation using SimPy.
Generate a complete, self-contained Python script that creates a SimPy simulation and visualizes it as an animated Gantt chart or timeline.

CRITICAL DURATION REQUIREMENTS:
- Target video duration: {duration} seconds
- Frame rate: 30 FPS
- EXACT frame count required: {frames} frames
- You MUST generate EXACTLY {frames} PNG files, no more, no less
- Frame naming: frame_00000.png, frame_00001.png, etc. (5-digit zero-padded)

VIDEO FORMAT: VERTICAL (9:16 for Shorts/Reels/TikTok)
- Output resolution: 1080x1920 pixels (portrait)
- Use figsize=(6, 10.67) or similar vertical aspect ratio
- Center all visual elements

**SIMPY BEST PRACTICES:**
1. Use `simpy.Environment()` to create the simulation environment
2. Define processes as generator functions using `yield env.timeout()` and `yield resource.request()`
3. Run simulation to completion FIRST, then animate the recorded events
4. Record all events (arrivals, service starts, departures) with timestamps

**VISUALIZATION APPROACH:**
1. Run the full SimPy simulation, recording all events to a list
2. For each frame, show the state of the system at that point in time
3. Use Gantt-style bars for resource utilization
4. Show queue lengths, waiting times, or throughput as needed

**COMMON SIMPY PATTERNS:**
```python
import simpy
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

def process(env, name, resource, events):
    arrival = env.now
    with resource.request() as req:
        yield req
        start = env.now
        yield env.timeout(service_time)
        end = env.now
    events.append({{'name': name, 'arrival': arrival, 'start': start, 'end': end}})
```

**REQUIRED TEMPLATE:**
```python
import sys
import os
import simpy
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

def run_simulation():
    '''Run SimPy simulation and return recorded events.'''
    env = simpy.Environment()
    events = []
    # ... setup processes ...
    env.run()
    return events

def main(output_dir):
    os.makedirs(output_dir, exist_ok=True)
    TOTAL_FRAMES = {frames}
    
    # Run simulation first
    events = run_simulation()
    
    # Calculate time range
    max_time = max(e['end'] for e in events) if events else 10
    
    fig, ax = plt.subplots(figsize=(6, 10.67))
    
    for frame_num in range(TOTAL_FRAMES):
        ax.clear()
        t = (frame_num / TOTAL_FRAMES) * max_time
        
        # Draw events up to time t
        # ... visualization code ...
        
        ax.set_xlim(0, max_time)
        ax.set_title(f"Time: {{t:.1f}}", fontsize=14, color='white')
        ax.set_facecolor('#1a1a2e')
        fig.patch.set_facecolor('#1a1a2e')
        ax.tick_params(colors='white')
        
        plt.savefig(os.path.join(output_dir, f"frame_{{frame_num:05d}}.png"),
                    dpi=180, bbox_inches='tight', pad_inches=0.1,
                    facecolor='#1a1a2e')
    
    plt.close()
    print(f"Generated {{TOTAL_FRAMES}} frames")

if __name__ == "__main__":
    main(sys.argv[1])
```

**STYLE GUIDE:**
- Use dark theme: background '#1a1a2e', text 'white'
- Use vibrant colors for bars: '#00d4ff', '#ff6b6b', '#4ecdc4', '#ffe66d'
- Add smooth transitions between states
- Show labels and legends clearly

Description: {description}

GENERATE ONLY PYTHON CODE (no markdown, no explanation):
"""


class SimpyService:
    def __init__(self):
        FRAMES_DIR.mkdir(parents=True, exist_ok=True)
        VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    
    async def generate(self, description: str, duration: float, previous_error: str = None) -> str:
        """
        Generate a SimPy visualization video from description.
        
        1. Generate SimPy script with Claude
        2. Run script to generate frames
        3. Compile frames to video
        
        Returns path to generated video.
        """
        video_id = str(uuid.uuid4())[:8]
        fps = 30
        frames = int(duration * fps)
        
        logger.info(f"[SimPy] Generating {frames} frames for {duration}s video")
        if previous_error:
            logger.info(f"[SimPy] Retrying with error context: {previous_error}")
        
        # Step 1: Generate script
        script = await self._generate_script(description, duration, frames, previous_error)
        logger.info(f"[SimPy] Script generated ({len(script)} chars)")
        
        # Step 2: Run simulation
        frames_path = FRAMES_DIR / f"simpy_{video_id}"
        frames_path.mkdir(exist_ok=True)
        
        await self._run_simulation(script, str(frames_path))
        
        # Step 3: Compile to video
        video_path = VIDEOS_DIR / f"simpy_{video_id}.mp4"
        await self._compile_video(str(frames_path), str(video_path), fps)
        
        return str(video_path)
    
    async def _generate_script(self, description: str, duration: float, frames: int, previous_error: str = None) -> str:
        """Generate simulation script using Claude."""
        
        error_context = ""
        if previous_error:
            error_context = f"""
*** PREVIOUS ATTEMPT FAILED WITH ERROR: ***
{previous_error}
*** YOU MUST FIX THIS ERROR IN THE NEW SCRIPT ***
"""
        
        final_prompt = SIMPY_PROMPT.replace("{description}", description).replace("{duration}", str(duration)).replace("{frames}", str(frames)) + error_context
        
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
    
    async def _run_simulation(self, script: str, output_dir: str):
        """Run the simulation script."""
        script_path = Path(output_dir) / "simulation.py"
        
        with open(script_path, "w") as f:
            f.write(script)
        
        logger.info(f"[SimPy] Running simulation...")
        
        process = await asyncio.create_subprocess_exec(
            "python", str(script_path), output_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            error_msg = stderr.decode() if stderr else "Unknown error"
            raise RuntimeError(f"SimPy simulation failed: {error_msg}")
        
        logger.info(f"[SimPy] Simulation complete")
    
    async def _compile_video(self, frames_dir: str, output_path: str, fps: int = 30):
        """Compile frames to video using FFmpeg."""
        from pathlib import Path
        frames_path = Path(frames_dir)
        frame_files = sorted(frames_path.glob("frame_*.png"))
        
        if not frame_files:
            raise RuntimeError(f"No frames found in {frames_dir}")
        
        logger.info(f"[SimPy] Compiling {len(frame_files)} frames to video")
        
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
            logger.error(f"[SimPy] FFmpeg failed: {stderr_text}")
            raise RuntimeError(f"FFmpeg compilation failed: {stderr_text}")
        
        logger.info(f"[SimPy] Video compiled: {output_path}")
