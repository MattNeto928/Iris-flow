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

from src.services._llm import generate_text, strip_code_fences, build_narration_timeline, validate_script, prepare_retry_context

logger = logging.getLogger(__name__)

# Output directories
OUTPUT_DIR = Path("/app/output")
FRAMES_DIR = OUTPUT_DIR / "frames"
VIDEOS_DIR = OUTPUT_DIR / "videos"


PLOTLY_PROMPT = """# Plotly Segment Generation

## When to Use Plotly (Engine Role)

Plotly renders segments that require **high-quality continuous 3D surface shading** that matplotlib cannot match:
- Dispersion surfaces (omega vs k)
- Potential energy landscapes
- Isosurfaces of scalar fields (probability density, charge density, electromagnetic field magnitude)
- Smooth parametric solids (Mesh3d models) and surfaces that orbit under a moving camera

**Do NOT use plotly for:**
- Simple particle clouds or scatter -> use matplotlib
- Equations or LaTeX -> use manim
- Basic 3D geometry (spheres, arrows, wire frames) -> use matplotlib

Plotly segments create cinematic 3D scientific visualizations. Claude generates a **complete Python script** that exports exactly `N = int(round(DURATION * 30))` PNG frames at 1080x1920 using Plotly + Kaleido, with smooth camera orbits and a dark aesthetic.

## FRAME COUNT IS NON-NEGOTIABLE

`DURATION` is injected via the environment and ALREADY equals this segment's length, so
`N_FRAMES = int(round(DURATION * FPS))` evaluates to exactly the required count. Drive the
frame loop with `for frame_idx in range(N_FRAMES):` and export one PNG per index. NEVER
hardcode a frame count or a fixed number of seconds — a wrong count gets time-stretched to
fit the audio and the camera orbit will visibly speed up or crawl.

## Kaleido export (pinned engine)

The container pins `plotly==5.24.1` + `kaleido==0.2.1`, so `fig.write_image(path, engine='kaleido', scale=1)`
is the correct, supported call. Use exactly that — do NOT pass any other engine, and do NOT
rely on `plotly.io.kaleido.scope` or Kaleido v1 APIs (not installed).

## Iris-local Style Constants

These palette values are mandatory. Use them verbatim — no substitutions:
```python
BG          = "#0D0D0D"   # background — always
BLUE        = "#4FC3F7"   # electric blue — primary accent
GOLD        = "#FFD54F"   # soft gold — secondary / highlight
CORAL       = "#FF7043"   # coral — contrast / alert
MINT        = "#80CBC4"   # mint — tertiary
LAVENDER    = "#CE93D8"   # lavender — quaternary
WARM_WHITE  = "#F5F5F5"   # labels, annotations
DIM         = "#424242"   # muted elements, grid lines
```

Apply these to `paper_bgcolor`, `plot_bgcolor`, `font color`, `scene bgcolor`, axis colors, and colorbar tick colors.

## Mandatory Script Structure

```python
import plotly.graph_objects as go
import numpy as np
import os

OUTPUT_DIR = os.environ.get('OUTPUT_DIR', '/tmp/frames')
os.makedirs(OUTPUT_DIR, exist_ok=True)
DURATION = float(os.environ.get('DURATION', '8'))   # injected = the real voiceover length
FPS = 30
N_FRAMES = int(round(DURATION * FPS))

def ease(t):
    \"\"\"Cosine ease-in-out: smooth acceleration and deceleration.\"\"\"
    return 0.5 - 0.5 * np.cos(np.pi * t)

fig = go.Figure()
# ... add traces here ...

fig.update_layout(
    width=1080, height=1920,
    paper_bgcolor='#0D0D0D', plot_bgcolor='#0D0D0D',
    margin=dict(l=20, r=20, t=80, b=20),
    font=dict(family='Roboto, Helvetica Neue, sans-serif', color='#F5F5F5'),
    scene=dict(
        bgcolor='#0D0D0D',
        xaxis=dict(gridcolor='#1A1A1A', zerolinecolor='#2A2A2A', showbackground=False),
        yaxis=dict(gridcolor='#1A1A1A', zerolinecolor='#2A2A2A', showbackground=False),
        zaxis=dict(gridcolor='#1A1A1A', zerolinecolor='#2A2A2A', showbackground=False),
        aspectmode='cube',
    ),
)

def camera_at(theta, phi=0.5, r=2.2):
    \"\"\"Spherical -> cartesian camera eye.\"\"\"
    return dict(x=r*np.sin(phi)*np.cos(theta), y=r*np.sin(phi)*np.sin(theta), z=r*np.cos(phi))

for frame_idx in range(N_FRAMES):
    t = frame_idx / max(N_FRAMES - 1, 1)
    t_e = ease(t)
    theta = -np.pi/4 + t_e * (2*np.pi/3)   # orbit 120 degrees, eased
    fig.update_layout(scene_camera=dict(eye=camera_at(theta), up=dict(x=0, y=0, z=1)))
    # fig.data[0].z = new_z   # if animating a surface
    fig.write_image(os.path.join(OUTPUT_DIR, f'frame_{frame_idx:04d}.png'),
                    format='png', engine='kaleido', scale=1)

print(f"Rendered {N_FRAMES} frames")
```

## COMPOSITION — fill the 9:16 frame

The surface/model must dominate the 1080x1920 canvas, not float small in the middle:
- Keep margins tight: `margin=dict(l=0, r=0, t=70, b=0)`.
- Make the 3D scene occupy the whole frame via its domain:
  `scene=dict(domain=dict(x=[0,1], y=[0.04, 0.96]), ...)`.
- Pull the camera in so the object is large: a closer `eye` (smaller radius, e.g. r≈1.7-2.0
  in `camera_at`) enlarges the subject. Pick a radius where the surface nearly fills the frame.
- Use `aspectmode='cube'` (or 'data') so the object isn't squashed, and a bold colorscale.

## 3D Trace Types

### Surface Plot
```python
x = np.linspace(-3, 3, 80); y = np.linspace(-3, 3, 80)
X, Y = np.meshgrid(x, y)
Z = np.sin(np.sqrt(X**2 + Y**2)) * np.exp(-0.15 * (X**2 + Y**2))
fig.add_trace(go.Surface(x=X, y=Y, z=Z, colorscale='Plasma', showscale=True, opacity=1.0,
    lighting=dict(ambient=0.5, diffuse=0.8, roughness=0.3, specular=0.5),
    lightposition=dict(x=1000, y=1000, z=1000),
    contours=dict(z=dict(show=True, color='rgba(255,255,255,0.15)', width=1))))
```

### Scatter3d (Points / Trails)
```python
fig.add_trace(go.Scatter3d(x=xs, y=ys, z=zs, mode='lines+markers',
    line=dict(color='#4FC3F7', width=2),
    marker=dict(size=3, color=zs, colorscale='Plasma', opacity=0.8)))
```

### Isosurface (scalar field at a threshold — e.g. an orbital lobe)
```python
g = np.linspace(-2,2,40); X,Y,Z = np.meshgrid(g,g,g)
field = (Z**2) * np.exp(-np.sqrt(X**2+Y**2+Z**2))    # p_z-like density
fig.add_trace(go.Isosurface(x=X.flatten(), y=Y.flatten(), z=Z.flatten(), value=field.flatten(),
    isomin=field.max()*0.25, isomax=field.max()*0.9, surface_count=2,
    colorscale='Viridis', caps=dict(x_show=False, y_show=False, z_show=False), opacity=0.6))
```

### Mesh3d MODEL (smooth solid — build a recognizable object the audience holds on)
```python
# Parametric torus knot as a tube of spheres, or a smooth molecule via Mesh3d spheres:
def add_sphere(cx, cy, cz, r, color):
    u=np.linspace(0,2*np.pi,18); v=np.linspace(0,np.pi,9)
    xs=(cx+r*np.outer(np.cos(u),np.sin(v))).flatten()
    ys=(cy+r*np.outer(np.sin(u),np.sin(v))).flatten()
    zs=(cz+r*np.outer(np.ones_like(u),np.cos(v))).flatten()
    fig.add_trace(go.Mesh3d(x=xs, y=ys, z=zs, alphahull=0, color=color, opacity=1.0,
                            lighting=dict(ambient=0.5, diffuse=0.8, specular=0.4)))
# e.g. benzene ring: 6 carbons on a hexagon + 6 hydrogens outward, bonds as thin Scatter3d lines.
```

## Camera Orbit Patterns (always eased — never raw linear t)

```python
theta = -np.pi/4 + ease(t) * 2*np.pi          # full 360, eased
phi   = 0.3 + ease(t) * 0.4                    # helical rise
r     = 2.5 - ease(t) * 0.8                    # zoom in while orbiting
```

## Colorscales for Dark Background
`'Plasma'`, `'Inferno'`, `'Magma'`, `'Viridis'`, `'Turbo'` all read well on #0D0D0D.
Custom: `[[0,'#0D0D0D'],[0.5,'#4FC3F7'],[1,'#FFD54F']]`.

## Colorbar Positioning (9:16 Vertical) — must not overlap the scene
```python
coloraxis_colorbar=dict(thickness=10, len=0.4, x=0.93, y=0.25,
                        tickfont=dict(size=11, color='#808080'))
```
Or `go.Surface(..., showscale=False)` and a small `fig.add_annotation(...)` label instead.

## Performance
- Kaleido renders ~0.3-1s per frame; a 20s segment is ~600 frames -> several minutes. Expected.
- Reduce surface resolution for animated surfaces: 40x40 instead of 80x80.
- Never re-create `go.Figure()` per frame — update in place with `fig.data[0].z = new_z`.
{narration_block}
CRITICAL DYNAMIC REQUIREMENTS:
- Target Duration: {duration} seconds
- Exact frames required: {frames} (emit frame_0000.png ... frame_{last:04d}.png; N_FRAMES already equals this)
- Description: {description}

GENERATE ONLY PYTHON CODE. Be concise — use loops, helper functions, and avoid repeating similar code blocks. No markdown, no explanation:
"""


