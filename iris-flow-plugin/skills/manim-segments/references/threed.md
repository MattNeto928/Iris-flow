# Manim 3D Scenes Reference

## ThreeDScene Setup

```python
from manim import *
import numpy as np

config.pixel_width = 1080
config.pixel_height = 1920
config.frame_rate = 30

class My3DScene(ThreeDScene):
    def construct(self):
        # Set camera orientation (phi = elevation angle, theta = azimuth)
        self.set_camera_orientation(phi=65 * DEGREES, theta=-45 * DEGREES)
        self.camera.set_zoom(1.2)
```

## Camera Angles Reference

```python
# phi: 0 = top-down, 90 = side view, 60-75 = classic 3D perspective
# theta: rotates around vertical axis

# Classic 3D view
self.set_camera_orientation(phi=70 * DEGREES, theta=-60 * DEGREES)

# Top-down
self.set_camera_orientation(phi=0 * DEGREES, theta=0)

# Front view (essentially 2D)
self.set_camera_orientation(phi=90 * DEGREES, theta=0)

# Isometric-ish
self.set_camera_orientation(phi=55 * DEGREES, theta=-45 * DEGREES)
```

## Smooth 3D Camera Rotation

```python
# Continuous ambient rotation — very cinematic
self.begin_ambient_camera_rotation(rate=0.2)  # radians/second
self.wait(8)  # rotate for 8 seconds
self.stop_ambient_camera_rotation()

# Animate to a specific angle
self.move_camera(phi=75 * DEGREES, theta=-90 * DEGREES, run_time=3, rate_func=smooth)
self.wait(1.5)
self.move_camera(phi=60 * DEGREES, theta=-30 * DEGREES, run_time=3, rate_func=smooth)
```

## Parametric Surface

```python
# Smooth mathematical surface
surface = Surface(
    lambda u, v: np.array([
        u,                      # x
        v,                      # y
        np.sin(u) * np.cos(v),  # z
    ]),
    u_range=[-3, 3],
    v_range=[-3, 3],
    resolution=(30, 30),  # Higher = smoother, more expensive
    checkerboard_colors=[BLUE_D, BLUE_E],
    stroke_width=0.5,
    stroke_color=WHITE,
    stroke_opacity=0.3,
)

self.play(Create(surface), run_time=3.0, rate_func=smooth)
```

### Common Surfaces
```python
# Saddle / hyperbolic paraboloid
lambda u, v: np.array([u, v, u**2 - v**2])

# Torus
R, r = 2, 0.5
lambda u, v: np.array([
    (R + r*np.cos(v)) * np.cos(u),
    (R + r*np.cos(v)) * np.sin(u),
    r * np.sin(v),
])

# Möbius strip
lambda u, v: np.array([
    (1 + v/2 * np.cos(u/2)) * np.cos(u),
    (1 + v/2 * np.cos(u/2)) * np.sin(u),
    v/2 * np.sin(u/2),
])

# Gaussian bell
lambda u, v: np.array([u, v, np.exp(-(u**2 + v**2))])

# Sphere
lambda u, v: np.array([
    np.sin(u) * np.cos(v),
    np.sin(u) * np.sin(v),
    np.cos(u),
])
```

## Color by Z-value (Height Mapping)

```python
surface = Surface(
    lambda u, v: np.array([u, v, np.sin(np.sqrt(u**2 + v**2))]),
    u_range=[-3, 3],
    v_range=[-3, 3],
    resolution=(40, 40),
)

# Color by height
surface.set_fill_by_value(
    axes=ThreeDAxes(),
    colors=[(BLUE, -1), (GREEN, 0), (YELLOW, 0.5), (RED, 1)],
    axis=2,  # z-axis
)
```

## 3D Axes

```python
axes = ThreeDAxes(
    x_range=[-3, 3, 1],
    y_range=[-3, 3, 1],
    z_range=[-2, 2, 1],
    x_length=6,
    y_length=6,
    z_length=4,
    axis_config={"color": GREY_C},
    tips=True,
)
labels = axes.get_axis_labels(
    x_label="x", y_label="y", z_label="z"
)
```

## 3D Parametric Curve

```python
# Helix
helix = ParametricFunction(
    lambda t: np.array([np.cos(t), np.sin(t), t / (2*PI)]),
    t_range=[0, 4*PI],
    color=BLUE_C,
    stroke_width=3,
)
self.play(Create(helix), run_time=4.0, rate_func=smooth)

# Lorenz attractor
sigma, rho, beta = 10, 28, 8/3
def lorenz(t, state):
    x, y, z = state
    return [sigma*(y-x), x*(rho-z)-y, x*y-beta*z]

from scipy.integrate import solve_ivp
sol = solve_ivp(lorenz, [0, 30], [1, 1, 1], max_step=0.01, dense_output=True)
t_vals = np.linspace(0, 30, 3000)
pts = sol.sol(t_vals).T

lorenz_curve = VMobject(stroke_color=BLUE_C, stroke_width=1.5)
lorenz_curve.set_points_smoothly([np.array([x/10, y/10, z/15]) for x,y,z in pts])
self.play(Create(lorenz_curve), run_time=8.0, rate_func=linear)
```

## Positioning in 3D for 9:16

- Keep 3D content centered near ORIGIN
- Use `self.camera.set_zoom(1.0–1.5)` to adjust apparent size
- `phi=65–75 DEGREES` gives best depth perception while keeping content on screen
- Large surfaces: scale down by 0.5–0.7 to fit vertical frame
- Add `ThreeDAxes` only if axes add educational value (not just decoration)
- Title text: add as `always_rotate` to face camera, or use `add_fixed_in_frame_mobjects`

```python
# Text always facing camera
title = Text("Gaussian Surface", font="Roboto", font_size=36)
self.add_fixed_in_frame_mobjects(title)
title.to_corner(UL)  # Fixed screen position
```
