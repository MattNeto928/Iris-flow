"""
SimPy Service - Discrete event simulation visualization.

Uses Claude to generate SimPy simulation scripts that output
Gantt charts, timeline visualizations, and queue length plots.
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


SIMPY_PROMPT = """# SimPy Segment Generation

SimPy segments visualize discrete event systems (queues, processes, workflows). The pattern is **always two-phase**: first run the full simulation capturing state snapshots, then render as matplotlib frames.

## Mandatory Two-Phase Pattern

```python
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import simpy
import os
from collections import deque

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
})

# ══════════════════════════════════════════════════════════════
# PHASE 1: Run simulation, capture snapshots
# ══════════════════════════════════════════════════════════════

SIM_DURATION = 60.0  # simulation time units
snapshots = []       # list of state dicts, one per time unit

# ... define processes + run simulation ...

env = simpy.Environment()
env.process(simulation_process(env, snapshots))
env.run(until=SIM_DURATION)

# ══════════════════════════════════════════════════════════════
# PHASE 2: Render frames from snapshots
# ══════════════════════════════════════════════════════════════

for frame_idx in range(N_FRAMES):
    # Map frame index to simulation snapshot
    snap_idx = int((frame_idx / N_FRAMES) * len(snapshots))
    snap_idx = min(snap_idx, len(snapshots) - 1)
    snap = snapshots[snap_idx]

    # Draw from snapshot
    # ...

    fig.savefig(os.path.join(OUTPUT_DIR, f'frame_{frame_idx:04d}.png'),
                dpi=120, bbox_inches='tight', pad_inches=0.1,
                facecolor='#0D0D0D')
```

## M/M/1 Queue Simulation

```python
import simpy
import random

def mm1_simulation(arrival_rate=0.8, service_rate=1.0, sim_time=100):
    \"\"\"Returns list of (time, queue_length, server_busy, wait_times) snapshots.\"\"\"
    env = simpy.Environment()
    server = simpy.Resource(env, capacity=1)
    snapshots = []
    wait_times = []

    def customer(env, name, server):
        arrival = env.now
        with server.request() as req:
            yield req
            wait = env.now - arrival
            wait_times.append(wait)
            service_time = random.expovariate(service_rate)
            yield env.timeout(service_time)

    def arrivals(env, server):
        i = 0
        while True:
            yield env.timeout(random.expovariate(arrival_rate))
            env.process(customer(env, i, server))
            i += 1

    def monitor(env, server, snapshots, interval=0.5):
        while True:
            snapshots.append({
                'time': env.now,
                'queue_len': len(server.queue),
                'utilization': server.count / server.capacity,
                'avg_wait': np.mean(wait_times) if wait_times else 0,
            })
            yield env.timeout(interval)

    env.process(arrivals(env, server))
    env.process(monitor(env, server, snapshots))
    env.run(until=sim_time)
    return snapshots

snapshots = mm1_simulation(arrival_rate=0.75, service_rate=1.0, sim_time=100)
```

## Queue Length Time Series Visualization

