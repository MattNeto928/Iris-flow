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


GEO_PROMPT = """# Geo Segment Generation

Geo segments visualize geographic data and global phenomena. Claude generates a complete Python script producing `N = int(duration * 30)` frames at 1080×1920 using cartopy + matplotlib Agg.

## Mandatory Structure

```python
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import numpy as np
import os

OUTPUT_DIR = os.environ.get('OUTPUT_DIR', '/tmp/frames')
os.makedirs(OUTPUT_DIR, exist_ok=True)
DURATION = float(os.environ.get('DURATION', '8'))
FPS = 30
N_FRAMES = int(DURATION * FPS)

plt.rcParams.update({
    'font.family': 'sans-serif',
    'font.sans-serif': ['Roboto', 'Helvetica Neue', 'DejaVu Sans'],
})

def ease_in_out_cubic(t):
    if t < 0.5: return 4 * t**3
    return 1 - (-2*t + 2)**3 / 2
```

## Rotating Globe (Orthographic Projection)

The most cinematic geo animation — Earth rotating slowly:

```python
# NOTE: Cartopy projections cannot be changed on an existing axes.
# For rotation: recreate figure+axes each frame (cartopy requirement)
# This is the correct pattern for globe rotation.

LON_START = -30.0
LON_TOTAL = 120.0  # total degrees to rotate

for frame_idx in range({frames}):
    t = frame_idx / max({frames} - 1, 1)
    t_e = ease_in_out_cubic(t)
    lon = LON_START + LON_TOTAL * t_e

    fig = plt.figure(figsize=(9, 16), dpi=120)
    fig.patch.set_facecolor('#050A14')

    # Orthographic = globe view
    proj = ccrs.Orthographic(central_longitude=lon, central_latitude=15)
    ax = fig.add_subplot(1, 1, 1, projection=proj)
    ax.set_facecolor('#050A14')

    # Background space color
    fig.patch.set_facecolor('#050A14')

    # Globe outline
    ax.add_feature(cfeature.OCEAN.with_scale('110m'),
                   facecolor='#0A1628', zorder=0)
    ax.add_feature(cfeature.LAND.with_scale('110m'),
                   facecolor='#1A2E1A', edgecolor='#2A3A2A',
                   linewidth=0.4, zorder=1)
    ax.add_feature(cfeature.COASTLINE.with_scale('110m'),
                   edgecolor='#3A5A3A', linewidth=0.6, zorder=2)
    ax.add_feature(cfeature.BORDERS.with_scale('110m'),
                   edgecolor='#2A3A2A', linewidth=0.3, zorder=2)
    ax.add_feature(cfeature.LAKES.with_scale('110m'),
                   facecolor='#0A1628', zorder=2)

    # Globe boundary (circular clip)
    ax.set_global()

    # Optional: add night/day shading or data points
    # ax.scatter([lon_data], [lat_data], transform=ccrs.PlateCarree(),
    #            c=values, cmap='plasma', s=15, alpha=0.7, zorder=5)

    # Title
    fig.text(0.5, 0.93, "Title Text", ha='center', va='top',
             fontsize=26, color='#F5F5F5', fontfamily='Roboto')

    plt.tight_layout(pad=0.5)
    fig.savefig(
        os.path.join(OUTPUT_DIR, f'frame_{frame_idx:04d}.png'),
        dpi=120, bbox_inches='tight', pad_inches=0,
        facecolor='#050A14',
    )
    plt.close(fig)
```

## Dark Earth Aesthetic — Color Palette

```python
DEEP_OCEAN  = '#061020'   # deep ocean
SHELF_OCEAN = '#0A1628'   # shallow ocean
LAND        = '#1A2810'   # land (dark green-grey)
HIGHLAND    = '#2A3018'   # mountains
COAST_LINE  = '#3A5A3A'   # coastlines
BORDER      = '#2A3020'   # country borders
SPACE_BG    = '#050A14'   # space background for globe

# Alternative: space/satellite night view
NIGHT_OCEAN = '#040810'
NIGHT_LAND  = '#0F1510'
CITY_COLOR  = '#FFD54F'   # city lights color
```

## Choropleth Map (Static World + Animated Data)

For data overlaid on a Mollweide/Robinson projection:

```python
# Use Robinson for world maps — minimal distortion, good for 9:16
fig = plt.figure(figsize=(9, 16), dpi=120)
fig.patch.set_facecolor('#0D0D0D')

ax = fig.add_subplot(1, 1, 1,
                      projection=ccrs.Robinson(central_longitude=0))
ax.set_global()
ax.set_facecolor('#0A1628')

ax.add_feature(cfeature.OCEAN.with_scale('110m'), facecolor='#061020', zorder=0)
ax.add_feature(cfeature.LAND.with_scale('110m'),  facecolor='#1A2810', zorder=1)
ax.add_feature(cfeature.COASTLINE.with_scale('110m'),
               edgecolor='#3A5A3A', linewidth=0.5, zorder=2)

# Data points (e.g., earthquake locations)
lons = np.random.uniform(-180, 180, 200)
lats = np.random.uniform(-60, 70, 200)
magnitudes = np.random.exponential(scale=2, size=200) + 2.0

scatter = ax.scatter(lons, lats, c=magnitudes,
                     transform=ccrs.PlateCarree(),
                     cmap='plasma', vmin=2, vmax=8,
                     s=magnitudes**2 * 3, alpha=0.7,
                     linewidths=0.3, edgecolors='white',
                     zorder=5)
```

## Zoom Into a Region

```python
# Animate zoom into a specific region using extent
START_EXTENT = [-180, 180, -85, 85]   # global
END_EXTENT   = [-15, 45, 35, 65]      # Europe

for frame_idx in range({frames}):
    t_e = ease_in_out_cubic(frame_idx / max({frames}-1, 1))

    extent = [
        START_EXTENT[0] + (END_EXTENT[0] - START_EXTENT[0]) * t_e,
        START_EXTENT[1] + (END_EXTENT[1] - START_EXTENT[1]) * t_e,
        START_EXTENT[2] + (END_EXTENT[2] - START_EXTENT[2]) * t_e,
        START_EXTENT[3] + (END_EXTENT[3] - START_EXTENT[3]) * t_e,
    ]

    fig = plt.figure(figsize=(9, 16), dpi=120)
    ax = fig.add_subplot(1, 1, 1, projection=ccrs.PlateCarree())
    ax.set_extent(extent, crs=ccrs.PlateCarree())
    # ... add features ...
    fig.savefig(...)
    plt.close(fig)
```

## Projection Reference for 9:16

| Projection | Best for | Class |
|-----------|----------|-------|
| Orthographic | Globe rotation | `ccrs.Orthographic(lon, lat)` |
| Robinson | World choropleth | `ccrs.Robinson()` |
| Mollweide | Equal-area world | `ccrs.Mollweide()` |
| LambertConformal | Regional (continents) | `ccrs.LambertConformal()` |
| PlateCarree | Simple regional zoom | `ccrs.PlateCarree()` |
| Mercator | City/country zoom | `ccrs.Mercator()` |

## Important: Cartopy Figure Recreation

Unlike matplotlib, **cartopy axes with a projection cannot be updated in place** when the projection itself must change (e.g., changing `central_longitude` for globe rotation). Always:
1. Create a new `fig, ax` each frame
2. Close with `plt.close(fig)` after saving
3. This is ~2-3x slower but necessary for correct globe rotation

For animations where the projection is FIXED (only data changes), you can initialize once and update:
```python
fig, ax = plt.subplots(subplot_kw={'projection': ccrs.Robinson()}, ...)
scatter = ax.scatter(...)  # initialize
for frame_idx in range({frames}):
    scatter.set_offsets(new_data)   # update data only
    fig.savefig(...)
# Do NOT plt.close() inside the loop in this case
```

CRITICAL DYNAMIC REQUIREMENTS:
- Target Duration: {duration} seconds
- Exact frames required: {frames}
- Description: {description}

GENERATE ONLY PYTHON CODE. Be concise — use loops, helper functions, and avoid repeating similar code blocks. No markdown, no explanation:
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
        """Run the geo visualization script."""
        script_path = Path(output_dir) / "visualization.py"
        
        with open(script_path, "w") as f:
            f.write(script)
        
        logger.info(f"[Geo] Running visualization...")
        
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
            logger.error(f"[Geo] FFmpeg failed: {stderr_text}")
            raise RuntimeError(f"FFmpeg compilation failed: {stderr_text}")
        
        logger.info(f"[Geo] Video compiled: {output_path}")
