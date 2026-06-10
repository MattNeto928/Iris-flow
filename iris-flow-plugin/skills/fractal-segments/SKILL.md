---
name: fractal-segments
description: This skill should be used when generating fractal visualization code for Iris-flow fractal segments, including Mandelbrot set, Julia sets, Newton fractals, L-systems, and Conway's Game of Life. Uses Numba JIT compilation for performance-critical pixel loops and matplotlib Agg for frame output.
version: 1.0.0
---

# Fractal Segment Generation

Fractal segments render mathematically-generated imagery using Numba for performance. Claude generates a complete Python script producing `N = int(duration * 30)` PNG frames at 1080×1920 with cinematic zoom or parameter animation.

## Mandatory Structure

```python
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from numba import njit, prange
import os

OUTPUT_DIR = os.environ.get('OUTPUT_DIR', '/tmp/frames')
os.makedirs(OUTPUT_DIR, exist_ok=True)
DURATION = float(os.environ.get('DURATION', '8'))
FPS = 30
N_FRAMES = int(DURATION * FPS)

WIDTH, HEIGHT = 1080, 1920

plt.rcParams.update({
    'font.family': 'sans-serif',
    'font.sans-serif': ['Roboto', 'Helvetica Neue', 'DejaVu Sans'],
})

fig, ax = plt.subplots(figsize=(9, 16), dpi=120)
fig.patch.set_facecolor('#000000')
ax.set_facecolor('#000000')
ax.axis('off')
plt.subplots_adjust(left=0, right=1, top=1, bottom=0)

def ease_in_out_cubic(t):
    if t < 0.5: return 4 * t**3
    return 1 - (-2*t + 2)**3 / 2
```

## Numba — JIT Compilation

Always use `@njit(parallel=True)` for the escape-time inner loop. Never use Python loops over pixels.

```python
from numba import njit, prange

# MUST call once before frame loop to trigger JIT compilation
# Pass dummy args to warm up
@njit(parallel=True, cache=True)
def mandelbrot_escape(cx_min, cx_max, cy_min, cy_max, width, height, max_iter):
    """Returns iteration count array [height, width]."""
    result = np.zeros((height, width), dtype=np.float64)
    for py in prange(height):
        cy = cy_min + (cy_max - cy_min) * py / height
        for px in range(width):
            cx = cx_min + (cx_max - cx_min) * px / width
            x, y = 0.0, 0.0
            for i in range(max_iter):
                x2, y2 = x*x, y*y
                if x2 + y2 > 4.0:
                    # Smooth coloring: fractional escape count
                    log_zn = np.log(x2 + y2) / 2
                    nu = np.log(log_zn / np.log(2)) / np.log(2)
                    result[py, px] = i + 1 - nu
                    break
                y = 2*x*y + cy
                x = x2 - y2 + cx
            else:
                result[py, px] = 0.0  # inside set
    return result

# Warm up JIT (mandatory — first call compiles, subsequent calls are fast)
_ = mandelbrot_escape(-2.0, 0.5, -1.25, 1.25, 64, 64, 50)
```

## Mandelbrot Zoom Animation

```python
# Target zoom coordinates (interesting region)
TARGET_X = -0.7269
TARGET_Y = 0.1889
ZOOM_START = 3.5    # initial view width
ZOOM_END = 0.002    # final view width (logarithmic zoom)

img_artist = ax.imshow(
    np.zeros((HEIGHT, WIDTH)),
    extent=[0, 1, 0, 1],  # dummy, we just need the artist
    cmap='inferno',
    origin='lower',
    interpolation='bilinear',
    vmin=0, vmax=1,
    aspect='auto',
)

for frame_idx in range(N_FRAMES):
    t = frame_idx / max(N_FRAMES - 1, 1)
    t_e = ease_in_out_cubic(t)

    # Logarithmic zoom — feels natural
    zoom = ZOOM_START * (ZOOM_END / ZOOM_START) ** t_e
    aspect = HEIGHT / WIDTH  # 1920/1080

    cx_min = TARGET_X - zoom / 2
    cx_max = TARGET_X + zoom / 2
    cy_min = TARGET_Y - zoom * aspect / 2
    cy_max = TARGET_Y + zoom * aspect / 2

    max_iter = int(50 + 200 * t_e)  # increase detail as we zoom

    raw = mandelbrot_escape(cx_min, cx_max, cy_min, cy_max, WIDTH, HEIGHT, max_iter)

    # Normalize using histogram equalization for contrast
    inside = raw == 0
    outside = raw > 0
    if outside.sum() > 0:
        flat = raw[outside]
        # Percentile stretch
        lo, hi = np.percentile(flat, 2), np.percentile(flat, 98)
        normed = np.clip((raw - lo) / (hi - lo + 1e-8), 0, 1)
        normed[inside] = 0
    else:
        normed = raw / (max_iter + 1e-8)

    img_artist.set_data(normed)
    img_artist.set_clim(0, 1)

    fig.savefig(
        os.path.join(OUTPUT_DIR, f'frame_{frame_idx:04d}.png'),
        dpi=120, bbox_inches='tight', pad_inches=0,
        facecolor='#000000',
    )

plt.close(fig)
```

