"""
Astro Service - Astronomy visualization using astropy and skyfield.

Uses Claude to generate astronomy scripts for orbital mechanics,
star maps, eclipses, and celestial phenomena.
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


ASTRO_PROMPT = """You are an expert Python programmer specializing in astronomy visualization using astropy, skyfield, and matplotlib.
Generate a complete, self-contained Python script that creates astronomical animations.

CRITICAL DURATION REQUIREMENTS:
- Target video duration: {duration} seconds
- Frame rate: 30 FPS
- EXACT frame count required: {frames} frames
- You MUST generate EXACTLY {frames} PNG files, no more, no less
- Frame naming: frame_00000.png, frame_00001.png, etc. (5-digit zero-padded)

VIDEO FORMAT: VERTICAL (9:16 for Shorts/Reels/TikTok)
- Output resolution: 1080x1920 pixels (portrait)
- Use figsize=(6, 10.67) or similar vertical aspect ratio

**IMPORTANT: WORK OFFLINE**
You do NOT have internet access. Use:
1. Astropy's built-in calculations (no external catalogs)
2. Skyfield with generated ephemeris data or simple Keplerian orbits
3. Mathematical approximations for orbital mechanics

**ASTROPY BASICS:**
```python
from astropy import units as u
from astropy.coordinates import SkyCoord, EarthLocation, AltAz
from astropy.time import Time
import numpy as np

# Create sky coordinates
coord = SkyCoord(ra=10.68458*u.degree, dec=41.26917*u.degree, frame='icrs')

# Time handling
t = Time('2024-01-01 00:00:00', scale='utc')
```

**ORBITAL MECHANICS (Keplerian approximation):**
```python
import numpy as np

def kepler_orbit(a, e, n_points=100):
    '''Generate elliptical orbit points.'''
    theta = np.linspace(0, 2*np.pi, n_points)
    r = a * (1 - e**2) / (1 + e * np.cos(theta))
    x = r * np.cos(theta)
    y = r * np.sin(theta)
    return x, y

# Planet positions (simplified)
# Mercury: a=0.387 AU, e=0.206
# Venus: a=0.723 AU, e=0.007
# Earth: a=1.0 AU, e=0.017
# Mars: a=1.524 AU, e=0.093
# Jupiter: a=5.203 AU, e=0.048
```

**ANIMATION IDEAS:**

1. **Solar System Orrery:**
```python
# Orbital parameters (semi-major axis in AU, orbital period in days)
planets = {{
    'Mercury': (0.387, 88),
    'Venus': (0.723, 225),
    'Earth': (1.0, 365),
    'Mars': (1.524, 687),
}}

for frame_num in range(TOTAL_FRAMES):
    t = frame_num / TOTAL_FRAMES
    days = t * 365 * 2  # Animate 2 years
    
    for name, (a, period) in planets.items():
        angle = 2 * np.pi * days / period
        x = a * np.cos(angle)
        y = a * np.sin(angle)
        ax.plot(x, y, 'o', markersize=planet_size[name])
```

2. **Moon Phases:**
```python
# Simulate moon phase based on sun-earth-moon geometry
for frame_num in range(TOTAL_FRAMES):
    phase = frame_num / TOTAL_FRAMES  # 0 to 1 = new to new moon
    angle = phase * 2 * np.pi
    # Draw illuminated portion
```

3. **Eclipse Geometry:**
Show sun, earth, moon alignment for solar/lunar eclipse.

4. **Star Field with Constellations:**
```python
# Generate random stars
np.random.seed(42)
n_stars = 500
ra = np.random.uniform(0, 360, n_stars)
dec = np.random.uniform(-90, 90, n_stars)
brightness = np.random.exponential(1, n_stars)
```

**SKYFIELD (simple usage):**
```python
from skyfield.api import load, Topos
from skyfield.positionlib import Apparent

# Note: skyfield normally needs internet for ephemeris
# Use simple calculations instead:
def planet_position(planet_name, jd):
    '''Simple Keplerian approximation.'''
    # ... return xyz coordinates
```

**STYLE GUIDE:**
- Pure black background: '#000000' or '#0a0a14'
- Stars: white or slightly colored points
- Planet colors: Mercury(gray), Venus(yellow), Earth(blue), Mars(red), etc.
- Orbits: thin dotted or dashed lines
- Sun: bright yellow/orange with glow effect
- Use glow effects for celestial bodies

