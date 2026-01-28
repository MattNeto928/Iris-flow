"""
Geo Service - Geographic visualization using cartopy and geopandas.

Uses Claude to generate cartopy scripts for map projections,
choropleth maps, and geographic data visualization.
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


GEO_PROMPT = """You are an expert Python programmer specializing in geographic visualization using cartopy and matplotlib.
Generate a complete, self-contained Python script that creates animated map visualizations.

CRITICAL DURATION REQUIREMENTS:
- Target video duration: {duration} seconds
- Frame rate: 30 FPS
- EXACT frame count required: {frames} frames
- You MUST generate EXACTLY {frames} PNG files, no more, no less
- Frame naming: frame_00000.png, frame_00001.png, etc. (5-digit zero-padded)

VIDEO FORMAT: VERTICAL (9:16 for Shorts/Reels/TikTok)
- Output resolution: 1080x1920 pixels (portrait)
- Use figsize=(6, 10.67) or similar vertical aspect ratio

**IMPORTANT: NO EXTERNAL DATA FILES**
You do NOT have access to any external shapefiles or data files. You MUST:
1. Use only cartopy's built-in features (coastlines, borders, ocean)
2. Generate synthetic data programmatically
3. Use cartopy.feature for built-in geographic features

**CARTOPY BEST PRACTICES:**
```python
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import matplotlib.pyplot as plt

# Create figure with projection
fig = plt.figure(figsize=(6, 10.67))
ax = fig.add_subplot(1, 1, 1, projection=ccrs.Orthographic(central_longitude=0, central_latitude=30))

# Add features (NO external data needed!)
ax.add_feature(cfeature.OCEAN, facecolor='#1a1a2e')
ax.add_feature(cfeature.LAND, facecolor='#2d2d44')
ax.add_feature(cfeature.COASTLINE, linewidth=0.5, edgecolor='#4a90d9')
ax.add_feature(cfeature.BORDERS, linewidth=0.3, edgecolor='#666666')
ax.set_global()
```

**AVAILABLE PROJECTIONS:**
- `ccrs.Orthographic(central_longitude, central_latitude)` - 3D globe view
- `ccrs.Robinson()` - Good for world maps
- `ccrs.PlateCarree()` - Simple lat/lon
- `ccrs.Mercator()` - Classic Mercator
- `ccrs.Mollweide()` - Equal-area

**ANIMATION IDEAS:**

1. **Rotating Globe:**
```python
for frame_num in range(TOTAL_FRAMES):
    t = frame_num / TOTAL_FRAMES
    lon = -180 + t * 360  # Full rotation
    ax = fig.add_subplot(1, 1, 1, projection=ccrs.Orthographic(central_longitude=lon, central_latitude=20))
```

2. **Projection Morphing (conceptual - show different projections):**
Show different map projections in sequence with smooth transitions.

3. **Great Circle Path:**
```python
import numpy as np
from cartopy.geodesic import Geodesic

# Plot great circle route
start = (-74, 40.7)  # NYC
end = (139.7, 35.7)  # Tokyo
geod = Geodesic()
path = geod.inverse(start, end)
```

4. **Simulated Data Visualization:**
```python
# Generate synthetic climate/population data
lons = np.linspace(-180, 180, 100)
lats = np.linspace(-90, 90, 50)
LON, LAT = np.meshgrid(lons, lats)
data = np.sin(np.radians(LAT) * 2) * np.cos(np.radians(LON) * 3)  # Fake pattern

ax.contourf(LON, LAT, data, transform=ccrs.PlateCarree(), cmap='RdYlBu_r', levels=20)
```

**STYLE GUIDE:**
- Dark ocean: '#0a0a14' or '#1a1a2e'
- Land: '#2d2d44' or '#1e3a5f'
- Coastlines: '#4a90d9' or cyan
- Use vibrant colormaps for data: 'plasma', 'viridis', 'RdYlBu_r'

