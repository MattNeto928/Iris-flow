"""
Stats Service - Statistical visualization using seaborn and statsmodels.

Uses Claude to generate statistical visualizations including distributions,
regression, Monte Carlo simulations, and probability demonstrations.
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


STATS_PROMPT = """# Stats Segment Generation

Stats segments animate probability and statistics concepts. Claude generates a complete Python script producing `N = int(duration * 30)` frames at 1080×1920 using matplotlib Agg + scipy.

## Mandatory Structure

```python
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import numpy as np
from scipy import stats
import os

OUTPUT_DIR = os.environ.get('OUTPUT_DIR', '/tmp/frames')
os.makedirs(OUTPUT_DIR, exist_ok=True)
DURATION = float(os.environ.get('DURATION', '8'))
FPS = 30
N_FRAMES = int(DURATION * FPS)

plt.rcParams.update({
    'font.family': 'sans-serif',
    'font.sans-serif': ['Roboto', 'Helvetica Neue', 'DejaVu Sans'],
    'axes.facecolor': '#0D0D0D',
    'figure.facecolor': '#0D0D0D',
    'text.color': '#F5F5F5',
    'axes.edgecolor': '#2A2A2A',
    'xtick.color': '#606060',
    'ytick.color': '#606060',
})

def ease_in_out_cubic(t):
    if t < 0.5: return 4 * t**3
    return 1 - (-2*t + 2)**3 / 2
```

## Distribution Animation — Morphing PDF

Animate distribution parameters changing smoothly:

```python
x = np.linspace(-5, 5, 500)

fig, ax = plt.subplots(figsize=(9, 16), dpi=120)
fig.patch.set_facecolor('#0D0D0D')
ax.set_facecolor('#0D0D0D')
ax.set_xlim(-5, 5)
ax.set_ylim(0, 1.0)
for spine in ['top', 'right']:
    ax.spines[spine].set_visible(False)
ax.spines[['left', 'bottom']].set_color('#2A2A2A')

# Start: wide distribution (σ=2), end: narrow (σ=0.5)
line_pdf, = ax.plot(x, np.zeros_like(x), color='#4FC3F7', lw=2.5)
fill = ax.fill_between(x, np.zeros_like(x), alpha=0.15, color='#4FC3F7')

mu_start, mu_end = 0.0, 1.0
sigma_start, sigma_end = 2.0, 0.5

title = ax.text(0, 0.95, "Normal Distribution", ha='center', va='top',
                fontsize=24, color='#F5F5F5', transform=ax.transAxes)
param_text = ax.text(0.05, 0.85, "", ha='left', va='top',
                      fontsize=16, color='#909090', transform=ax.transAxes)

for frame_idx in range(N_FRAMES):
    t = frame_idx / max(N_FRAMES - 1, 1)
    t_e = ease_in_out_cubic(t)

    mu = mu_start + (mu_end - mu_start) * t_e
    sigma = sigma_start + (sigma_end - sigma_start) * t_e

    y = stats.norm.pdf(x, mu, sigma)
    line_pdf.set_ydata(y)

    # Update fill — must recreate (limitation of fill_between)
    for coll in ax.collections:
        coll.remove()
    ax.fill_between(x, y, alpha=0.15, color='#4FC3F7')

    param_text.set_text(f"μ = {mu:.2f},  σ = {sigma:.2f}")
    ax.set_ylim(0, max(y.max() * 1.3, 0.1))

    fig.savefig(os.path.join(OUTPUT_DIR, f'frame_{frame_idx:04d}.png'),
                dpi=120, bbox_inches='tight', pad_inches=0.1,
                facecolor='#0D0D0D')
```

## Central Limit Theorem

