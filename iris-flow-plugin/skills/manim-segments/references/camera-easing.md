# Manim Camera & Easing Reference

## MovingCameraScene Setup

Always use `MovingCameraScene`. Never use plain `Scene` in Iris-flow segments.

```python
class MyScene(MovingCameraScene):
    def construct(self):
        # Set initial frame to match 9:16 vertical
        self.camera.frame.set(frame_width=9)
        # frame_height auto-adjusts to 16 based on pixel ratio
```

## Camera Properties

```python
# Access the camera frame
frame = self.camera.frame

# Get current state
current_width = frame.width       # frame_width
current_center = frame.get_center()

# Set in config
frame.set(frame_width=9)          # reset zoom
frame.move_to(ORIGIN)             # reset position
```

## Zoom Patterns

### Zoom In to Detail
```python
# Smoothly zoom into an equation
self.play(
    self.camera.animate.set(frame_width=4).move_to(eq.get_center()),
    rate_func=smooth,
    run_time=3.0,
)
self.wait(2.0)

# Zoom back out
self.play(
    self.camera.animate.set(frame_width=9).move_to(ORIGIN),
    rate_func=smooth,
    run_time=2.5,
)
```

### Reveal by Zooming Out
Start zoomed in on a detail, then pull back to reveal full picture:
```python
# Start tight
self.camera.frame.set(frame_width=3)
self.camera.frame.move_to(point_of_interest)

# Add content (not visible to viewer yet, outside frame)
self.add(full_scene_content)

# Reveal
self.play(
    self.camera.animate.set(frame_width=9).move_to(ORIGIN),
    rate_func=smooth,
    run_time=4.0,
)
```

### Cinematic Pan
```python
# Pan across equation steps
steps = [eq1, eq2, eq3]  # positioned left-to-right or top-to-bottom
for step in steps:
    self.play(
        self.camera.animate.move_to(step.get_center()),
        rate_func=smooth,
        run_time=2.0,
    )
    self.wait(1.5)
```

## Rate Functions — Complete Reference

```python
from manim import *

# Built-in rate functions (all importable from manim)
smooth              # Sine ease-in-out — default for most animations
linear              # Constant speed — for continuous rotation/scrolling only
rush_into           # Fast start, slow end (ease-in)
rush_from           # Slow start, fast end (ease-out)
slow_into           # Very gradual acceleration
there_and_back      # Goes to target and returns (for emphasis/pulse)
there_and_back_with_pause   # Same but holds at target briefly
ease_in_sine        # Sine ease-in
ease_out_sine       # Sine ease-out
ease_in_out_sine    # Sine ease-in-out (similar to smooth)
ease_in_cubic       # Cubic ease-in
ease_out_cubic      # Cubic ease-out (great for settling/landing)
ease_in_out_cubic   # Cubic ease-in-out (slightly more pronounced than smooth)
ease_in_quint       # Strong acceleration
ease_out_quint      # Strong deceleration
double_smooth       # Smooth applied twice — very soft
```

### Custom Rate Functions
```python
# Overshoot (spring effect)
def overshoot(t):
    return smooth(t) + 0.1 * np.sin(4 * np.pi * t) * (1 - t)

# Stepped ease (for discrete reveals)
def stepped(n):
    def func(t):
        return np.floor(t * n) / n
    return func

self.play(Create(obj), rate_func=overshoot, run_time=2.0)
```

## Easing Decision Guide

| Situation | Rate Function | run_time |
|-----------|--------------|----------|
| Object appears | `ease_out_cubic` | 1.0–1.5 |
| Object disappears | `ease_in_cubic` | 0.8–1.0 |
| Camera zoom | `smooth` | 2.5–4.0 |
| Camera pan | `smooth` | 2.0–3.0 |
| Equation writes | `linear` | 2.0–3.5 |
| Transform/morph | `smooth` | 1.5–2.5 |
| Pulsing emphasis | `there_and_back` | 1.5 |
| Continuous rotation | `linear` | varies |
| Graph plotting | `smooth` | 2.0–3.0 |
| Particle motion | `linear` | varies |

## Multi-Step Camera Choreography

```python
class CinematicScene(MovingCameraScene):
    def construct(self):
        # Phase 1: Start wide, show title
        self.camera.frame.set(frame_width=9)
        title = Text("The Fourier Transform", font="Roboto", font_size=44, color=WHITE)
        title.move_to(UP * 6.5)
        self.play(FadeIn(title, shift=DOWN*0.3), rate_func=ease_out_cubic, run_time=1.5)
        self.wait(1.0)

        # Phase 2: Build main visual in center
        # ... add equations, graphs ...

        # Phase 3: Zoom to key formula
        key_formula = MathTex(r"\hat{f}(\xi) = \int_{-\infty}^{\infty} f(x)e^{-2\pi i \xi x}dx")
        key_formula.move_to(ORIGIN)
        self.play(Write(key_formula), run_time=3.0)
        self.wait(1.0)

        self.play(
            self.camera.animate.set(frame_width=5).move_to(key_formula.get_center()),
            rate_func=smooth,
            run_time=3.0,
        )
        self.wait(2.0)

        # Phase 4: Pull back to show consequence
        self.play(
            self.camera.animate.set(frame_width=9).move_to(ORIGIN),
            rate_func=smooth,
            run_time=2.5,
        )
        self.wait(2.0)
```

## Safe Zoom Ranges

| frame_width | What's visible | Use for |
|-------------|---------------|---------|
| 2–3 | Single equation, tight detail | Extreme emphasis |
| 4–5 | Small diagram + label | Formula focus |
| 6–7 | Half of scene | Mid-range |
| 9 | Full vertical frame (default) | Normal view |
| 10–12 | Reveals surrounding context | Pullback reveal |

Never go below `frame_width=2` or above `frame_width=14`.
