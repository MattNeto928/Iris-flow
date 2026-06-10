---
name: plotly-segments
description: This skill should be used when generating Plotly 3D visualization code for Iris-flow plotly segments, when writing Python scripts that create 3D surface plots, scatter3d, mesh3d, or animated 3D scientific visualizations exported as PNG frames via Kaleido for video compilation.
version: 1.0.0
---

# Plotly Segment Generation

Plotly segments create cinematic 3D scientific visualizations. Claude generates a **complete Python script** that exports exactly `N = int(duration * 30)` PNG frames at 1080×1920 using Plotly + Kaleido, with smooth camera orbits and dark aesthetic.

## Mandatory Script Structure

```python
import plotly.graph_objects as go
import numpy as np
import os

OUTPUT_DIR = os.environ.get('OUTPUT_DIR', '/tmp/frames')
os.makedirs(OUTPUT_DIR, exist_ok=True)
DURATION = float(os.environ.get('DURATION', '8'))
FPS = 30
N_FRAMES = int(DURATION * FPS)

# ── Easing ────────────────────────────────────────────────────────────────────
def ease_in_out_cubic(t):
    if t < 0.5: return 4 * t**3
    return 1 - (-2*t + 2)**3 / 2

# ── Build figure ONCE ─────────────────────────────────────────────────────────
fig = go.Figure()

# ... add traces here ...

fig.update_layout(
    width=1080,
    height=1920,
    paper_bgcolor='#0D0D0D',
    plot_bgcolor='#0D0D0D',
    margin=dict(l=20, r=20, t=80, b=20),
    font=dict(family='Roboto, Helvetica Neue, sans-serif', color='#F5F5F5'),
    scene=dict(
        bgcolor='#0D0D0D',
        xaxis=dict(gridcolor='#1A1A1A', zerolinecolor='#2A2A2A', showbackground=False),
        yaxis=dict(gridcolor='#1A1A1A', zerolinecolor='#2A2A2A', showbackground=False),
        zaxis=dict(gridcolor='#1A1A1A', zerolinecolor='#2A2A2A', showbackground=False),
    ),
)

# ── Camera orbit path ─────────────────────────────────────────────────────────
def camera_at(theta, phi=0.5, r=2.2):
    """Spherical → cartesian camera eye."""
    return dict(
        x=r * np.sin(phi) * np.cos(theta),
        y=r * np.sin(phi) * np.sin(theta),
        z=r * np.cos(phi),
    )

# ── Frame loop ────────────────────────────────────────────────────────────────
for frame_idx in range(N_FRAMES):
    t = frame_idx / max(N_FRAMES - 1, 1)
    t_e = ease_in_out_cubic(t)

    # Update camera
    theta = -np.pi/4 + t_e * (2 * np.pi / 3)  # orbit 120°
    eye = camera_at(theta)
    fig.update_layout(scene_camera=dict(eye=eye, up=dict(x=0, y=0, z=1)))

    # Update data if needed (e.g. animated surface)
    # fig.data[0].update(z=new_z_values)

    fig.write_image(
        os.path.join(OUTPUT_DIR, f'frame_{frame_idx:04d}.png'),
        format='png',
        engine='kaleido',
        scale=1,
    )

print(f"Rendered {N_FRAMES} frames")
```

## Dark Theme — Complete Layout Template

```python
DARK_LAYOUT = dict(
    paper_bgcolor='#0D0D0D',
    plot_bgcolor='#0D0D0D',
    font=dict(family='Roboto, Helvetica Neue, sans-serif', size=14, color='#F5F5F5'),
    title=dict(
        font=dict(size=28, color='#F5F5F5'),
        x=0.5, xanchor='center',
        y=0.97, yanchor='top',
    ),
    scene=dict(
        bgcolor='#0D0D0D',
        xaxis=dict(
            backgroundcolor='#0D0D0D',
            gridcolor='#1E1E1E',
            showbackground=True,
            zerolinecolor='#2A2A2A',
            tickfont=dict(color='#606060'),
            title=dict(font=dict(color='#909090')),
        ),
        yaxis=dict(
            backgroundcolor='#111111',
            gridcolor='#1E1E1E',
            showbackground=True,
            zerolinecolor='#2A2A2A',
            tickfont=dict(color='#606060'),
            title=dict(font=dict(color='#909090')),
        ),
        zaxis=dict(
            backgroundcolor='#0D0D0D',
            gridcolor='#1E1E1E',
            showbackground=True,
            zerolinecolor='#2A2A2A',
            tickfont=dict(color='#606060'),
            title=dict(font=dict(color='#909090')),
        ),
        aspectmode='cube',  # or 'data', 'auto'
    ),
    margin=dict(l=20, r=20, t=80, b=20),
    coloraxis_colorbar=dict(
        thickness=12,
        len=0.5,
        x=0.92,       # right side, within frame
        y=0.5,
        tickfont=dict(color='#909090'),
    ),
)
```

## 3D Trace Types