```python
# Show sample means converging to normal distribution
from collections import deque

POP_SIZE = 100000
population = np.random.exponential(scale=2, size=POP_SIZE)  # skewed population
SAMPLE_SIZE = 30
N_SAMPLES_TOTAL = 500  # draw this many samples total across animation

fig, (ax_pop, ax_means) = plt.subplots(2, 1, figsize=(9, 16), dpi=120,
                                         gridspec_kw={'height_ratios': [1, 2]})
# ... setup axes ...

sample_means = []
# Pre-compute all samples
all_means = [np.mean(np.random.choice(population, SAMPLE_SIZE))
             for _ in range(N_SAMPLES_TOTAL)]

# Histogram bins fixed
bins = np.linspace(min(all_means)*0.9, max(all_means)*1.1, 40)

for frame_idx in range(N_FRAMES):
    n_shown = int((frame_idx / N_FRAMES) * N_SAMPLES_TOTAL)
    current_means = all_means[:n_shown]

    ax_means.clear()
    if len(current_means) > 2:
        ax_means.hist(current_means, bins=bins, color='#4FC3F7',
                      alpha=0.75, edgecolor='none', density=True)
        # Overlay normal curve
        mu_hat = np.mean(current_means)
        sigma_hat = np.std(current_means)
        x_norm = np.linspace(bins[0], bins[-1], 200)
        ax_means.plot(x_norm, stats.norm.pdf(x_norm, mu_hat, sigma_hat),
                      color='#FFD54F', lw=2, alpha=0.9)

    ax_means.text(0.5, 0.95, f"n = {n_shown} samples",
                  transform=ax_means.transAxes, ha='center', va='top',
                  fontsize=16, color='#F5F5F5')
    fig.savefig(...)
```

## Bayesian Updating

```python
# Prior → Likelihood → Posterior animation
x = np.linspace(0, 1, 500)  # probability of heads

# Beta distribution: conjugate prior for binomial
alpha0, beta0 = 2.0, 2.0  # prior (slightly informative)

# Simulate coin flips
np.random.seed(42)
flips = np.random.binomial(1, 0.7, size=50)  # true p=0.7, biased coin

fig, ax = plt.subplots(figsize=(9, 16), dpi=120)
# ...

line_prior,    = ax.plot(x, np.zeros_like(x), color='#CE93D8', lw=2, label='Prior')
line_posterior, = ax.plot(x, np.zeros_like(x), color='#4FC3F7', lw=2.5, label='Posterior')

for frame_idx in range(N_FRAMES):
    n_flips = int((frame_idx / N_FRAMES) * len(flips))
    heads = flips[:n_flips].sum()
    tails = n_flips - heads

    alpha_post = alpha0 + heads
    beta_post  = beta0  + tails

    prior_pdf = stats.beta.pdf(x, alpha0, beta0)
    post_pdf  = stats.beta.pdf(x, alpha_post, beta_post)

    line_prior.set_ydata(prior_pdf)
    line_posterior.set_ydata(post_pdf)
    ax.set_ylim(0, max(post_pdf.max(), prior_pdf.max()) * 1.3)

    ax.set_title(f"After {n_flips} flips: {heads}H {tails}T\n"
                 f"P(heads) ~ Beta({alpha_post:.0f}, {beta_post:.0f})",
                 fontsize=18, color='#F5F5F5')
    fig.savefig(...)
```

## Hypothesis Testing — p-value Visualization

```python
# Animate shading the rejection region as test statistic moves
x = np.linspace(-5, 5, 500)
ALPHA = 0.05
z_critical = stats.norm.ppf(1 - ALPHA/2)  # two-tailed

fig, ax = plt.subplots(figsize=(9, 16), dpi=120)
null_dist = stats.norm.pdf(x, 0, 1)
ax.plot(x, null_dist, color='#F5F5F5', lw=2, label='H₀ distribution')

# Shade rejection regions (static)
ax.fill_between(x, null_dist, where=(x > z_critical), color='#FF7043', alpha=0.4)
ax.fill_between(x, null_dist, where=(x < -z_critical), color='#FF7043', alpha=0.4)

# Animate observed test statistic moving from center to edge
z_obs_start, z_obs_end = 0.0, 2.3
obs_line = ax.axvline(z_obs_start, color='#FFD54F', lw=2.5)
pval_text = ax.text(0.5, 0.8, "", ha='center', transform=ax.transAxes,
                    fontsize=18, color='#FFD54F')

for frame_idx in range(N_FRAMES):
    t_e = ease_in_out_cubic(frame_idx / max(N_FRAMES-1, 1))
    z_obs = z_obs_start + (z_obs_end - z_obs_start) * t_e
    obs_line.set_xdata([z_obs, z_obs])
    p_val = 2 * (1 - stats.norm.cdf(abs(z_obs)))
    pval_text.set_text(f"p-value = {p_val:.3f}")
    fig.savefig(...)
```

## Monte Carlo Pi Estimation

