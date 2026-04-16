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


ASTRO_PROMPT = """# Astro Segment Generation

Astro segments visualize space, orbital mechanics, and astrophysics. Claude generates a complete Python script producing `N = int(duration * 30)` frames at 1080×1920 using matplotlib Agg + astropy.

## Mandatory Structure

```python
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib.patches import FancyArrowPatch
import numpy as np
from scipy.integrate import solve_ivp
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

SPACE_BG = '#000008'
STAR_WHITE = '#F8F8FF'

def ease_in_out_cubic(t):
    if t < 0.5: return 4 * t**3
    return 1 - (-2*t + 2)**3 / 2
```

## Realistic Star Field Background

Generate once, draw underneath everything else:

```python
def generate_starfield(n_stars=800, seed=42):
    \"\"\"Returns (x, y, size, alpha) arrays for a realistic star field.\"\"\"
    rng = np.random.default_rng(seed)
    x = rng.uniform(-4.5, 4.5, n_stars)
    y = rng.uniform(-8.5, 8.5, n_stars)
    # Most stars are dim — exponential size distribution
    raw_sizes = rng.exponential(scale=0.5, size=n_stars)
    sizes = np.clip(raw_sizes, 0.1, 4.0)
    alphas = np.clip(rng.beta(0.5, 2, n_stars), 0.05, 0.95)
    return x, y, sizes, alphas

sx, sy, ss, sa = generate_starfield(n_stars=600)

# Color: 80% white, 10% blue-white, 5% orange/red, 5% yellow
rng = np.random.default_rng(42)
star_colors = []
for _ in range(len(sx)):
    r = rng.random()
    if r < 0.80:   star_colors.append('#F8F8FF')
    elif r < 0.90: star_colors.append('#B0C4FF')  # blue-white (hot star)
    elif r < 0.95: star_colors.append('#FF9966')  # orange (cool giant)
    else:          star_colors.append('#FFE680')  # yellow (G-type)

fig, ax = plt.subplots(figsize=(9, 16), dpi=120)
fig.patch.set_facecolor(SPACE_BG)
ax.set_facecolor(SPACE_BG)
ax.set_xlim(-4.5, 4.5)
ax.set_ylim(-8.5, 8.5)
ax.axis('off')

# Draw star field (static — all frames share this)
for i in range(len(sx)):
    ax.plot(sx[i], sy[i], 'o', color=star_colors[i],
            markersize=ss[i], alpha=sa[i], markeredgewidth=0)
```

## Solar System Orbital Animation

```python
# Simplified solar system (inner planets + scaled sizes)
# Using circular orbits with Kepler's third law scaling
PLANETS = [
    # name, semi-major axis (AU scaled), period (days), color, visual_size
    ('Mercury', 0.8,  88,   '#B5B5B5', 6),
    ('Venus',   1.2,  225,  '#E8C56A', 9),
    ('Earth',   1.7,  365,  '#4FC3F7', 10),
    ('Mars',    2.3,  687,  '#FF7043', 7),
]
SUN_RADIUS = 0.3
SUN_COLOR  = '#FFE066'

# Draw Sun (with glow)
def draw_sun(ax, x=0, y=0):
    for r, alpha in [(0.8, 0.04), (0.5, 0.08), (0.3, 0.15)]:
        ax.add_patch(plt.Circle((x, y), r, color=SUN_COLOR, alpha=alpha, zorder=3))
    ax.add_patch(plt.Circle((x, y), SUN_RADIUS, color=SUN_COLOR, zorder=4))

# Draw orbits (dashed ellipses)
for name, sma, period, color, vis_size in PLANETS:
    orbit = plt.Circle((0, 0), sma, fill=False,
                        color=color, alpha=0.15, linewidth=0.8,
                        linestyle='--', zorder=2)
    ax.add_patch(orbit)

# Initial positions (random phases for visual interest)
rng = np.random.default_rng(7)
initial_phases = rng.uniform(0, 2*np.pi, len(PLANETS))

# Planet artists
planet_dots = []
planet_trails = []
TRAIL_LEN = 60  # frames

for i, (name, sma, period, color, vis_size) in enumerate(PLANETS):
    dot = ax.plot([], [], 'o', color=color, markersize=vis_size,
                  markeredgewidth=0, zorder=6)[0]
    trail, = ax.plot([], [], '-', color=color, alpha=0.25, linewidth=1, zorder=5)
    planet_dots.append(dot)
    planet_trails.append(trail)

draw_sun(ax)

# Simulate orbit
# Convert period to animation frames: one revolution = period proportional frames
ORBIT_SPEED = 2 * np.pi / 200  # Earth makes one orbit in 200 frames

trail_history = [[] for _ in PLANETS]

for frame_idx in range(N_FRAMES):
    for i, (name, sma, period, color, vis_size) in enumerate(PLANETS):
        # Angle: proportional to 1/period (faster inner, slower outer)
        ang_speed = ORBIT_SPEED * (365 / period)
        angle = initial_phases[i] + frame_idx * ang_speed
        x = sma * np.cos(angle)
        y = sma * np.sin(angle)

        planet_dots[i].set_data([x], [y])

        trail_history[i].append((x, y))
        if len(trail_history[i]) > TRAIL_LEN:
            trail_history[i].pop(0)

        trail_x = [p[0] for p in trail_history[i]]
        trail_y = [p[1] for p in trail_history[i]]
        planet_trails[i].set_data(trail_x, trail_y)

    fig.savefig(os.path.join(OUTPUT_DIR, f'frame_{frame_idx:04d}.png'),
                dpi=120, bbox_inches='tight', pad_inches=0,
                facecolor=SPACE_BG)
```

## Elliptical Orbit (Kepler's Laws)

```python
# True elliptical orbit with varying speed (Kepler's 2nd law)
def kepler_orbit(a, e, n_points=500):
    \"\"\"Returns (x, y, v) arrays for an elliptical orbit.\"\"\"
    # True anomaly
    nu = np.linspace(0, 2*np.pi, n_points)
    r = a * (1 - e**2) / (1 + e * np.cos(nu))
    x = r * np.cos(nu)
    y = r * np.sin(nu)
    # Angular momentum → speed proportional to 1/r
    v = 1 / r  # normalized
    return x, y, v

a, e = 2.5, 0.6  # semi-major axis, eccentricity
orb_x, orb_y, orb_v = kepler_orbit(a, e)

# Focus at origin, sun at focus
c = a * e  # center-to-focus distance
focus_x = -c

# Draw orbit
ax.plot(orb_x + focus_x, orb_y, color='#4FC3F7', alpha=0.3, lw=1,
        linestyle='--')

# Planet traces along orbit
planet = ax.plot([], [], 'o', color='#80CBC4', markersize=12,
                  markeredgewidth=0, zorder=6)[0]
trail, = ax.plot([], [], '-', color='#80CBC4', alpha=0.3, lw=1.5)

trail_hist = []
for frame_idx in range(N_FRAMES):
    # Map frame to position along orbit (weighted by speed for equal-time spacing)
    # Use cumulative arc length weighted by 1/v
    t = frame_idx / N_FRAMES
    idx = int(t * len(orb_x)) % len(orb_x)
    px = orb_x[idx] + focus_x
    py = orb_y[idx]
    planet.set_data([px], [py])
    trail_hist.append((px, py))
    if len(trail_hist) > 90:
        trail_hist.pop(0)
    trail.set_data([p[0] for p in trail_hist], [p[1] for p in trail_hist])
    fig.savefig(...)
```

## N-Body Gravitational Simulation

```python
G = 1.0

def nbody_deriv(t, state, masses):
    n = len(masses)
    pos = state[:2*n].reshape(n, 2)
    vel = state[2*n:].reshape(n, 2)
    acc = np.zeros((n, 2))
    for i in range(n):
        for j in range(n):
            if i == j: continue
            r = pos[j] - pos[i]
            dist = np.linalg.norm(r) + 0.3  # softening
            acc[i] += G * masses[j] * r / dist**3
    return np.concatenate([vel.flatten(), acc.flatten()])

# Initial conditions (figure-8 three-body problem)
masses = [1.0, 1.0, 1.0]
# Stable figure-8 initial conditions
p0 = np.array([
     0.97000436, -0.24308753, 0, 0,
    -0.97000436,  0.24308753, 0, 0,
     0.0, 0.0, 0, 0,
    # velocities
     0.93240737/2, 0.86473146/2,
     0.93240737/2, 0.86473146/2,
    -0.93240737,  -0.86473146,
])

sol = solve_ivp(nbody_deriv, [0, 20], p0,
                args=(masses,), max_step=0.01,
                t_eval=np.linspace(0, 20, N_FRAMES),
                method='RK45')

colors = ['#FF7043', '#4FC3F7', '#FFD54F']
trails = [[] for _ in range(3)]
dots = [ax.plot([], [], 'o', color=c, markersize=14, zorder=6)[0]
        for c in colors]
lines = [ax.plot([], [], '-', color=c, alpha=0.3, lw=1.5)[0]
         for c in colors]

for frame_idx in range(N_FRAMES):
    state = sol.y[:, frame_idx]
    for i in range(3):
        x, y = state[i*2] * 2, state[i*2+1] * 2  # scale up
        dots[i].set_data([x], [y])
        trails[i].append((x, y))
        if len(trails[i]) > 80: trails[i].pop(0)
        lines[i].set_data([p[0] for p in trails[i]],
                           [p[1] for p in trails[i]])
    fig.savefig(...)
```

## Black Hole Visualization (Artistic)

```python
# Gravitational lensing rings effect
from matplotlib.colors import LinearSegmentedColormap

fig, ax = plt.subplots(figsize=(9, 16), dpi=120)
fig.patch.set_facecolor('#000000')
ax.set_facecolor('#000000')
ax.set_xlim(-4.5, 4.5)
ax.set_ylim(-8.0, 8.0)
ax.axis('off')

# Star field
# ... (use generate_starfield from above) ...

# Accretion disk (animated rotation)
for frame_idx in range(N_FRAMES):
    t = frame_idx / max(N_FRAMES - 1, 1)
    phase = frame_idx / FPS * 0.5  # rotation speed

    ax_clear_except_stars = True  # manage layers

    # Event horizon (pure black circle)
    bh = plt.Circle((0, 0), 0.6, color='#000000', zorder=10)
    ax.add_patch(bh)

    # Photon sphere (glowing ring)
    for r, alpha in [(0.75, 0.6), (0.80, 0.4), (0.90, 0.2)]:
        ring = plt.Circle((0,0), r, fill=False,
                           edgecolor='#FFD54F', linewidth=2,
                           alpha=alpha, zorder=9)
        ax.add_patch(ring)

    # Accretion disk (elliptical, rotating glow)
    theta_disk = np.linspace(0, 2*np.pi, 200)
    for layer, (rx, ry, col, alph) in enumerate([
        (1.8, 0.3, '#FF6600', 0.6),
        (2.2, 0.35, '#FF4400', 0.4),
        (2.6, 0.4, '#CC2200', 0.25),
    ]):
        x_disk = rx * np.cos(theta_disk + phase * (1 + layer*0.2))
        y_disk = ry * np.sin(theta_disk + phase * (1 + layer*0.2))
        ax.plot(x_disk, y_disk, color=col, alpha=alph,
                lw=3 - layer*0.5, zorder=8)

    fig.savefig(...)
    # Clear dynamic elements for next frame (but keep stars)
    for patch in ax.patches[-3:]:
        patch.remove()
```

## Positioning Guide for Space Scenes

- **Title**: `ax.text(0, 7.8, title, ha='center', fontsize=26, color='#F5F5F5')`
- **Planet labels**: Small text next to planet dot, offset UP slightly
- **Scale bar**: Bottom of frame, `ax.text(-4, -7.8, "1 AU", fontsize=12, color='#555555')`
- **Orbit labels**: Along orbit line at 45° position, dimmed
- Keep focal object (sun/planet/black hole) centered or slightly above center in 9:16 frame
- Vertical format works beautifully for orbital planes viewed at an angle (tilt planet system ~20°)

CRITICAL DYNAMIC REQUIREMENTS:
- Target Duration: {duration} seconds
- Exact frames required: {frames}
- Description: {description}

GENERATE ONLY PYTHON CODE. Be concise — use loops, helper functions, and avoid repeating similar code blocks. No markdown, no explanation:
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
        """Run the astro visualization script."""
        script_path = Path(output_dir) / "visualization.py"
        
        with open(script_path, "w") as f:
            f.write(script)
        
        logger.info(f"[Astro] Running visualization...")
        
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
            logger.error(f"[Astro] FFmpeg failed: {stderr_text}")
            raise RuntimeError(f"FFmpeg compilation failed: {stderr_text}")
        
        logger.info(f"[Astro] Video compiled: {output_path}")
