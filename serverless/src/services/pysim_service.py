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


PYSIM_PROMPT = """# Matplotlib Segment Generation

Generate a complete, self-contained Python script that produces exactly N = int(duration * 30) frames
saved as frame_0000.png, frame_0001.png, etc. into OUTPUT_DIR (from environment variable).

## DEFAULT: 3D FIRST

**Always use mpl_toolkits.mplot3d when the topic has any spatial geometry.**
3D is the default. 2D is the exception (use only for 2D-native content like waveforms,
histograms, or 2D field maps where the third dimension adds nothing).

3D setup that MUST appear in every 3D script:
```python
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401 — registers projection
import numpy as np
import os

BG = '#0D0D0D'; BLUE = '#4FC3F7'; GOLD = '#FFD54F'; CORAL = '#FF7043'
MINT = '#80CBC4'; LAVENDER = '#CE93D8'; WARM_WHITE = '#F5F5F5'; DIM = '#424242'

OUTPUT_DIR = os.environ.get('OUTPUT_DIR', '/tmp/frames')
os.makedirs(OUTPUT_DIR, exist_ok=True)
DURATION = float(os.environ.get('DURATION', '8'))
FPS = 30
N_FRAMES = int(DURATION * FPS)

W, H = 1080, 1920

def ease(t):
    t = np.clip(t, 0.0, 1.0)
    return 0.5 - 0.5 * np.cos(np.pi * t)

def phase(t, start, end):
    if t <= start: return 0.0
    if t >= end: return 1.0
    return ease((t - start) / (end - start))

fig = plt.figure(figsize=(W/100, H/100), dpi=100, facecolor=BG)
ax = fig.add_subplot(111, projection='3d', facecolor=BG)
ax.set_axis_off()
ax.set_xlim(-2, 2); ax.set_ylim(-2, 2); ax.set_zlim(-2, 2)
ax.set_box_aspect((1, 1, 1.6))  # ALWAYS — keeps 3D box un-squashed in 9:16
```

Two rules that prevent the most common 3D failures:
1. `set_box_aspect((1, 1, 1.6))` — without this the 3D box looks crushed in portrait format
2. `ax.set_axis_off()` or set pane facecolors to `(0.05, 0.05, 0.05, 1)` — default grey panes look terrible on #0D0D0D

## The Artist Golden Rule

Build ALL artists ONCE before the frame loop. Update them inside the loop with set_* methods.
NEVER call ax.clear() inside the loop for non-surface content.

```python
# RIGHT — build once, update in loop
sc_electrons = ax.scatter(base[:, 0], base[:, 1], base[:, 2],
                          s=22, c=BLUE, alpha=0.80, depthshade=False)
for i in range(N_FRAMES):
    new_pos = base.copy(); new_pos[:, 2] += disp_z
    sc_electrons._offsets3d = (new_pos[:, 0], new_pos[:, 1], new_pos[:, 2])
    fig.savefig(f"{OUTPUT_DIR}/frame_{i:04d}.png", facecolor=BG, dpi=100)

# WRONG — causes flicker
for i in range(N_FRAMES):
    ax.clear()         # NEVER
    ax.scatter(...)    # NEVER recreate inside loop
```

EXCEPTION: `plot_surface` cannot be updated in place — use `surf.remove(); surf = ax.plot_surface(...)`
for morphing surfaces. Keep surface morphs to ≤ 60 grid resolution to stay fast.

## Easing — Always

Every animated quantity uses the `ease()` or `phase()` helpers. No raw linear interpolation.

```python
# Camera sweep
azim = -55 + 90 * ease(t)      # ease full segment
elev = 18 + 5 * np.sin(2*np.pi*t)  # gentle bob

# Multi-phase: label fades in 5%→15%, main motion 15%→80%
label_alpha = phase(t, 0.05, 0.15)
motion_progress = phase(t, 0.15, 0.80)
```

## Iris-local 3D Pattern Library

These are the high-frequency physical patterns. Use them directly when applicable.

### Pattern 1: Driven Oscillator (resonance sweep)
Bead on a spring whose drive frequency sweeps from 0.3ω₀ → 1.7ω₀. Shows resonance blowup.
```python
omega0 = 2.0 * np.pi; gamma = 0.55; F0 = 5.5; dt = 1.0/FPS
z = 0.0; vz = 0.0; phase_acc = 0.0; trail = []

def spring_path(z_bead, n_pts=140, n_coils=9, radius=0.34):
    s = np.linspace(0, 1, n_pts)
    z = 3.0 + (z_bead - 3.0) * s
    envelope = np.sin(np.pi * s) ** 0.55
    angle = 2*np.pi*n_coils*s
    return radius*envelope*np.cos(angle), radius*envelope*np.sin(angle), z

ax.set_xlim(-2,2); ax.set_ylim(-2,2); ax.set_zlim(-3.6,3.6)
ax.set_box_aspect((1,1,1.6))
ax.scatter([0],[0],[3.0], s=140, c=DIM, marker='s', depthshade=False)
sx0, sy0, sz0 = spring_path(0)
spring_line, = ax.plot(sx0, sy0, sz0, color=BLUE, lw=2.6, alpha=0.92)
bead = ax.scatter([0],[0],[0], s=420, c=GOLD, edgecolors=WARM_WHITE, lw=1.5, depthshade=False)
trail_sc = ax.scatter([],[],[], s=70, c=[], cmap='plasma', vmin=0, vmax=1, depthshade=False, alpha=0.85)

for i in range(N_FRAMES):
    gt = i / max(N_FRAMES-1, 1)
    omega = omega0 * (0.3 + 1.4 * ease(gt))
    phase_acc += omega * dt
    F = F0 * np.cos(phase_acc)
    a = -omega0**2 * z - gamma*vz + F
    vz += a*dt; z += vz*dt
    z = np.clip(z, -2.9, 2.9)
    sx,sy,sz = spring_path(z)
    spring_line.set_data(sx,sy); spring_line.set_3d_properties(sz)
    bead._offsets3d = ([0],[0],[z])
    trail.append(z); trail = trail[-36:]
    if len(trail)>1:
        tz=np.array(trail); trail_sc._offsets3d=(np.zeros_like(tz),np.zeros_like(tz),tz)
        trail_sc.set_array(np.linspace(0.05,0.95,len(tz)))
    ax.view_init(elev=14+4*np.sin(2*np.pi*gt), azim=25+75*ease(gt))
    fig.savefig(f"{OUTPUT_DIR}/frame_{i:04d}.png", facecolor=BG, dpi=100)
```

### Pattern 2: Electron Sea Sloshing (LSP / nanoparticle)
Gold nanoparticle: static ion cloud (GOLD scatter) + oscillating electron cloud (BLUE scatter).
Shows induced dipole as charge separation under an oscillating E-field.
```python
rng = np.random.default_rng(7); R = 0.95; Npart = 360
pts = []
while len(pts) < Npart:
    c = rng.uniform(-1,1,(Npart*2,3)); ok = c[np.linalg.norm(c,axis=1)<=1][:Npart-len(pts)]
    pts.extend(ok.tolist())
base = np.array(pts) * R

u=np.linspace(0,2*np.pi,40); v=np.linspace(0,np.pi,20)
ax.plot_wireframe(R*np.outer(np.cos(u),np.sin(v)),
                  R*np.outer(np.sin(u),np.sin(v)),
                  R*np.outer(np.ones_like(u),np.cos(v)), color=DIM, alpha=0.30, lw=0.6)
sc_ions = ax.scatter(base[:,0],base[:,1],base[:,2], s=18,c=GOLD,alpha=0.55,depthshade=False)
sc_e    = ax.scatter(base[:,0],base[:,1],base[:,2], s=22,c=BLUE,alpha=0.80,depthshade=False)

for i in range(N_FRAMES):
    t = i/max(N_FRAMES-1,1); e=ease(t)
    disp_z = -0.30 * np.sin(2*np.pi*2.0*t) * (0.4+0.6*e)
    np_ = base.copy(); np_[:,2] += disp_z
    sc_e._offsets3d = (np_[:,0], np_[:,1], np_[:,2])
    ax.view_init(elev=18+5*np.sin(2*np.pi*t), azim=-55+90*e)
    fig.savefig(f"{OUTPUT_DIR}/frame_{i:04d}.png", facecolor=BG, dpi=100)
```

### Pattern 3: Rotating camera around an object (azim sweep)
```python
azim_start, azim_end = -45, 45
for i in range(N_FRAMES):
    t = i/(N_FRAMES-1); te = ease(t)
    azim = azim_start + (azim_end - azim_start)*te
    elev = 18 + 6*np.sin(2*np.pi*t)  # gentle bob
    ax.view_init(elev=elev, azim=azim)
    fig.savefig(f"{OUTPUT_DIR}/frame_{i:04d}.png", facecolor=BG, dpi=100)
# Sweep no more than ~120° per segment — more disorients.
```

### Pattern 4: Vector field in 3D (electric/magnetic field, fluid)
```python
g = np.linspace(-1.5,1.5,8)  # 8x8x8 grid max — more = visual mush
Xg,Yg,Zg = np.meshgrid(g,g,g)
# Example: dipole field
r2 = Xg**2+Yg**2+Zg**2+0.1
U = 3*Xg*Zg/r2**2.5; V = 3*Yg*Zg/r2**2.5; W = (3*Zg**2-r2)/r2**2.5
ax.quiver(Xg,Yg,Zg,U,V,W, length=0.25, normalize=True, color=BLUE, alpha=0.6)
# Animate by rotating camera, not by re-quivering (re-quiver is slow)
for i in range(N_FRAMES):
    ax.view_init(elev=20+10*ease(i/(N_FRAMES-1)), azim=-60+120*ease(i/(N_FRAMES-1)))
    fig.savefig(f"{OUTPUT_DIR}/frame_{i:04d}.png", facecolor=BG, dpi=100)
```

### Pattern 5: Surface morph between two functions
```python
X,Y = np.meshgrid(np.linspace(-3,3,60), np.linspace(-3,3,60))
Za = np.sin(np.sqrt(X**2+Y**2)); Zb = X**2-Y**2
# plot_surface must be removed+redrawn for morphs
surf = ax.plot_surface(X,Y,Za, cmap='plasma', linewidth=0, antialiased=True)
for i in range(N_FRAMES):
    a = ease(i/(N_FRAMES-1)); Z = (1-a)*Za + a*Zb
    surf.remove()
    surf = ax.plot_surface(X,Y,Z, cmap='plasma', linewidth=0, antialiased=True)
    ax.view_init(elev=20+20*a, azim=-40+120*ease(i/(N_FRAMES-1)))
    fig.savefig(f"{OUTPUT_DIR}/frame_{i:04d}.png", facecolor=BG, dpi=100)
```

### Pattern 6: Index ellipsoid morph (birefringence, crystal optics)
```python
u_ = np.linspace(0,2*np.pi,60); v_ = np.linspace(0,np.pi,30)
a0,b0,c0 = 1.0,1.0,1.0   # sphere start
a1,b1,c1 = 1.6,0.8,1.0   # uniaxial ellipsoid end
surf = None
for i in range(N_FRAMES):
    te = ease(i/(N_FRAMES-1))
    a,b,c = a0+(a1-a0)*te, b0+(b1-b0)*te, c0+(c1-c0)*te
    sx = a*np.outer(np.cos(u_),np.sin(v_))
    sy = b*np.outer(np.sin(u_),np.sin(v_))
    sz = c*np.outer(np.ones_like(u_),np.cos(v_))
    if surf: surf.remove()
    surf = ax.plot_surface(sx,sy,sz, cmap='viridis', alpha=0.75, linewidth=0)
    ax.view_init(elev=20, azim=-45+90*te)
    fig.savefig(f"{OUTPUT_DIR}/frame_{i:04d}.png", facecolor=BG, dpi=100)
```

### Pattern 7: Glow / Bloom (cheap visual lift for any 3D line)
```python
# Layer same curve at increasing widths + decreasing alpha — fakes bloom
xs, ys, zs = trajectory_x, trajectory_y, trajectory_z
for lw, a in [(12, 0.06), (7, 0.14), (4, 0.28), (1.5, 1.0)]:
    ax.plot3D(xs, ys, zs, color=BLUE, lw=lw, alpha=a)
```

## 2D: Only When Geometry Is Truly 2D

Use standard 2D axes only for: waveforms vs time, spectra, 2D field maps (imshow),
histograms, 2D phase portraits. Setup:

```python
fig = plt.figure(figsize=(W/100, H/100), dpi=100, facecolor=BG)
ax = fig.add_subplot(111)
ax.set_facecolor(BG); ax.set_axis_off()
ax.set_xlim(-5,5); ax.set_ylim(-8.5,8.5)
# Build artists once, update in loop with set_data/set_ydata/set_offsets
```

## Text overlays (both 2D and 3D)

```python
# Title — placed with fig.text for 3D (axes text gets clipped by 3D view)
fig.text(0.5, 0.93, "Segment Title", ha='center', color=WARM_WHITE,
         fontsize=30, fontweight='bold', family='DejaVu Sans')
fig.text(0.5, 0.88, "subtitle or equation hint", ha='center',
         color=BLUE, fontsize=20, family='DejaVu Sans')
# Fade-in label
label = fig.text(0.10, 0.55, "label text", color=BLUE, fontsize=18,
                 family='DejaVu Sans', alpha=0.0)
# In loop:
label.set_alpha(phase(t, 0.05, 0.15))
```

CRITICAL DYNAMIC REQUIREMENTS:
- Target Duration: {duration} seconds
- Exact frames required: {frames}
- Description: {description}

GENERATE ONLY PYTHON CODE. No markdown, no explanation. Use the patterns above directly.
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