```python
times   = [s['time'] for s in snapshots]
q_lens  = [s['queue_len'] for s in snapshots]
util    = [s['utilization'] for s in snapshots]

fig, (ax_q, ax_u) = plt.subplots(2, 1, figsize=(9, 16), dpi=120,
                                   gridspec_kw={'height_ratios': [2, 1]})
for a in [ax_q, ax_u]:
    a.set_facecolor('#0D0D0D')

# Fixed limits based on full data
ax_q.set_xlim(0, max(times))
ax_q.set_ylim(0, max(q_lens) * 1.2 + 1)
ax_u.set_xlim(0, max(times))
ax_u.set_ylim(0, 1.2)

# Initialize artists — line draws in from left
q_line, = ax_q.plot([], [], color='#4FC3F7', lw=2)
u_line, = ax_u.plot([], [], color='#FFD54F', lw=2)
u_fill = None

ax_q.set_ylabel("Queue Length", color='#909090', fontsize=14)
ax_u.set_ylabel("Server Utilization", color='#909090', fontsize=14)
ax_u.set_xlabel("Time", color='#909090', fontsize=14)

# Add ρ = λ/μ theoretical line
rho = 0.75
ax_u.axhline(rho, color='#FF7043', lw=1.5, linestyle='--', alpha=0.7)
ax_u.text(max(times)*0.02, rho+0.03, f"ρ = {rho}", color='#FF7043', fontsize=12)

for frame_idx in range(N_FRAMES):
    snap_idx = max(1, int((frame_idx / N_FRAMES) * len(snapshots)))
    t_show = times[:snap_idx]
    q_show = q_lens[:snap_idx]
    u_show = util[:snap_idx]

    q_line.set_data(t_show, q_show)
    u_line.set_data(t_show, u_show)

    # Remove old fill, add new (fill_between can't update in-place)
    for coll in ax_u.collections:
        coll.remove()
    if len(t_show) > 1:
        ax_u.fill_between(t_show, u_show, alpha=0.2, color='#FFD54F')

    fig.savefig(os.path.join(OUTPUT_DIR, f'frame_{frame_idx:04d}.png'),
                dpi=120, bbox_inches='tight', pad_inches=0.1,
                facecolor='#0D0D0D')
```

## Animated Queue Diagram (Customers as Circles)

```python
# Visual queue: circles representing customers
MAX_VISIBLE = 12

def draw_queue_diagram(ax, queue_len, server_busy, time, avg_wait):
    ax.clear()
    ax.set_facecolor('#0D0D0D')
    ax.set_xlim(-1, 14)
    ax.set_ylim(-3, 4)
    ax.axis('off')

    # Server box
    server_color = '#FF7043' if server_busy else '#2A2A2A'
    ax.add_patch(patches.FancyBboxPatch((11, -0.7), 1.8, 1.4,
                  boxstyle="round,pad=0.1", facecolor=server_color,
                  edgecolor='#555555', lw=1.5))
    ax.text(11.9, 0, "Server", ha='center', va='center',
            fontsize=11, color='#F5F5F5', fontfamily='Roboto')

    # Queue line
    n_shown = min(queue_len, MAX_VISIBLE)
    for i in range(n_shown):
        x = 9.5 - i * 0.85
        circle = plt.Circle((x, 0), 0.35, color='#4FC3F7', alpha=0.85)
        ax.add_patch(circle)

    if queue_len > MAX_VISIBLE:
        ax.text(0.5, 0, f"+{queue_len-MAX_VISIBLE} more",
                ha='center', va='center', fontsize=12, color='#909090')

    # Arrow from queue to server
    ax.annotate('', xy=(11, 0), xytext=(10.3, 0),
                arrowprops=dict(arrowstyle='->', color='#555555', lw=1.5))

    # Stats
    ax.text(6.5, 2.5, f"Queue: {queue_len}  |  t = {time:.1f}  |  avg wait = {avg_wait:.2f}",
            ha='center', fontsize=14, color='#909090', fontfamily='Roboto')

fig, ax = plt.subplots(figsize=(9, 16), dpi=120)
fig.patch.set_facecolor('#0D0D0D')

for frame_idx in range(N_FRAMES):
    snap = snapshots[min(int(frame_idx/N_FRAMES*len(snapshots)), len(snapshots)-1)]
    draw_queue_diagram(ax, snap['queue_len'], snap['utilization'] > 0,
                       snap['time'], snap['avg_wait'])
    fig.savefig(...)
```

## Gantt Chart (Process Timeline)

