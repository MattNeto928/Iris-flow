# Manim Vector Fields Reference

## Core Classes

### ArrowVectorField
Renders the field as a grid of arrows. Best for showing direction and magnitude at discrete points.

```python
from manim import *

def electric_field(pos):
    # Electric field from a positive charge at origin
    r = np.linalg.norm(pos[:2])
    if r < 0.1:
        return np.array([0, 0, 0])
    return pos / (r ** 3)

field = ArrowVectorField(
    electric_field,
    x_range=[-3.5, 3.5, 0.5],
    y_range=[-6.5, 6.5, 0.5],
    length_func=lambda norm: 0.35 * sigmoid(norm),  # Cap arrow length
    color=BLUE_C,
)
```

Color by magnitude using a color map:
```python
field = ArrowVectorField(
    func,
    x_range=[-3, 3, 0.4],
    y_range=[-6, 6, 0.4],
    colors=[BLUE_E, TEAL, GREEN, YELLOW, ORANGE, RED],  # low → high magnitude
)
```

### StreamLines
Renders continuous flow lines following the field. More fluid and cinematic than arrows.

```python
stream = StreamLines(
    func,
    x_range=[-3.5, 3.5],
    y_range=[-6.5, 6.5],
    dt=0.05,              # Integration step — smaller = more accurate
    virtual_time=3,       # How far each line flows
    n_repeats=1,          # Repetitions per starting point
    noise_factor=0,       # 0 = clean field lines, >0 = turbulent
    stroke_width=2,
    max_anchors_per_line=40,
)
```

### AnimatedStreamLines
Makes StreamLines flow continuously — the most cinematic option.

```python
stream = StreamLines(func, x_range=[-3, 3], y_range=[-6, 6], dt=0.05, virtual_time=3)
anim_stream = AnimatedStreamLines(stream, line_anim_class=ShowPassingFlash)

self.add(anim_stream)
self.wait(6)  # Let it flow for 6 seconds
```

Alternative with `Create` for draw-on effect:
```python
anim_stream = AnimatedStreamLines(stream, line_anim_class=Create)
```

## Common Field Functions

All functions take `pos: np.ndarray` (shape [3,]) and return `np.ndarray` (shape [3,]).

```python
# Rotation / vortex
def vortex(pos):
    x, y = pos[0], pos[1]
    return np.array([-y, x, 0]) / (np.sqrt(x**2 + y**2) + 0.1)

# Sink (convergent field)
def sink(pos):
    return -pos / (np.linalg.norm(pos) + 0.1)

# Source (divergent field)
def source(pos):
    return pos / (np.linalg.norm(pos) + 0.1)

# Saddle point
def saddle(pos):
    return np.array([pos[0], -pos[1], 0])

# Gravitational / electric (inverse-square)
def gravity(pos):
    r = np.linalg.norm(pos[:2])
    if r < 0.3:
        return np.array([0, 0, 0])
    return -pos / r**3

# Magnetic dipole (approximate)
def magnetic_dipole(pos):
    x, y = pos[0], pos[1]
    r2 = x**2 + y**2 + 0.01
    r = np.sqrt(r2)
    # Dipole pointing in y direction
    Bx = 3 * x * y / r2**2.5
    By = (2*y**2 - x**2) / r2**2.5
    return np.array([Bx, By, 0])

# Oscillator phase portrait (dx/dt = y, dy/dt = -x)
def harmonic_oscillator(pos):
    return np.array([pos[1], -pos[0], 0])

# Van der Pol oscillator (nonlinear, limit cycle)
def van_der_pol(pos, mu=1.0):
    x, y = pos[0], pos[1]
    return np.array([y, mu*(1 - x**2)*y - x, 0])

# Lorenz attractor (slice at z=0 for 2D display)
def lorenz_2d(pos, sigma=10, rho=28, beta=8/3):
    x, y = pos[0], pos[1]
    z = 1.0  # fixed slice
    return np.array([sigma*(y - x), x*(rho - z) - y, 0]) * 0.05  # scaled
```

## Phase Portrait Pattern (Educational Standard)

```python
class PhasePortrait(MovingCameraScene):
    def construct(self):
        self.camera.frame.set(frame_width=9)

        # Axes
        ax = Axes(
            x_range=[-3.5, 3.5, 1],
            y_range=[-6.5, 6.5, 1],
            axis_config={"color": GREY_D, "stroke_width": 1},
            tips=False,
        )

        # Axis labels
        x_label = MathTex("x", font_size=28, color=GREY_B).next_to(ax.x_axis, RIGHT, buff=0.15)
        y_label = MathTex(r"\dot{x}", font_size=28, color=GREY_B).next_to(ax.y_axis, UP, buff=0.15)

        # Stream lines — most cinematic choice for phase portraits
        stream = StreamLines(
            harmonic_oscillator,
            x_range=[-3.2, 3.2],
            y_range=[-6.0, 6.0],
            dt=0.05,
            virtual_time=4,
            stroke_width=1.5,
            colors=[BLUE_E, TEAL_C, GREEN_C],
        )
        anim_stream = AnimatedStreamLines(stream)

        title = Text("Simple Harmonic Oscillator", font="Roboto", font_size=34, color=WHITE)
        title.move_to(UP * 7.0)

        self.play(FadeIn(title), Create(ax), Write(x_label), Write(y_label), run_time=2.0)
        self.add(anim_stream)
        self.wait(5)

        # Equilibrium point
        eq_point = Dot(ax.c2p(0, 0), color=YELLOW, radius=0.12)
        eq_label = Text("equilibrium", font="Roboto", font_size=22, color=YELLOW)
        eq_label.next_to(eq_point, RIGHT, buff=0.2)
        self.play(FadeIn(eq_point), FadeIn(eq_label), run_time=1.0)
        self.wait(3.0)
```

