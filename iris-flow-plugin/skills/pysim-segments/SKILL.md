---
name: pysim-segments
description: This skill should be used when generating matplotlib scientific simulation code for Iris-flow pysim segments, when writing Python scripts that render PNG frame sequences for physics simulations, particle systems, wave equations, orbital mechanics, or any scientific visualization using matplotlib with the Agg backend. Also applies to mesa and pymunk segment types.
version: 1.0.0
---

# PySim Segment Generation

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
    """t in [0,1] → eased value in [0,1]"""
    if t < 0.5:
        return 4 * t**3
    return 1 - (-2*t + 2)**3 / 2

def lerp(a, b, t):
    return a + (b - a) * t

# ── Frame loop ────────────────────────────────────────────────────────────────
for frame_idx in range(N_FRAMES):
    t = frame_idx / max(N_FRAMES - 1, 1)  # normalized time [0, 1]
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
print(f"Rendered {N_FRAMES} frames to {OUTPUT_DIR}")
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
    """Remap global t to [0,1] within a time window."""
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
ax.text(-4.5, -7.5, f"t = {sim_time:.2f}s",
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

for frame_idx in range(N_FRAMES):
    t = frame_idx / (N_FRAMES - 1)
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

for frame_idx in range(N_FRAMES):
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
for frame_idx in range(N_FRAMES):
    t = frame_idx / (N_FRAMES - 1)
    azim = -60 + ease_in_out_cubic(t) * 120  # rotate 120° total
    ax.view_init(elev=30, azim=azim)
    fig.savefig(...)
```

## Positioning — Safe Coordinate Bounds

For a figure with `xlim=(-5,5)`, `ylim=(-8.5, 8.5)`:
- Data region: keep within x∈[-4.5,4.5], y∈[-7.5,7.5]
- Title text: y = 8.0 (top, inside axes)
- Time/info text: y = -7.8, x = -4.5 (bottom-left)
- Legend: use `ax.legend(loc='upper right', bbox_to_anchor=(0.98, 0.98))`

Never use `tight_layout()` inside the frame loop — call it once before the loop if needed.

## Reference Files

- `references/simulations.md` — Particle gravity, orbital mechanics, fluid flow, wave PDE patterns