```python
# Track job start/end times for Gantt
job_log = []  # list of {'job_id': int, 'start': float, 'end': float, 'wait': float}

# After simulation, draw Gantt chart building over time
MAX_JOBS_SHOWN = 20

fig, ax = plt.subplots(figsize=(9, 16), dpi=120)
fig.patch.set_facecolor('#0D0D0D')
ax.set_facecolor('#0D0D0D')

for frame_idx in range(N_FRAMES):
    n_jobs = max(1, int((frame_idx / N_FRAMES) * len(job_log)))
    visible = job_log[-MAX_JOBS_SHOWN:n_jobs]

    ax.clear()
    ax.set_facecolor('#0D0D0D')

    for i, job in enumerate(visible):
        y = i
        wait_bar = ax.barh(y, job['wait'], left=job['start'],
                           color='#FF7043', alpha=0.5, height=0.6)
        service_bar = ax.barh(y, job['end']-job['start']-job['wait'],
                              left=job['start']+job['wait'],
                              color='#4FC3F7', alpha=0.8, height=0.6)

    ax.set_xlabel("Simulation Time", color='#909090')
    ax.set_ylabel("Job", color='#909090')

    # Legend
    ax.barh(-2, 0, color='#FF7043', alpha=0.5, label='Wait time')
    ax.barh(-2, 0, color='#4FC3F7', alpha=0.8, label='Service time')
    ax.legend(loc='upper left', facecolor='#1A1A1A', labelcolor='#F5F5F5')

    fig.savefig(...)
```

CRITICAL DYNAMIC REQUIREMENTS:
- Target Duration: {duration} seconds
- Exact frames required: {frames}
- Description: {description}

GENERATE ONLY PYTHON CODE. Be concise — use loops, helper functions, and avoid repeating similar code blocks. No markdown, no explanation:
"""


class SimpyService:
    def __init__(self):
        FRAMES_DIR.mkdir(parents=True, exist_ok=True)
        VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    
    async def generate(self, description: str, duration: float, previous_error: str = None) -> str:
        """
        Generate a SimPy visualization video from description.
        
        1. Generate SimPy script with Claude
        2. Run script to generate frames
        3. Compile frames to video
        
        Returns path to generated video.
        """
        video_id = str(uuid.uuid4())[:8]
        fps = 30
        frames = int(duration * fps)
        
        logger.info(f"[SimPy] Generating {frames} frames for {duration}s video")
        if previous_error:
            logger.info(f"[SimPy] Retrying with error context: {previous_error}")
        
        # Step 1: Generate script
        script = await self._generate_script(description, duration, frames, previous_error)
        logger.info(f"[SimPy] Script generated ({len(script)} chars)")
        
        # Step 2: Run simulation
        frames_path = FRAMES_DIR / f"simpy_{video_id}"
        frames_path.mkdir(exist_ok=True)
        
        await self._run_simulation(script, str(frames_path))
        
        # Step 3: Compile to video
        video_path = VIDEOS_DIR / f"simpy_{video_id}.mp4"
        await self._compile_video(str(frames_path), str(video_path), fps)
        
        return str(video_path)
    
    async def _generate_script(self, description: str, duration: float, frames: int, previous_error: str = None) -> str:
        """Generate simulation script using Claude."""
        
        error_context = ""
        if previous_error:
            error_context = f"""
*** PREVIOUS ATTEMPT FAILED WITH ERROR: ***
{previous_error}
*** YOU MUST FIX THIS ERROR IN THE NEW SCRIPT ***
"""
        
        final_prompt = SIMPY_PROMPT.replace("{description}", description).replace("{duration}", str(duration)).replace("{frames}", str(frames)) + error_context
        
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
        
        logger.info(f"[SimPy] Running simulation...")
        
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
            raise RuntimeError(f"SimPy simulation failed: {error_msg}")
        
        logger.info(f"[SimPy] Simulation complete")
    
    async def _compile_video(self, frames_dir: str, output_path: str, fps: int = 30):
        """Compile frames to video using FFmpeg."""
        from pathlib import Path
        frames_path = Path(frames_dir)
        frame_files = sorted(frames_path.glob("frame_*.png"))
        
        if not frame_files:
            raise RuntimeError(f"No frames found in {frames_dir}")
        
        logger.info(f"[SimPy] Compiling {len(frame_files)} frames to video")
        
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
            logger.error(f"[SimPy] FFmpeg failed: {stderr_text}")
            raise RuntimeError(f"FFmpeg compilation failed: {stderr_text}")
        
        logger.info(f"[SimPy] Video compiled: {output_path}")