**REQUIRED TEMPLATE:**
```python
import sys
import os
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Circle
from matplotlib.collections import PatchCollection

def main(output_dir):
    os.makedirs(output_dir, exist_ok=True)
    TOTAL_FRAMES = {frames}
    
    fig, ax = plt.subplots(figsize=(6, 10.67))
    
    for frame_num in range(TOTAL_FRAMES):
        ax.clear()
        t = frame_num / TOTAL_FRAMES
        
        # Set up dark space background
        ax.set_facecolor('#000000')
        fig.patch.set_facecolor('#000000')
        
        # Animation logic
        # ...
        
        ax.set_aspect('equal')
        ax.axis('off')
        
        plt.savefig(os.path.join(output_dir, f"frame_{{frame_num:05d}}.png"),
                    dpi=180, bbox_inches='tight', pad_inches=0,
                    facecolor='#000000')
    
    plt.close()
    print(f"Generated {{TOTAL_FRAMES}} frames")

if __name__ == "__main__":
    main(sys.argv[1])
```

Description: {description}

GENERATE ONLY PYTHON CODE (no markdown, no explanation):
"""


class AstroService:
    def __init__(self):
        FRAMES_DIR.mkdir(parents=True, exist_ok=True)
        VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    
    async def generate(self, description: str, duration: float, previous_error: str = None) -> str:
        """
        Generate an astronomy visualization video from description.
        
        1. Generate astropy/skyfield script with Claude
        2. Run script to generate frames
        3. Compile frames to video
        
        Returns path to generated video.
        """
        video_id = str(uuid.uuid4())[:8]
        fps = 30
        frames = int(duration * fps)
        
        logger.info(f"[Astro] Generating {frames} frames for {duration}s video")
        if previous_error:
            logger.info(f"[Astro] Retrying with error context: {previous_error}")
        
        # Step 1: Generate script
        script = await self._generate_script(description, duration, frames, previous_error)
        logger.info(f"[Astro] Script generated ({len(script)} chars)")
        
        # Step 2: Run visualization
        frames_path = FRAMES_DIR / f"astro_{video_id}"
        frames_path.mkdir(exist_ok=True)
        
        await self._run_visualization(script, str(frames_path))
        
        # Step 3: Compile to video
        video_path = VIDEOS_DIR / f"astro_{video_id}.mp4"
        await self._compile_video(str(frames_path), str(video_path), fps)
        
        return str(video_path)
    
    async def _generate_script(self, description: str, duration: float, frames: int, previous_error: str = None) -> str:
        """Generate astro script using Claude."""
        
        error_context = ""
        if previous_error:
            error_context = f"""
*** PREVIOUS ATTEMPT FAILED WITH ERROR: ***
{previous_error}
*** YOU MUST FIX THIS ERROR IN THE NEW SCRIPT ***
"""
        
        final_prompt = ASTRO_PROMPT.replace("{description}", description).replace("{duration}", str(duration)).replace("{frames}", str(frames)) + error_context
        
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
        """Run the astro visualization script."""
        script_path = Path(output_dir) / "visualization.py"
        
        with open(script_path, "w") as f:
            f.write(script)
        
        logger.info(f"[Astro] Running visualization...")
        
        process = await asyncio.create_subprocess_exec(
            "python", str(script_path), output_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            error_msg = stderr.decode() if stderr else "Unknown error"
            raise RuntimeError(f"Astro visualization failed: {error_msg}")
        
        logger.info(f"[Astro] Visualization complete")
    
    async def _compile_video(self, frames_dir: str, output_path: str, fps: int = 30):
        """Compile frames to video using FFmpeg."""
        from pathlib import Path
        frames_path = Path(frames_dir)
        frame_files = sorted(frames_path.glob("frame_*.png"))
        
        if not frame_files:
            raise RuntimeError(f"No frames found in {frames_dir}")
        
        logger.info(f"[Astro] Compiling {len(frame_files)} frames to video")
        
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
            logger.error(f"[Astro] FFmpeg failed: {stderr_text}")
            raise RuntimeError(f"FFmpeg compilation failed: {stderr_text}")
        
        logger.info(f"[Astro] Video compiled: {output_path}")