```python
fig, ax = plt.subplots(figsize=(9, 16), dpi=120)
ax.set_xlim(-1.1, 1.1)
ax.set_ylim(-1.1, 1.1)
ax.set_aspect('equal')

# Draw unit circle
theta = np.linspace(0, 2*np.pi, 200)
ax.plot(np.cos(theta), np.sin(theta), color='#4FC3F7', lw=2, alpha=0.6)
ax.add_patch(patches.Rectangle((-1,-1), 2, 2, fill=False,
                                 edgecolor='#2A2A2A', lw=1))

N_POINTS_TOTAL = 2000
pts = np.random.uniform(-1, 1, (N_POINTS_TOTAL, 2))
inside = (pts[:,0]**2 + pts[:,1]**2) <= 1

scatter_in  = ax.scatter([], [], s=4, color='#4FC3F7', alpha=0.7)
scatter_out = ax.scatter([], [], s=4, color='#FF7043', alpha=0.7)
pi_text = ax.text(0, 1.05, "π ≈ ...", ha='center', fontsize=28,
                  color='#FFD54F', fontfamily='Roboto')

for frame_idx in range(N_FRAMES):
    n = int((frame_idx / N_FRAMES) * N_POINTS_TOTAL) + 1
    pi_est = 4 * inside[:n].sum() / n
    scatter_in.set_offsets(pts[:n][inside[:n]])
    scatter_out.set_offsets(pts[:n][~inside[:n]])
    pi_text.set_text(f"π ≈ {pi_est:.4f}  (n={n})")
    fig.savefig(...)
```

CRITICAL DYNAMIC REQUIREMENTS:
- Target Duration: {duration} seconds
- Exact frames required: {frames}
- Description: {description}

GENERATE ONLY PYTHON CODE. Be concise — use loops, helper functions, and avoid repeating similar code blocks. No markdown, no explanation:
"""


class StatsService:
    def __init__(self):
        FRAMES_DIR.mkdir(parents=True, exist_ok=True)
        VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    
    async def generate(self, description: str, duration: float, previous_error: str = None) -> str:
        """
        Generate a statistical visualization video from description.
        
        1. Generate stats script with Claude
        2. Run script to generate frames
        3. Compile frames to video
        
        Returns path to generated video.
        """
        video_id = str(uuid.uuid4())[:8]
        fps = 30
        frames = int(duration * fps)
        
        logger.info(f"[Stats] Generating {frames} frames for {duration}s video")
        if previous_error:
            logger.info(f"[Stats] Retrying with error context: {previous_error}")
        
        # Step 1: Generate script
        script = await self._generate_script(description, duration, frames, previous_error)
        logger.info(f"[Stats] Script generated ({len(script)} chars)")
        
        # Step 2: Run visualization
        frames_path = FRAMES_DIR / f"stats_{video_id}"
        frames_path.mkdir(exist_ok=True)
        
        await self._run_visualization(script, str(frames_path))
        
        # Step 3: Compile to video
        video_path = VIDEOS_DIR / f"stats_{video_id}.mp4"
        await self._compile_video(str(frames_path), str(video_path), fps)
        
        return str(video_path)
    
    async def _generate_script(self, description: str, duration: float, frames: int, previous_error: str = None) -> str:
        """Generate stats script using Claude."""
        
        error_context = ""
        if previous_error:
            error_context = f"""
*** PREVIOUS ATTEMPT FAILED WITH ERROR: ***
{previous_error}
*** YOU MUST FIX THIS ERROR IN THE NEW SCRIPT ***
"""
        
        final_prompt = STATS_PROMPT.replace("{description}", description).replace("{duration}", str(duration)).replace("{frames}", str(frames)) + error_context
        
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
        """Run the stats visualization script."""
        script_path = Path(output_dir) / "visualization.py"
        
        with open(script_path, "w") as f:
            f.write(script)
        
        logger.info(f"[Stats] Running visualization...")
        
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
            raise RuntimeError(f"Stats visualization failed: {error_msg}")
        
        logger.info(f"[Stats] Visualization complete")
    
    async def _compile_video(self, frames_dir: str, output_path: str, fps: int = 30):
        """Compile frames to video using FFmpeg."""
        from pathlib import Path
        frames_path = Path(frames_dir)
        frame_files = sorted(frames_path.glob("frame_*.png"))
        
        if not frame_files:
            raise RuntimeError(f"No frames found in {frames_dir}")
        
        logger.info(f"[Stats] Compiling {len(frame_files)} frames to video")
        
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
            logger.error(f"[Stats] FFmpeg failed: {stderr_text}")
            raise RuntimeError(f"FFmpeg compilation failed: {stderr_text}")
        
        logger.info(f"[Stats] Video compiled: {output_path}")