## Julia Set Animation

Animate the `c` parameter along a smooth path for mesmerizing morphing:

```python
@njit(parallel=True, cache=True)
def julia_escape(cx_min, cx_max, cy_min, cy_max, cr, ci, width, height, max_iter):
    result = np.zeros((height, width), dtype=np.float64)
    for py in prange(height):
        zy = cy_min + (cy_max - cy_min) * py / height
        for px in range(width):
            zx = cx_min + (cx_max - cx_min) * px / width
            x, y = zx, zy
            for i in range(max_iter):
                x2, y2 = x*x, y*y
                if x2 + y2 > 4.0:
                    log_zn = np.log(x2 + y2) / 2
                    nu = np.log(log_zn / np.log(2)) / np.log(2)
                    result[py, px] = i + 1 - nu
                    break
                x, y = x2 - y2 + cr, 2*x*y + ci
    return result

# Warm up
_ = julia_escape(-1.5, 1.5, -1.5, 1.5, -0.4, 0.6, 32, 32, 30)

# Animate c along a circle in parameter space
for frame_idx in range(N_FRAMES):
    t = frame_idx / max(N_FRAMES - 1, 1)
    # Smooth parameter path
    angle = 2 * np.pi * t * 0.5  # half revolution
    cr = 0.7885 * np.cos(angle)
    ci = 0.7885 * np.sin(angle)

    raw = julia_escape(-1.8, 1.8, -3.2, 3.2, cr, ci, WIDTH, HEIGHT, 120)
    # normalize + imshow + save...
```

## Colormaps for Fractals

```python
# Best single colormaps for fractals (apply to imshow)
'inferno'    # black→purple→orange→yellow — very dramatic
'magma'      # black→purple→pink→cream
'twilight'   # cyclic — good for phase/angle
'hot'        # black→red→orange→white
'plasma'     # purple→orange→yellow
'gist_heat'  # black→red→yellow→white

# Custom: map escape count to HSV for classic rainbow fractal
def escape_to_rgb(normed):
    """normed: float array [0,1], returns uint8 [H, W, 3]"""
    import matplotlib.colors as mcolors
    cmap = plt.get_cmap('inferno')
    rgba = cmap(normed)
    return (rgba[:, :, :3] * 255).astype(np.uint8)
```

## L-System Animation

```python
def apply_rules(axiom, rules, n):
    s = axiom
    for _ in range(n):
        s = ''.join(rules.get(c, c) for c in s)
    return s

def lsystem_to_path(instructions, angle_deg=25, step=0.15):
    """Convert L-system string to list of (x, y) coordinates."""
    x, y, angle = 0.0, 0.0, 90.0
    stack = []
    path = [(x, y)]
    for cmd in instructions:
        if cmd in 'Ff':
            rad = np.radians(angle)
            x += step * np.cos(rad)
            y += step * np.sin(rad)
            path.append((x, y))
        elif cmd == '+':
            angle += angle_deg
        elif cmd == '-':
            angle -= angle_deg
        elif cmd == '[':
            stack.append((x, y, angle))
        elif cmd == ']':
            x, y, angle = stack.pop()
            path.append((x, y))
    return np.array(path)

# Dragon curve
rules = {'X': 'X+YF+', 'Y': '-FX-Y', 'F': 'F'}
axiom = 'FX'
for n in range(1, 14):
    s = apply_rules(axiom, rules, n)
    path = lsystem_to_path(s, angle_deg=90, step=0.05)
    # Animate growth frame-by-frame: draw first k% of path per frame
```

## Positioning and Labels

```python
# Title overlaid at top
ax.text(0.5, 0.97, "Mandelbrot Set", transform=ax.transAxes,
        ha='center', va='top', fontsize=24, color='#F5F5F5',
        fontfamily='Roboto', alpha=0.9)

# Zoom level / coordinates at bottom
ax.text(0.02, 0.02, f"zoom: {1/zoom:.0f}x", transform=ax.transAxes,
        ha='left', va='bottom', fontsize=12, color='#555555', fontfamily='Roboto')
```

## Performance Notes

- `@njit(parallel=True, cache=True)` — `cache=True` avoids recompiling across runs
- First call always compiles — call with small dummy data before frame loop
- 1080×1920 @ max_iter=200 takes ~0.3–1.0s per frame depending on CPU cores
- Increase `max_iter` as zoom increases (deeper zoom needs more iterations to show detail)
- `prange` in outer loop, `range` in inner — Numba parallelizes the outer dimension