**REQUIRED TEMPLATE:**
```python
import sys
import os
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature

def main(output_dir):
    os.makedirs(output_dir, exist_ok=True)
    TOTAL_FRAMES = {frames}
    
    for frame_num in range(TOTAL_FRAMES):
        t = frame_num / TOTAL_FRAMES
        
        # Create figure with projection
        fig = plt.figure(figsize=(6, 10.67))
        
        # Animation: e.g., rotating globe
        central_lon = -180 + t * 360
        ax = fig.add_subplot(1, 1, 1, projection=ccrs.Orthographic(
            central_longitude=central_lon, central_latitude=20
        ))
        
        # Add features
        ax.add_feature(cfeature.OCEAN, facecolor='#0a0a14')
        ax.add_feature(cfeature.LAND, facecolor='#1e3a5f')
        ax.add_feature(cfeature.COASTLINE, linewidth=0.5, edgecolor='#4a90d9')
        ax.set_global()
        
        fig.patch.set_facecolor('#0a0a14')
        
        plt.savefig(os.path.join(output_dir, f"frame_{{frame_num:05d}}.png"),
                    dpi=180, bbox_inches='tight', pad_inches=0,
                    facecolor='#0a0a14')
        plt.close()
    
    print(f"Generated {{TOTAL_FRAMES}} frames")

if __name__ == "__main__":
    main(sys.argv[1])
```

Description: {description}

GENERATE ONLY PYTHON CODE (no markdown, no explanation):
"""


class GeoService:
    def __init__(self):
        FRAMES_DIR.mkdir(parents=True, exist_ok=True)
        VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    
    async def generate(self, description: str, duration: float, previous_error: str = None) -> str:
        """
        Generate a geographic visualization video from description.
        
        1. Generate cartopy script with Claude
        2. Run script to generate frames
        3. Compile frames to video
        
        Returns path to generated video.
        """
        video_id = str(uuid.uuid4())[:8]
        fps = 30
        frames = int(duration * fps)
        
        logger.info(f"[Geo] Generating {frames} frames for {duration}s video")
        if previous_error:
            logger.info(f"[Geo] Retrying with error context: {previous_error}")
        
        # Step 1: Generate script
        script = await self._generate_script(description, duration, frames, previous_error)
        logger.info(f"[Geo] Script generated ({len(script)} chars)")
        
        # Step 2: Run visualization
        frames_path = FRAMES_DIR / f"geo_{video_id}"
        frames_path.mkdir(exist_ok=True)
        
        await self._run_visualization(script, str(frames_path))
        
        # Step 3: Compile to video
        video_path = VIDEOS_DIR / f"geo_{video_id}.mp4"
        await self._compile_video(str(frames_path), str(video_path), fps)
        
        return str(video_path)
    
    async def _generate_script(self, description: str, duration: float, frames: int, previous_error: str = None) -> str:
        """Generate geo script using Claude."""
        
        error_context = ""
        if previous_error:
            error_context = f"""
*** PREVIOUS ATTEMPT FAILED WITH ERROR: ***
{previous_error}
*** YOU MUST FIX THIS ERROR IN THE NEW SCRIPT ***
"""
        
        final_prompt = GEO_PROMPT.replace("{description}", description).replace("{duration}", str(duration)).replace("{frames}", str(frames)) + error_context
        
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
        """Run the geo visualization script."""
        script_path = Path(output_dir) / "visualization.py"
        
        with open(script_path, "w") as f:
            f.write(script)
        
        logger.info(f"[Geo] Running visualization...")
        
        process = await asyncio.create_subprocess_exec(
            "python", str(script_path), output_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            error_msg = stderr.decode() if stderr else "Unknown error"
            raise RuntimeError(f"Geo visualization failed: {error_msg}")
        
        logger.info(f"[Geo] Visualization complete")
    
    async def _compile_video(self, frames_dir: str, output_path: str, fps: int = 30):
        """Compile frames to video using FFmpeg."""
        from pathlib import Path
        frames_path = Path(frames_dir)
        frame_files = sorted(frames_path.glob("frame_*.png"))
        
        if not frame_files:
            raise RuntimeError(f"No frames found in {frames_dir}")
        
        logger.info(f"[Geo] Compiling {len(frame_files)} frames to video")
        
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
            logger.error(f"[Geo] FFmpeg failed: {stderr_text}")
            raise RuntimeError(f"FFmpeg compilation failed: {stderr_text}")
        
        logger.info(f"[Geo] Video compiled: {output_path}")