## Animating Field Transitions

Morphing between two fields (e.g. stable → unstable):
```python
def stable_field(pos):
    return np.array([-pos[0], -pos[1], 0]) * 0.5

def unstable_field(pos):
    return np.array([pos[0], pos[1], 0]) * 0.5

field1 = ArrowVectorField(stable_field, x_range=[-3,3,0.5], y_range=[-6,6,0.5])
field2 = ArrowVectorField(unstable_field, x_range=[-3,3,0.5], y_range=[-6,6,0.5])

self.play(Create(field1), run_time=2)
self.wait(1)
self.play(Transform(field1, field2), rate_func=smooth, run_time=3.0)
```

## Particle Tracers Following Field

```python
class FlowingParticles(MovingCameraScene):
    def construct(self):
        self.camera.frame.set(frame_width=9)

        def func(pos):
            x, y = pos[0], pos[1]
            return np.array([-y, x - 0.1*x, 0])  # spiral inward

        # Background field (subtle)
        field = ArrowVectorField(func, x_range=[-3,3,0.6], y_range=[-6,6,0.6],
                                  length_func=lambda n: 0.2, color=GREY_D)
        self.add(field)

        # Particles that follow the field
        particles = VGroup()
        starts = [np.array([1.5, i, 0]) for i in np.linspace(-3, 3, 8)]
        for start in starts:
            p = Dot(start, radius=0.07, color=ELECTRIC_BLUE)
            particles.add(p)

        self.add(particles)

        # Animate each particle along a path computed by Euler integration
        dt = 0.05
        steps = 120  # 4 seconds at 30fps
        paths = []
        for p in particles:
            path = [p.get_center().copy()]
            pos = p.get_center().copy()
            for _ in range(steps):
                v = func(pos)
                pos = pos + v * dt
                path.append(pos.copy())
            paths.append(path)

        # Use UpdateFromAlphaFunc for smooth motion
        def make_updater(p, path):
            def updater(mob, alpha):
                idx = int(alpha * (len(path) - 1))
                idx = min(idx, len(path) - 1)
                mob.move_to(path[idx])
            return updater

        anims = [UpdateFromAlphaFunc(p, make_updater(p, path), run_time=4.0)
                 for p, path in zip(particles, paths)]
        self.play(*anims, rate_func=linear)
        self.wait(1.5)
```

## Gradient Descent Visualization

```python
def loss_surface_gradient(pos):
    x, y = pos[0], pos[1]
    # Bowl-shaped loss (x^2 + 2y^2)
    return np.array([-2*x, -4*y, 0]) * 0.3

class GradientDescent(MovingCameraScene):
    def construct(self):
        self.camera.frame.set(frame_width=9)

        field = ArrowVectorField(
            loss_surface_gradient,
            x_range=[-3, 3, 0.5],
            y_range=[-5, 5, 0.5],
            length_func=lambda n: 0.4 * np.tanh(n),
            colors=[RED, ORANGE, YELLOW, GREEN],
        )
        self.play(Create(field), run_time=2.5, rate_func=smooth)

        # Ball rolling down
        ball = Dot(np.array([2.5, 3.0, 0]), radius=0.15, color=WHITE)
        self.add(ball)

        # Euler-integrate path
        dt = 0.08
        pos = np.array([2.5, 3.0, 0.0])
        path_points = [pos.copy()]
        for _ in range(80):
            grad = loss_surface_gradient(pos)
            pos = pos + grad * dt
            path_points.append(pos.copy())

        path = VMobject(stroke_color=WHITE, stroke_width=2)
        path.set_points_as_corners(path_points)

        def updater(mob, alpha):
            idx = int(alpha * (len(path_points) - 1))
            mob.move_to(path_points[min(idx, len(path_points)-1)])

        self.play(
            UpdateFromAlphaFunc(ball, updater, run_time=5.0),
            Create(path, run_time=5.0),
            rate_func=linear,
        )
        self.wait(2)
```

## Positioning Tips for 9:16 Vertical

- Place the field in the **center** of the frame (y ∈ [-5, 5])
- Reserve **top** (y ∈ [5.5, 7.2]) for title/label
- Reserve **bottom** (y ∈ [-7.2, -5.5]) for equation or annotation
- Vertical orientation means wide vector fields (x ∈ [-3, 3]) look best when shorter (y ∈ [-5, 5])
- Use `NumberPlane` as a subtle background grid to give spatial context without distraction

## Performance Notes

- `ArrowVectorField` with small grid step (0.3) can create thousands of arrows — keep step ≥ 0.4 for performance
- `StreamLines` with `virtual_time > 5` is expensive — cap at 4
- `AnimatedStreamLines` runs indefinitely — always pair with `self.wait(N)` then `self.remove()`
- Use `stroke_width=1.5–2.0` for stream lines (thinner = less GPU load, more elegant)