class PlotlyService:
    def __init__(self):
        FRAMES_DIR.mkdir(parents=True, exist_ok=True)
        VIDEOS_DIR.mkdir(parents=True, exist_ok=True)

    async def generate(
        self,
        description: str,
        duration: float,
        previous_error: str = None,
        voiceover_text: str = None,
    ) -> str:
        """
        Generate a Plotly visualization video from description.

        1. Generate Plotly script with Claude
        2. Run script to generate frames
        3. Compile frames to video

        Returns path to generated video.
        """
        video_id = str(uuid.uuid4())[:8]
        fps = 30
        frames = int(round(duration * fps))

        logger.info(f"[Plotly] Generating {frames} frames for {duration}s video")
        if previous_error:
            logger.info(f"[Plotly] Retrying with error context: {previous_error}")

        # Step 1: Generate script
        script = await self._generate_script(description, duration, frames, previous_error, voiceover_text)
        logger.info(f"[Plotly] Script generated ({len(script)} chars)")

        # Step 2: Run visualization
        frames_path = FRAMES_DIR / f"plotly_{video_id}"
        frames_path.mkdir(exist_ok=True)

        await self._run_visualization(script, str(frames_path), duration)

        # Step 3: Compile to video
        video_path = VIDEOS_DIR / f"plotly_{video_id}.mp4"
        await self._compile_video(str(frames_path), str(video_path), fps)

        return str(video_path)

    async def _generate_script(
        self,
        description: str,
        duration: float,
        frames: int,
        previous_error: str = None,
        voiceover_text: str = None,
    ) -> str:
        """Generate Plotly script using Claude (streaming + adaptive thinking)."""


        narration_block = build_narration_timeline(voiceover_text, duration)
        description, narration_block, error_context = prepare_retry_context(
            description, narration_block, previous_error)

        final_prompt = (
            PLOTLY_PROMPT
            .replace("{narration_block}", narration_block)
            .replace("{description}", description)
            .replace("{duration}", str(duration))
            .replace("{frames}", str(frames))
            .replace("{last:04d}", f"{max(frames - 1, 0):04d}")
            + error_context
        )

        self._last_prompt = final_prompt
        self._last_model = "claude-fable-5"

        response_text, stop_reason = generate_text(final_prompt, max_tokens=32000)
        if stop_reason == "max_tokens":
            raise RuntimeError("Code generation was truncated (hit max_tokens). The description may be too complex for a single segment.")

        return validate_script(strip_code_fences(response_text), "write_image", stop_reason, "plotly")

    async def _run_visualization(self, script: str, output_dir: str, duration: float):
        """Run the Plotly script."""
        script_path = Path(output_dir) / "visualization.py"

        with open(script_path, "w") as f:
            f.write(script)

        logger.info(f"[Plotly] Running visualization ({duration:.2f}s target)...")

        env = os.environ.copy()
        env["OUTPUT_DIR"] = output_dir
        # Inject the real duration so N_FRAMES matches the voiceover (see pysim_service).
        env["DURATION"] = str(float(duration))
        process = await asyncio.create_subprocess_exec(
            "python", str(script_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
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
            logger.error(f"[Plotly] FFmpeg failed: {stderr_text}")
            raise RuntimeError(f"FFmpeg compilation failed: {stderr_text}")

        logger.info(f"[Plotly] Video compiled: {output_path}")
