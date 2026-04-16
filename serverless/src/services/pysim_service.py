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


PYSIM_PROMPT = """# PySim Segment Generation

PySim segments generate scientific simulations as PNG frame sequences compiled into MP4 by FFmpeg. Claude generates a **complete, self-contained Python script** that produces exactly `N = int(duration * 30)` frames saved as `frame_0000.png`, `frame_0001.png`, etc.

## Mandatory Script Structure

```python
import matplotlib
matplotlib.use('Agg')  # MUST be before any other matplotlib import
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import numpy as np
import os

# ── Output setup ──────────────────────────────────────────────────────────────
OUTPUT_DIR = os.environ.get('OUTPUT_DIR', '/tmp/frames')
os.makedirs(OUTPUT_DIR, exist_ok=True)
DURATION = float(os.environ.get('DURATION', '8'))
FPS = 30
N_FRAMES = int(DURATION * FPS)

# ── Global style ──────────────────────────────────────────────────────────────
plt.rcParams.update({
    'font.family': 'sans-serif',
    'font.sans-serif': ['Roboto', 'Helvetica Neue', 'DejaVu Sans'],
    'text.color': '#F5F5F5',
    'axes.facecolor': '#0D0D0D',
    'figure.facecolor': '#0D0D0D',
    'axes.edgecolor': '#2A2A2A',
    'grid.color': '#1E1E1E',
    'grid.linewidth': 0.5,
})

# ── Figure — fixed at 1080×1920 ───────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(9, 16), dpi=120)  # 9*120=1080, 16*120=1920
fig.patch.set_facecolor('#0D0D0D')
ax.set_facecolor('#0D0D0D')

# ── Axis limits — SET ONCE, NEVER INSIDE THE FRAME LOOP ──────────────────────
XLIM = (-5, 5)
YLIM = (-8.5, 8.5)
ax.set_xlim(XLIM)
ax.set_ylim(YLIM)
ax.set_aspect('equal')
ax.axis('off')  # or configure ticks/spines explicitly

# ── Initialize simulation state ───────────────────────────────────────────────
# ... all state variables here ...

# ── Initialize artists (create once, update in loop) ──────────────────────────
# e.g. scatter = ax.scatter([], [], c=[], s=[], cmap='plasma', vmin=0, vmax=1)
# e.g. line, = ax.plot([], [], color='#4FC3F7', lw=2)

# ── Easing utilities ──────────────────────────────────────────────────────────
def ease_in_out_cubic(t):
    \"\"\"t in [0,1] → eased value in [0,1]\"\"\"
    if t < 0.5:
        return 4 * t**3
    return 1 - (-2*t + 2)**3 / 2

def lerp(a, b, t):
    return a + (b - a) * t

# ── Frame loop ────────────────────────────────────────────────────────────────
for frame_idx in range({frames}):
    t = frame_idx / max({frames} - 1, 1)  # normalized time [0, 1]
    t_eased = ease_in_out_cubic(t)

    # Update simulation state (vectorized, no Python loops)
    # ...

    # Update artist data — NEVER call plt.cla() or ax.clear()
    # scatter.set_offsets(positions)
    # scatter.set_array(colors)
    # line.set_data(x_data, y_data)

    # Save frame
    fig.savefig(
        os.path.join(OUTPUT_DIR, f'frame_{frame_idx:04d}.png'),
        dpi=120,
        bbox_inches='tight',
        pad_inches=0,
        facecolor=fig.get_facecolor(),
    )

plt.close(fig)
print(f"Rendered {{N_FRAMES}} frames to {{OUTPUT_DIR}}")
```

## The Golden Rule: Never Recreate Artists

The most common source of jitter is recreating matplotlib artists inside the frame loop. Always initialize once, update with `set_data` / `set_offsets` / `set_array`.

```python
# WRONG — causes flicker/jitter
for frame in range(N_FRAMES):
    ax.clear()           # ← NEVER
    ax.scatter(x, y)     # ← NEVER create inside loop
    ax.set_xlim(...)     # ← NEVER reset limits inside loop

# RIGHT — initialize once, update properties only
scatter = ax.scatter(x0, y0, c=colors, s=sizes, cmap='plasma', vmin=0, vmax=1)
for frame in range(N_FRAMES):
    # Update positions and colors via set_* methods
    scatter.set_offsets(np.column_stack([new_x, new_y]))
    scatter.set_array(new_colors)
```

## Axis Limits — Fixed Forever

Set axis limits ONCE before the frame loop. They must never change mid-animation (causes zoom jitter):

```python
# Set based on the maximum extent of the simulation
# Add 15% padding beyond the maximum coordinate
ax.set_xlim(-X_MAX * 1.15, X_MAX * 1.15)
ax.set_ylim(-Y_MAX * 1.15, Y_MAX * 1.15)
```

## Easing — Smooth Parameter Changes

All parameter transitions must use easing, not linear interpolation:

```python
def ease_in_out_cubic(t):
    if t < 0.5: return 4 * t**3
    return 1 - (-2*t + 2)**3 / 2

def ease_out_expo(t):
    return 1 - 2**(-10 * t) if t > 0 else 0

# Phase-based easing (multiple phases in one animation)
def phase_ease(t, start, end):
    \"\"\"Remap global t to [0,1] within a time window.\"\"\"
    if t <= start: return 0.0
    if t >= end: return 1.0
    return ease_in_out_cubic((t - start) / (end - start))

# Example: zoom in from t=0→0.3, hold t=0.3→0.7, zoom out t=0.7→1.0
zoom = lerp(1.0, 2.5, phase_ease(t, 0.0, 0.3)) \
     + lerp(2.5, 2.5, phase_ease(t, 0.3, 0.7) - phase_ease(t, 0.0, 0.3)) \
     + lerp(2.5, 1.0, phase_ease(t, 0.7, 1.0))
```

## Dark Aesthetic Palette

```python
BG          = '#0D0D0D'
PANEL_BG    = '#121212'
ELECTRIC    = '#4FC3F7'   # primary data / curves
GOLD        = '#FFD54F'   # highlight / key value
CORAL       = '#FF7043'   # secondary data
MINT        = '#80CBC4'   # tertiary
LAVENDER    = '#CE93D8'   # quaternary
WARM_WHITE  = '#F5F5F5'   # text
DIM_GREY    = '#424242'   # secondary text / grid

# Good colormaps on dark backgrounds
# 'plasma', 'inferno', 'magma', 'viridis', 'twilight', 'cool', 'hot'
```

## Text and Labels

```python
# Title — top of frame, always
ax.text(0, 8.0, "Simulation Title",
        ha='center', va='top',
        fontsize=22, color=WARM_WHITE, fontweight='bold',
        fontfamily='Roboto')

# Annotation — never overlap with data
ax.text(-4.5, -7.5, f"t = {{sim_time:.2f}}s",
        ha='left', va='bottom',
        fontsize=14, color=DIM_GREY, fontfamily='Roboto')

# Use ax.transAxes for fixed screen-space text (doesn't move with data)
ax.text(0.5, 0.97, "Title",
        transform=ax.transAxes,
        ha='center', va='top',
        fontsize=22, color=WARM_WHITE)
```

## Vectorized Simulation Patterns

### Particle System
```python
N = 200  # number of particles
pos = np.random.uniform(-4, 4, (N, 2))
vel = np.random.randn(N, 2) * 0.1
mass = np.random.uniform(0.5, 2.0, N)

scatter = ax.scatter(pos[:, 0], pos[:, 1],
                     c=mass, cmap='plasma', s=20,
                     vmin=mass.min(), vmax=mass.max(),
                     alpha=0.85, linewidths=0)

for frame_idx in range({frames}):
    t = frame_idx / ({frames} - 1)
    # Vectorized update — no Python loop over particles
    pos += vel * (1.0 / FPS)
    # Boundary: wrap or bounce
    vel[pos > 4.5] *= -1
    vel[pos < -4.5] *= -1
    pos = np.clip(pos, -4.5, 4.5)

    scatter.set_offsets(pos)
    fig.savefig(...)
```

### Wave Equation
```python
x = np.linspace(-4.5, 4.5, 400)
line, = ax.plot(x, np.zeros_like(x), color=ELECTRIC, lw=2.5, alpha=0.9)
fill = ax.fill_between(x, np.zeros_like(x), alpha=0.15, color=ELECTRIC)

for frame_idx in range({frames}):
    t_sec = frame_idx / FPS
    y = np.sin(2 * np.pi * (x - t_sec * 1.5)) * np.exp(-0.1 * x**2)
    line.set_ydata(y)
    # Update fill: remove old, add new (fill_between must be recreated)
    # Alternative: use imshow or contourf for wave fields
    fig.savefig(...)
```

### 3D Matplotlib Rotation
```python
from mpl_toolkits.mplot3d import Axes3D

fig = plt.figure(figsize=(9, 16), dpi=120)
ax = fig.add_subplot(111, projection='3d')
fig.patch.set_facecolor('#0D0D0D')
ax.set_facecolor('#0D0D0D')

# Plot once
X, Y = np.meshgrid(np.linspace(-3, 3, 60), np.linspace(-3, 3, 60))
Z = np.sin(np.sqrt(X**2 + Y**2))
surf = ax.plot_surface(X, Y, Z, cmap='plasma', alpha=0.9,
                        linewidth=0, antialiased=True)

# Rotate per frame — set_xlim NOT needed, view_init only
for frame_idx in range({frames}):
    t = frame_idx / ({frames} - 1)
    azim = -60 + ease_in_out_cubic(t) * 120  # rotate 120° total
    ax.view_init(elev=30, azim=azim)
    fig.savefig(...)
```

### Flow Field + Tracer Particles (premium science-viz look)

Stream plot as a static base, then particles that actually follow the field lines on top. This is the pattern that makes videos look research-grade vs. toy:

```python
from scipy.interpolate import RegularGridInterpolator

# Vector field — example: rotational flow with sink
grid = np.linspace(-4, 4, 40)
X, Y = np.meshgrid(grid, grid)
U = -Y - 0.2 * X  # flow field components
V =  X - 0.2 * Y

# Draw static streamlines (slim, low alpha — they're context)
ax.streamplot(X, Y, U, V, color='#1E1E1E', density=1.6, linewidth=0.6, arrowsize=0)

# Interpolators so particles read the field continuously
fu = RegularGridInterpolator((grid, grid), U.T, bounds_error=False, fill_value=0.0)
fv = RegularGridInterpolator((grid, grid), V.T, bounds_error=False, fill_value=0.0)

# Particles
N = 300
pts = np.random.uniform(-4, 4, (N, 2))
trails = np.zeros((N, 8, 2))  # last 8 positions per particle for trail fade
trails[:] = pts[:, None, :]

scatter = ax.scatter(pts[:, 0], pts[:, 1], s=14, c='#4FC3F7', alpha=0.9, linewidths=0)
# Trail lines — use LineCollection for efficiency
from matplotlib.collections import LineCollection
trail_lines = LineCollection([], colors='#4FC3F7', linewidths=1.2, alpha=0.4)
ax.add_collection(trail_lines)

DT = 0.08
for frame_idx in range({frames}):
    # Step particles along the field
    vx = fu(pts); vy = fv(pts)
    pts += np.stack([vx, vy], axis=1) * DT
    # Respawn particles that left the box
    out = (np.abs(pts[:, 0]) > 4.2) | (np.abs(pts[:, 1]) > 4.2)
    pts[out] = np.random.uniform(-4, 4, (out.sum(), 2))
    # Shift trails
    trails = np.roll(trails, -1, axis=1); trails[:, -1, :] = pts
    scatter.set_offsets(pts)
    trail_lines.set_segments(trails)
    fig.savefig(...)
```

### Manifold / Parametric Surface Reveal

A surface that gradually "un-crumples" from a flat disc to its target shape. Great for visualizing non-trivial geometry (Möbius, torus, hyperbolic paraboloid):

```python
# Parametric sphere → torus morph
U_, V_ = np.meshgrid(np.linspace(0, 2*np.pi, 80), np.linspace(0, np.pi, 40))
R, r = 2.0, 0.7

for frame_idx in range({frames}):
    t = ease_in_out_cubic(frame_idx / ({frames} - 1))
    # Blend: at t=0 a sphere, at t=1 a torus
    sphere_x = R * np.sin(V_) * np.cos(U_)
    sphere_y = R * np.sin(V_) * np.sin(U_)
    sphere_z = R * np.cos(V_)
    torus_x = (R + r * np.cos(V_ * 2)) * np.cos(U_)
    torus_y = (R + r * np.cos(V_ * 2)) * np.sin(U_)
    torus_z = r * np.sin(V_ * 2)
    Xm = (1 - t) * sphere_x + t * torus_x
    Ym = (1 - t) * sphere_y + t * torus_y
    Zm = (1 - t) * sphere_z + t * torus_z
    # Use ax.clear() ONLY for 3D surfaces since plot_surface can't be updated in place
    ax.clear()
    ax.set_facecolor('#0D0D0D'); ax.set_axis_off()
    ax.plot_surface(Xm, Ym, Zm, cmap='plasma', alpha=0.92, linewidth=0)
    ax.view_init(elev=20 + 20*t, azim=-40 + 180*t)
    fig.savefig(...)
```

Note: 3D surfaces are the ONE exception to the "never use ax.clear()" rule, because `plot_surface` doesn't support in-place data update. Limit 3D surface scenes to short clips for this reason.

### Heatmap + Moving Indicator (dual layer)

Live data often reads better as a heatmap with a cursor indicating the current value — like a research dashboard:

```python
# Example: wave equation on a 2D grid
N = 128
u = np.zeros((N, N)); v = np.zeros((N, N))
# Seed a pulse
u[N//2, N//2] = 5.0
im = ax.imshow(u, cmap='magma', vmin=-1, vmax=1,
               extent=[-4, 4, -4, 4], origin='lower', interpolation='bilinear')
# Add contours for extra richness (computed each frame)
contour_set = [None]
# Cursor marker (bright dot tracking peak)
cursor = ax.scatter([0], [0], s=200, c='#FFD54F',
                    edgecolors='#FFFFFF', linewidths=2, zorder=5)

C = 0.3  # wave speed
for frame_idx in range({frames}):
    # Simple 2D wave update
    lap = (np.roll(u, 1, 0) + np.roll(u, -1, 0) +
           np.roll(u, 1, 1) + np.roll(u, -1, 1) - 4*u)
    v += C * lap
    u += v * 0.5
    u *= 0.997  # damping
    im.set_data(u)
    # Move cursor to highest-amplitude point
    iy, ix = np.unravel_index(np.argmax(np.abs(u)), u.shape)
    cursor.set_offsets([[ix * 8/N - 4, iy * 8/N - 4]])
    fig.savefig(...)
```

### Multi-Panel Composite (data-dashboard aesthetic)

For topics that have multiple facets (stats + time series + spatial distribution), use a GridSpec layout. Mobile safe only if you keep panels chunky:

```python
import matplotlib.gridspec as gridspec

fig = plt.figure(figsize=(9, 16), dpi=120)
fig.patch.set_facecolor('#0D0D0D')
gs = gridspec.GridSpec(3, 1, height_ratios=[3, 2, 2], hspace=0.35)

ax_big = fig.add_subplot(gs[0]);  ax_big.set_facecolor('#0D0D0D')
ax_mid = fig.add_subplot(gs[1]);  ax_mid.set_facecolor('#0D0D0D')
ax_sm  = fig.add_subplot(gs[2]);  ax_sm.set_facecolor('#0D0D0D')

# Each sub-axis has its own artists — initialize ONCE, update in loop
# Never call plt.subplots inside the loop
```

### Glow / Bloom Fake (cheap visual lift)

Matplotlib has no native bloom, but layering the same artist at increasing line widths + decreasing alpha fakes it convincingly:

```python
# Draw the same curve 4 times — widest+faintest first, crispest last
for lw, a in [(14, 0.08), (9, 0.14), (5, 0.24), (2, 1.0)]:
    ax.plot(x, y, color='#4FC3F7', lw=lw, alpha=a, solid_capstyle='round')
```

Apply this to any "hero" line (main data curve, highlighted trajectory) for immediate premium-look. Works in the frame loop — update each layer via `set_data`.

## Positioning — Safe Coordinate Bounds

For a figure with `xlim=(-5,5)`, `ylim=(-8.5, 8.5)`:
- Data region: keep within x∈[-4.5,4.5], y∈[-7.5,7.5]
- Title text: y = 8.0 (top, inside axes)
- Time/info text: y = -7.8, x = -4.5 (bottom-left)
- Legend: use `ax.legend(loc='upper right', bbox_to_anchor=(0.98, 0.98))`

Never use `tight_layout()` inside the frame loop — call it once before the loop if needed.

## Choosing the Right Pattern

Pick the simulation pattern that actually SERVES the concept — don't default to particles for every topic. Good choices:

| Topic shape | Pattern |
|-------------|---------|
| "Something flows / circulates" | Flow Field + Tracer Particles |
| "Shape A becomes shape B" | Manifold / Parametric Morph |
| "Wave or propagation on a medium" | Heatmap + Moving Indicator |
| "Compare multiple angles of one thing" | Multi-Panel Composite |
| "A single trajectory with dramatic motion" | Particle + Glow layering |
| "Pattern emerges from simple rules" | Vectorized cellular update + imshow |
| "Distribution shifts over time" | Animated histogram / density curve |

Avoid: a lone scattered cloud of dots floating aimlessly. Always give motion a REASON (field, gradient, rule, interaction).

## The "Not AI Slop" Checklist

Before submitting, verify:
1. **Motion has causation** — every moving thing is moving because of a rule, field, or interaction, not just a sine wave on position.
2. **At least one element uses glow layering** for visual punch.
3. **Easing is applied** — no raw linear interpolation on any transform.
4. **Color is restricted** — 2-3 accent colors max per scene, everything else is greyscale background.
5. **One focal point per frame** — the viewer's eye should know exactly where to look.
6. **Data is real or physically plausible** — not hand-waved constants picked for prettiness.

## Reference Files

- `references/simulations.md` — Particle gravity, orbital mechanics, fluid flow, wave PDE patterns

CRITICAL DYNAMIC REQUIREMENTS:
- Target Duration: {duration} seconds
- Exact frames required: {frames}
- Description: {description}

GENERATE ONLY PYTHON CODE. Be concise — use loops, helper functions, and avoid repeating similar code blocks. No markdown, no explanation:
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
    
    async def _run_simulation(self, script: str, output_dir: str):
        """Run the simulation script."""
        script_path = Path(output_dir) / "simulation.py"
        
        with open(script_path, "w") as f:
            f.write(script)
        
        logger.info(f"[PySim] Running simulation...")
        
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
            "-i", f"{frames_dir}/frame_%04d.png",
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