### Surface Plot
```python
x = np.linspace(-3, 3, 80)
y = np.linspace(-3, 3, 80)
X, Y = np.meshgrid(x, y)
Z = np.sin(np.sqrt(X**2 + Y**2)) * np.exp(-0.15 * (X**2 + Y**2))

surf = go.Surface(
    x=X, y=Y, z=Z,
    colorscale='Plasma',       # or 'Viridis', 'Inferno', 'Magma', 'Turbo'
    showscale=True,
    opacity=1.0,
    lighting=dict(ambient=0.5, diffuse=0.8, roughness=0.3, specular=0.5),
    lightposition=dict(x=1000, y=1000, z=1000),
    contours=dict(z=dict(show=True, color='rgba(255,255,255,0.15)', width=1)),
)
fig.add_trace(surf)
```

### Scatter3d (Points / Trails)
```python
scatter = go.Scatter3d(
    x=xs, y=ys, z=zs,
    mode='lines+markers',
    line=dict(color='#4FC3F7', width=2),
    marker=dict(size=3, color=zs, colorscale='Plasma', opacity=0.8),
)
```

### Isosurface
```python
# Visualize a scalar field at a threshold
iso = go.Isosurface(
    x=X.flatten(), y=Y.flatten(), z=Z_vol.flatten(),
    value=field.flatten(),
    isomin=0.3, isomax=0.8,
    surface_count=3,
    colorscale='Viridis',
    caps=dict(x_show=False, y_show=False, z_show=False),
    opacity=0.7,
)
```

## Camera Orbit Patterns

```python
# Full 360° orbit (constant elevation)
theta = -np.pi/4 + t * 2 * np.pi
eye = camera_at(theta, phi=0.55, r=2.2)

# Orbit + elevation change (helical)
theta = -np.pi/4 + t * np.pi
phi = 0.3 + t * 0.4  # rising from 0.3 to 0.7
eye = camera_at(theta, phi=phi, r=2.2)

# Zoom in while orbiting
r = 2.5 - t_e * 0.8  # zoom from 2.5 to 1.7
theta = -np.pi/4 + t * np.pi / 2
eye = camera_at(theta, phi=0.5, r=r)

# Eased orbit — slow-in slow-out over 120°
theta = -np.pi/4 + ease_in_out_cubic(t) * (2*np.pi/3)
eye = camera_at(theta)
```

## Animated Surface (Data Changes Per Frame)

```python
x = np.linspace(-3, 3, 60)
y = np.linspace(-3, 3, 60)
X, Y = np.meshgrid(x, y)

fig.add_trace(go.Surface(x=X, y=Y, z=np.zeros_like(X), colorscale='Plasma'))

for frame_idx in range(N_FRAMES):
    t_sec = frame_idx / FPS
    Z = np.sin(np.sqrt(X**2 + Y**2) - t_sec * 2) * np.exp(-0.1*(X**2+Y**2))
    fig.data[0].z = Z

    # Update camera
    theta = -np.pi/4 + (frame_idx/N_FRAMES) * np.pi
    fig.update_layout(scene_camera=dict(
        eye=camera_at(theta),
        up=dict(x=0, y=0, z=1)
    ))

    fig.write_image(f'{OUTPUT_DIR}/frame_{frame_idx:04d}.png',
                    engine='kaleido', scale=1)
```

## Colorscales for Dark Background

Best Plotly colorscales on dark backgrounds (most → least recommended):
1. `'Plasma'` — purple → orange → yellow (vibrant, high contrast)
2. `'Inferno'` — black → purple → orange → yellow (dramatic)
3. `'Magma'` — black → purple → pink → cream
4. `'Viridis'` — purple → teal → yellow (perceptually uniform)
5. `'Turbo'` — full rainbow, very vivid
6. `'Hot'` — black → red → orange → white
7. Custom: `[[0,'#0D0D0D'],[0.5,'#4FC3F7'],[1,'#FFD54F']]`

## Colorbar Positioning (9:16 Vertical)

Critical for vertical format — colorbar must not overlap the 3D scene:
```python
coloraxis_colorbar=dict(
    thickness=10,
    len=0.4,        # 40% of figure height
    x=0.93,         # rightmost safe position
    y=0.25,         # lower third (below scene center)
    title=dict(text="", font=dict(size=11)),
    tickfont=dict(size=11, color='#808080'),
)
```

Or disable colorbar and use a simple title annotation instead:
```python
surf = go.Surface(..., showscale=False)
fig.add_annotation(text="Amplitude", x=1.0, y=0.25, xref='paper', yref='paper',
                   showarrow=False, font=dict(size=13, color='#909090'))
```

## Performance

- Kaleido is slow (~0.5–2s per frame). For 8s at 30fps = 240 frames → ~2–8 minutes render time. This is expected.
- Reduce surface resolution for animated surfaces: `resolution=(40,40)` instead of `(80,80)`
- Never re-create `go.Figure()` per frame — update in-place
- Use `fig.data[0].z = new_z` (direct attribute update) not `fig.update_traces(z=new_z)` — it's faster
