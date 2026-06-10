# PySim Scientific Simulation Patterns

## N-Body Gravity Simulation

```python
import numpy as np

N = 8
G = 1.0
SOFTENING = 0.3  # prevents singularity

# Initialize
masses = np.random.uniform(0.5, 3.0, N)
pos = np.random.uniform(-3, 3, (N, 2))
vel = np.random.randn(N, 2) * 0.3

def compute_accelerations(pos, masses):
    """Vectorized N-body gravitational acceleration."""
    dx = pos[:, 0:1] - pos[:, 0]  # (N, N) pairwise differences
    dy = pos[:, 1:2] - pos[:, 1]
    r2 = dx**2 + dy**2 + SOFTENING**2
    r3 = r2 ** 1.5
    with np.errstate(divide='ignore', invalid='ignore'):
        ax_mat = -G * masses * dx / r3
        ay_mat = -G * masses * dy / r3
    np.fill_diagonal(ax_mat, 0)
    np.fill_diagonal(ay_mat, 0)
    return np.column_stack([ax_mat.sum(axis=1), ay_mat.sum(axis=1)])

dt = 1.0 / FPS
for frame_idx in range(N_FRAMES):
    acc = compute_accelerations(pos, masses)
    vel += acc * dt
    pos += vel * dt
    # Clamp to safe bounds
    pos = np.clip(pos, -4.5, 4.5)
    scatter.set_offsets(pos)
    sizes = masses * 40
    scatter.set_sizes(sizes)
    fig.savefig(...)
```

## Double Pendulum

```python
from scipy.integrate import solve_ivp

def double_pendulum(t, state, L1=1.5, L2=1.5, m1=1, m2=1, g=9.8):
    th1, w1, th2, w2 = state
    c = np.cos(th1 - th2)
    s = np.sin(th1 - th2)
    dth1 = w1
    dth2 = w2
    dw1 = (m2*g*np.sin(th2)*c - m2*s*(L1*w1**2*c + L2*w2**2) - (m1+m2)*g*np.sin(th1)) \
          / (L1*(m1 + m2*s**2))
    dw2 = ((m1+m2)*(L1*w1**2*s - g*np.sin(th2) + g*np.sin(th1)*c) + m2*L2*w2**2*s*c) \
          / (L2*(m1 + m2*s**2))
    return [dth1, dw1, dth2, dw2]

# Pre-integrate full trajectory
t_span = (0, DURATION)
t_eval = np.linspace(0, DURATION, N_FRAMES)
sol = solve_ivp(double_pendulum, t_span, [np.pi/2, 0, np.pi/3, 0.5],
                t_eval=t_eval, max_step=0.01, method='RK45')

th1, th2 = sol.y[0], sol.y[2]
L1, L2 = 1.5, 1.5
x1 = L1 * np.sin(th1)
y1 = -L1 * np.cos(th1)
x2 = x1 + L2 * np.sin(th2)
y2 = y1 - L2 * np.cos(th2)

# Initialize artists
pivot = ax.plot(0, 2, 'o', color=DIM_GREY, ms=6)[0]
arm1, = ax.plot([0, x1[0]], [2, 2+y1[0]], '-', color=ELECTRIC, lw=3)
arm2, = ax.plot([x1[0], x2[0]], [2+y1[0], 2+y2[0]], '-', color=CORAL, lw=3)
bob1 = ax.plot(x1[0], 2+y1[0], 'o', color=ELECTRIC, ms=18)[0]
bob2 = ax.plot(x2[0], 2+y2[0], 'o', color=CORAL, ms=22)[0]
# Trace trail
trail_len = 60
trail, = ax.plot([], [], '-', color=CORAL, lw=1.5, alpha=0.4)

for frame_idx in range(N_FRAMES):
    ox, oy = 0, 2  # pivot position on screen
    arm1.set_data([ox, ox+x1[frame_idx]], [oy, oy+y1[frame_idx]])
    arm2.set_data([ox+x1[frame_idx], ox+x2[frame_idx]],
                  [oy+y1[frame_idx], oy+y2[frame_idx]])
    bob1.set_data([ox+x1[frame_idx]], [oy+y1[frame_idx]])
    bob2.set_data([ox+x2[frame_idx]], [oy+y2[frame_idx]])
    start = max(0, frame_idx - trail_len)
    trail.set_data(ox+x2[start:frame_idx+1], oy+y2[start:frame_idx+1])
    fig.savefig(...)
```

