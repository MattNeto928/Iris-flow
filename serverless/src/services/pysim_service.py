"""
PySim Service - Python scientific simulation generation.

Uses Claude to generate Python simulation scripts, then runs them to produce frames
and compiles to video. Ported from local pysim_service.
"""

import os
import uuid
import logging
import subprocess
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


PYSIM_PROMPT = """You are an expert Python scientific computing programmer. Generate a complete, self-contained Python script that creates a simulation and outputs frames for video creation.

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

**CRITICAL - MUST FOLLOW THESE RULES:**
1. **USE MATPLOTLIB ONLY** - Do NOT use pygame, tkinter, or any GUI libraries
2. **SET BACKEND FIRST** - Start with: `import matplotlib; matplotlib.use('Agg')`
3. **NO EVENT LOOPS** - No while True, no pygame.event loop, no blocking calls
4. **FINITE LOOP ONLY** - Use exactly: `for frame_num in range({frames}):`
5. **NO USER INPUT** - Script must run completely autonomously
6. Output ONLY the Python code - no explanations, no markdown backticks

**PERFORMANCE RULES (PREVENT TIMEOUTS - CRITICAL):**
- **VECTORIZATION IS MANDATORY**: NEVER loop over particles/agents to draw them individually.
    - BAD: `for p in particles: ax.scatter(p.x, p.y, ...)` (This causes timeouts!)
    - GOOD: `ax.scatter(particles_x, particles_y, s=sizes, c=colors, ...)` (One call per frame)
- Keep particle/agent counts reasonable (< 500 per frame)
- Avoid expensive operations (scipy.optimize, heavy matrix ops) inside frame loop
- Pre-compute static data BEFORE the frame loop
- If adding glow/effects, use layers (e.g. 3 scatter calls total), DO NOT iterate points.

**AVOID THESE COMMON ERRORS:**
- NO plt.colorbar() - causes layout errors
- NO plt.tight_layout() inside the loop
- Use ax.clear() at start of each frame
- Use fixed axis limits (ax.set_xlim, ax.set_ylim)

**PARAMETER VALIDATION RULES:**
- ALWAYS clamp alpha values to [0, 1] range: `alpha = np.clip(alpha, 0, 1)`
- ALWAYS clamp color values if performing math: `colors = np.clip(colors * factor, 0, 1)`
- BAD: `c=colors * 1.5` (Causes crash: "RGBA values should be within 0-1 range")
- ALWAYS ensure marker sizes are positive: `s = np.maximum(s, 1)`
- NEVER compute values that could go negative for positive-only params

**STRING FORMATTING RULES (PREVENT CRASHES):**
- NEVER use curly braces `{{}}` in f-strings with undefined or potentially undefined variables
- BAD: `ax.text("Value: {{}}".format())` - missing argument causes crash!
- BAD: `f"Rate: {{speed}}x"` when speed might be undefined
- GOOD: Define all variables BEFORE using them in f-strings
- GOOD: Use string concatenation for labels: `"Value: " + str(value)`

**CODE SYNTAX RULES:**
- ALWAYS close all parentheses, brackets, and braces
- ALWAYS match function call opening ( with closing )
- DOUBLE-CHECK multi-line function calls have proper closing parentheses
- BAD: `ax.text2D(0.5, 0.05, "Label", transform=ax.transAxes,` (unclosed!)
- GOOD: Complete all function calls on single line or properly close multi-line calls

REQUIRED TEMPLATE:
```
import sys
import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

def main(output_dir):
    os.makedirs(output_dir, exist_ok=True)
    TOTAL_FRAMES = {frames}
    
    # Vertical format for Shorts/Reels
    fig, ax = plt.subplots(figsize=(6, 10.67))
    
    for frame_num in range(TOTAL_FRAMES):
        ax.clear()
        
        # === YOUR SIMULATION CODE HERE ===
        t = frame_num / TOTAL_FRAMES
        # ... simulation logic ...
        # === END SIMULATION CODE ===
        
        ax.set_xlim(-2, 2)
        ax.set_ylim(-4, 4)
        ax.set_aspect('equal')
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


class PysimService:
    def __init__(self):
        FRAMES_DIR.mkdir(parents=True, exist_ok=True)
        VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    
    async def generate(self, description: str, duration: float, previous_error: str = None) -> str:
        """
        Generate a PySim video from description.
        
        1. Generate Python script with Claude
        2. Run script to generate frames
        3. Compile frames to video
        
        Returns path to generated video.
        """
        video_id = str(uuid.uuid4())[:8]
        fps = 30
        frames = int(duration * fps)
        
        logger.info(f"[PySim] Generating {frames} frames for {duration}s video")
        if previous_error:
            logger.info(f"[PySim] Retrying with error context: {previous_error}")
        
        # Step 1: Generate script
        script = await self._generate_script(description, duration, frames, previous_error)
        logger.info(f"[PySim] Script generated ({len(script)} chars)")
        
        # Step 2: Run simulation
        frames_path = FRAMES_DIR / video_id
        frames_path.mkdir(exist_ok=True)
        
        await self._run_simulation(script, str(frames_path))
        
        # Step 3: Compile to video
        video_path = VIDEOS_DIR / f"pysim_{video_id}.mp4"
        await self._compile_video(str(frames_path), str(video_path), fps)
        
        return str(video_path)
    
    async def _generate_script(self, description: str, duration: float, frames: int, previous_error: str = None) -> str:
        """Generate simulation script using Claude."""
        
        # Add error context if retrying
        error_context = ""
        if previous_error:
            error_context = f"""
*** PREVIOUS ATTEMPT FAILED WITH ERROR: ***
{previous_error}
*** YOU MUST FIX THIS ERROR IN THE NEW SCRIPT ***
"""
        
        # Use replace() instead of format() to avoid conflicts with curly braces in the prompt examples
        final_prompt = PYSIM_PROMPT.replace("{description}", description).replace("{duration}", str(duration)).replace("{frames}", str(frames)) + error_context
        
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
        
        logger.info(f"[PySim] Running simulation...")
        
        process = await asyncio.create_subprocess_exec(
            "python", str(script_path), output_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            error_msg = stderr.decode() if stderr else "Unknown error"
            raise RuntimeError(f"Simulation failed: {error_msg}")
        
        logger.info(f"[PySim] Simulation complete")
    
    async def _compile_video(self, frames_dir: str, output_path: str, fps: int = 30):
        """Compile frames to video using FFmpeg."""
        # Validate frames exist before compilation
        from pathlib import Path
        frames_path = Path(frames_dir)
        frame_files = sorted(frames_path.glob("frame_*.png"))
        
        if not frame_files:
            raise RuntimeError(f"No frames found in {frames_dir}")
        
        logger.info(f"[PySim] Compiling {len(frame_files)} frames to video")
        
        cmd = [
            "ffmpeg", "-y",
            "-framerate", str(fps),
            "-i", f"{frames_dir}/frame_%05d.png",
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",  # Ensure even dimensions for libx264
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
            logger.error(f"[PySim] FFmpeg failed: {stderr_text}")
            raise RuntimeError(f"FFmpeg compilation failed: {stderr_text}")
        
        logger.info(f"[PySim] Video compiled: {output_path}")