## Lorenz Attractor (3D Projection)

```python
from scipy.integrate import solve_ivp

def lorenz(t, state, sigma=10, rho=28, beta=8/3):
    x, y, z = state
    return [sigma*(y-x), x*(rho-z)-y, x*y-beta*z]

sol = solve_ivp(lorenz, [0, DURATION*3], [1.0, 1.0, 1.0],
                t_eval=np.linspace(0, DURATION*3, N_FRAMES),
                max_step=0.01, method='RK45')
xs, ys, zs = sol.y

# Project to 2D (x-z plane looks most dramatic)
proj_x = xs / 15  # scale to fit canvas
proj_y = (zs - 25) / 12

trail_len = 120
line, = ax.plot([], [], color=ELECTRIC, lw=1.5, alpha=0.8)
dot = ax.plot(proj_x[0], proj_y[0], 'o', color=GOLD, ms=8)[0]

for frame_idx in range(N_FRAMES):
    start = max(0, frame_idx - trail_len)
    line.set_data(proj_x[start:frame_idx+1], proj_y[start:frame_idx+1])
    dot.set_data([proj_x[frame_idx]], [proj_y[frame_idx]])
    fig.savefig(...)
```

## Wave Interference Pattern

```python
x = np.linspace(-4.5, 4.5, 300)
y = np.linspace(-8.0, 8.0, 533)
XX, YY = np.meshgrid(x, y)

# Two point sources
src1 = np.array([-1.5, 0])
src2 = np.array([1.5, 0])

img = ax.imshow(
    np.zeros((533, 300)),
    extent=[-4.5, 4.5, -8, 8],
    origin='lower',
    cmap='RdBu_r',
    vmin=-2, vmax=2,
    aspect='auto',
    interpolation='bilinear',
)

for frame_idx in range(N_FRAMES):
    t_sec = frame_idx / FPS
    r1 = np.sqrt((XX - src1[0])**2 + (YY - src1[1])**2) + 0.01
    r2 = np.sqrt((XX - src2[0])**2 + (YY - src2[1])**2) + 0.01
    wave = np.sin(5 * r1 - 8 * t_sec) / r1 + np.sin(5 * r2 - 8 * t_sec) / r2
    img.set_data(wave)
    fig.savefig(...)
```

## Vector Field / Streamplot

```python
x = np.linspace(-4, 4, 25)
y = np.linspace(-7, 7, 44)
XX, YY = np.meshgrid(x, y)

# Static streamplot — initialize once
def make_field(t_phase):
    U = -YY + np.sin(t_phase) * XX
    V = XX + np.cos(t_phase) * YY
    return U, V

# Note: ax.streamplot cannot be updated in-place — must clear and redraw
# For animated vector fields in matplotlib, use quiver:
U0, V0 = make_field(0)
spd = np.sqrt(U0**2 + V0**2)
quiv = ax.quiver(XX, YY, U0/spd, V0/spd,
                 spd, cmap='plasma', scale=30,
                 width=0.003, alpha=0.8)

for frame_idx in range(N_FRAMES):
    t_sec = frame_idx / FPS
    U, V = make_field(t_sec * 0.5)
    spd = np.sqrt(U**2 + V**2)
    quiv.set_UVC(U/spd, V/spd, spd)
    fig.savefig(...)
```

## Cellular Automaton (Conway's Game of Life)

```python
GRID_W, GRID_H = 54, 96  # ~1080/20, ~1920/20

grid = np.random.choice([0, 1], size=(GRID_H, GRID_W), p=[0.65, 0.35])

img = ax.imshow(grid, cmap='viridis', vmin=0, vmax=1,
                extent=[-4.5, 4.5, -8, 8], origin='lower', aspect='auto',
                interpolation='nearest')

def gol_step(g):
    neighbors = sum(np.roll(np.roll(g, i, 0), j, 1)
                    for i in (-1,0,1) for j in (-1,0,1)
                    if (i,j) != (0,0))
    return ((neighbors == 3) | ((g == 1) & (neighbors == 2))).astype(int)

for frame_idx in range(N_FRAMES):
    grid = gol_step(grid)
    img.set_data(grid)
    fig.savefig(...)
```
