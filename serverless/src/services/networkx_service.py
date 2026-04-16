"""
NetworkX Service - Graph algorithm visualization.

Uses Claude to generate NetworkX scripts that visualize graph algorithms
like shortest path, BFS/DFS, PageRank, and community detection.
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


NETWORKX_PROMPT = """# NetworkX Segment Generation

NetworkX segments visualize graph algorithms and data structures as step-by-step animations. Claude generates a complete Python script producing `N = int(duration * 30)` PNG frames at 1080×1920 using networkx + matplotlib Agg.

## Mandatory Structure

```python
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import networkx as nx
import numpy as np
import os

OUTPUT_DIR = os.environ.get('OUTPUT_DIR', '/tmp/frames')
os.makedirs(OUTPUT_DIR, exist_ok=True)
DURATION = float(os.environ.get('DURATION', '8'))
FPS = 30
N_FRAMES = int(DURATION * FPS)

plt.rcParams.update({
    'font.family': 'sans-serif',
    'font.sans-serif': ['Roboto', 'Helvetica Neue', 'DejaVu Sans'],
})

fig, ax = plt.subplots(figsize=(9, 16), dpi=120)
fig.patch.set_facecolor('#0D0D0D')
ax.set_facecolor('#0D0D0D')
ax.set_xlim(-1, 1)
ax.set_ylim(-1, 1)
ax.set_aspect('equal')
ax.axis('off')
```

## Graph Layout — Positioning for 9:16

The most critical step: layout must fit within the vertical canvas and keep nodes separated.

```python
# Always seed for reproducibility
G = nx.karate_club_graph()  # or your custom graph

# Kamada-Kawai: best quality, slowest — use for < 50 nodes
pos = nx.kamada_kawai_layout(G)

# Spring: fast, reasonable — use for 20–100 nodes
pos = nx.spring_layout(G, seed=42, k=2.5/np.sqrt(len(G)))
# k controls separation — larger k = more spread

# Circular: clean, use when topology matters less
pos = nx.circular_layout(G)

# Shell: concentric rings — great for BFS layers
shells = [[root], list(nx.bfs_layers(G, root))[1], ...]
pos = nx.shell_layout(G, nlist=shells)

# Scale pos to fit 9:16 canvas
# Default layouts return coords in [-1, 1]
# Scale: x → [-0.85, 0.85], y → [-0.85, 0.85]
# (ax.set_xlim(-1,1), ylim(-1,1) with 0.15 margin handles labels)
```

## Drawing — Always Separate Components

Never use `nx.draw()` — always draw nodes, edges, and labels separately for animation control:

```python
# Colors: maintain dicts for per-node/edge state
NODE_DEFAULT  = '#1E3A5F'  # dark blue — unvisited
NODE_FRONTIER = '#FF7043'  # coral — in queue/stack
NODE_VISITED  = '#4FC3F7'  # electric blue — visited
NODE_PATH     = '#FFD54F'  # gold — final path
EDGE_DEFAULT  = '#2A2A2A'  # nearly invisible
EDGE_ACTIVE   = '#80CBC4'  # mint — traversed edge

node_colors = {n: NODE_DEFAULT for n in G.nodes()}
edge_colors = {e: EDGE_DEFAULT for e in G.edges()}

def draw_frame(ax, G, pos, node_colors, edge_colors,
               node_sizes, labels=None, title=""):
    ax.clear()
    ax.set_facecolor('#0D0D0D')
    ax.set_xlim(-1.1, 1.1)
    ax.set_ylim(-1.1, 1.1)
    ax.axis('off')

    # Edges first (behind nodes)
    nx.draw_networkx_edges(
        G, pos, ax=ax,
        edge_color=[edge_colors.get(e, edge_colors.get((e[1],e[0]), EDGE_DEFAULT))
                    for e in G.edges()],
        width=2.5,
        alpha=0.8,
        arrows=True,  # set False for undirected
        arrowsize=15,
    )

    # Nodes
    nx.draw_networkx_nodes(
        G, pos, ax=ax,
        node_color=[node_colors[n] for n in G.nodes()],
        node_size=[node_sizes.get(n, 400) for n in G.nodes()],
        linewidths=1.5,
        edgecolors='#444444',
    )

    # Labels
    nx.draw_networkx_labels(
        G, pos, ax=ax,
        labels=labels or {n: str(n) for n in G.nodes()},
        font_color='#F5F5F5',
        font_size=11,
        font_family='Roboto',
    )

    # Title
    ax.text(0, 1.05, title, ha='center', va='bottom',
            fontsize=20, color='#F5F5F5', fontfamily='Roboto',
            transform=ax.transData)
```

## Algorithm Animation Pattern

Pre-compute all algorithm states, then interpolate frames:

```python
# Step 1: Run algorithm and record states
def bfs_states(G, start):
    \"\"\"Returns list of (node_colors, edge_colors, description) per step.\"\"\"
    states = []
    visited = set()
    queue = [start]
    node_col = {n: NODE_DEFAULT for n in G.nodes()}
    edge_col = {e: EDGE_DEFAULT for e in G.edges()}

    node_col[start] = NODE_FRONTIER
    states.append((dict(node_col), dict(edge_col), f"Start at node {start}"))

    while queue:
        current = queue.pop(0)
        node_col[current] = NODE_VISITED
        visited.add(current)

        for neighbor in G.neighbors(current):
            e = (current, neighbor)
            rev_e = (neighbor, current)
            if neighbor not in visited and neighbor not in queue:
                queue.append(neighbor)
                node_col[neighbor] = NODE_FRONTIER
                edge_col[e if e in G.edges() else rev_e] = EDGE_ACTIVE

        states.append((dict(node_col), dict(edge_col),
                       f"Visiting node {current}"))
    return states

states = bfs_states(G, start=0)

# Step 2: Distribute states across frames
# Each state holds for (N_FRAMES / len(states)) frames
frames_per_state = N_FRAMES / len(states)

for frame_idx in range(N_FRAMES):
    state_idx = min(int(frame_idx / frames_per_state), len(states) - 1)
    nc, ec, desc = states[state_idx]

    draw_frame(ax, G, pos, nc, ec,
               node_sizes={n: 500 for n in G.nodes()},
               title=desc)

    fig.savefig(
        os.path.join(OUTPUT_DIR, f'frame_{frame_idx:04d}.png'),
        dpi=120, bbox_inches='tight', pad_inches=0.1,
        facecolor='#0D0D0D',
    )
```

## Weighted Graph / Dijkstra

```python
def dijkstra_states(G, start):
    import heapq
    dist = {n: float('inf') for n in G.nodes()}
    dist[start] = 0
    prev = {}
    pq = [(0, start)]
    visited = set()
    states = []
    nc = {n: NODE_DEFAULT for n in G.nodes()}
    ec = {e: EDGE_DEFAULT for e in G.edges()}

    nc[start] = NODE_FRONTIER
    states.append((dict(nc), dict(ec), f"Start: dist[{start}]=0"))

    while pq:
        d, u = heapq.heappop(pq)
        if u in visited: continue
        visited.add(u)
        nc[u] = NODE_VISITED

        for v, data in G[u].items():
            w = data.get('weight', 1)
            if dist[u] + w < dist[v]:
                dist[v] = dist[u] + w
                prev[v] = u
                nc[v] = NODE_FRONTIER
                e = (u,v) if (u,v) in G.edges() else (v,u)
                ec[e] = EDGE_ACTIVE
                heapq.heappush(pq, (dist[v], v))

        states.append((dict(nc), dict(ec), f"Settled node {u}, dist={d:.1f}"))

    # Highlight shortest path
    # ...
    return states

# Draw edge weight labels
edge_labels = {(u,v): f"{d['weight']}" for u,v,d in G.edges(data=True)}
nx.draw_networkx_edge_labels(G, pos, edge_labels=edge_labels,
                             font_color='#909090', font_size=9, ax=ax)
```

## Node Sizing for Centrality Visualization

```python
centrality = nx.betweenness_centrality(G)
sizes = {n: 200 + 1500 * centrality[n] for n in G.nodes()}
colors = {n: plt.cm.plasma(centrality[n]) for n in G.nodes()}
# Then animate by revealing high-centrality nodes last (dramatic)
```

## Label Collision Prevention

For dense graphs, position labels offset from nodes:
```python
# Offset labels above nodes
label_pos = {n: (pos[n][0], pos[n][1] + 0.08) for n in G.nodes()}
nx.draw_networkx_labels(G, label_pos, ...)
```

For graphs with >20 nodes, omit labels or only label key nodes:
```python
important = [n for n in G.nodes() if G.degree(n) > 3]
labels = {n: str(n) for n in important}
nx.draw_networkx_labels(G, pos, labels=labels, ...)
```

## Color State Legend

```python
# Add legend to each frame
legend_elements = [
    mpatches.Patch(color=NODE_DEFAULT, label='Unvisited'),
    mpatches.Patch(color=NODE_FRONTIER, label='In Queue'),
    mpatches.Patch(color=NODE_VISITED, label='Visited'),
    mpatches.Patch(color=NODE_PATH, label='Shortest Path'),
]
ax.legend(handles=legend_elements, loc='lower center',
          bbox_to_anchor=(0, -0.05), ncol=2,
          facecolor='#1A1A1A', edgecolor='#333333',
          labelcolor='#F5F5F5', fontsize=11)
```

CRITICAL DYNAMIC REQUIREMENTS:
- Target Duration: {duration} seconds
- Exact frames required: {frames}
- Description: {description}

GENERATE ONLY PYTHON CODE. Be concise — use loops, helper functions, and avoid repeating similar code blocks. No markdown, no explanation:
"""


class NetworkxService:
    def __init__(self):
        FRAMES_DIR.mkdir(parents=True, exist_ok=True)
        VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    
    async def generate(self, description: str, duration: float, previous_error: str = None) -> str:
        """
        Generate a NetworkX visualization video from description.
        
        1. Generate NetworkX script with Claude
        2. Run script to generate frames
        3. Compile frames to video
        
        Returns path to generated video.
        """
        video_id = str(uuid.uuid4())[:8]
        fps = 30
        frames = int(duration * fps)
        
        logger.info(f"[NetworkX] Generating {frames} frames for {duration}s video")
        if previous_error:
            logger.info(f"[NetworkX] Retrying with error context: {previous_error}")
        
        # Step 1: Generate script
        script = await self._generate_script(description, duration, frames, previous_error)
        logger.info(f"[NetworkX] Script generated ({len(script)} chars)")
        
        # Step 2: Run visualization
        frames_path = FRAMES_DIR / f"networkx_{video_id}"
        frames_path.mkdir(exist_ok=True)
        
        await self._run_visualization(script, str(frames_path))
        
        # Step 3: Compile to video
        video_path = VIDEOS_DIR / f"networkx_{video_id}.mp4"
        await self._compile_video(str(frames_path), str(video_path), fps)
        
        return str(video_path)
    
    async def _generate_script(self, description: str, duration: float, frames: int, previous_error: str = None) -> str:
        """Generate NetworkX script using Claude."""
        
        error_context = ""
        if previous_error:
            error_context = f"""
*** PREVIOUS ATTEMPT FAILED WITH ERROR: ***
{previous_error}
*** YOU MUST FIX THIS ERROR IN THE NEW SCRIPT ***
"""
        
        final_prompt = NETWORKX_PROMPT.replace("{description}", description).replace("{duration}", str(duration)).replace("{frames}", str(frames)) + error_context
        
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
        """Run the NetworkX script."""
        script_path = Path(output_dir) / "visualization.py"
        
        with open(script_path, "w") as f:
            f.write(script)
        
        logger.info(f"[NetworkX] Running visualization...")
        
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
            raise RuntimeError(f"NetworkX visualization failed: {error_msg}")
        
        logger.info(f"[NetworkX] Visualization complete")
    
    async def _compile_video(self, frames_dir: str, output_path: str, fps: int = 30):
        """Compile frames to video using FFmpeg."""
        from pathlib import Path
        frames_path = Path(frames_dir)
        frame_files = sorted(frames_path.glob("frame_*.png"))
        
        if not frame_files:
            raise RuntimeError(f"No frames found in {frames_dir}")
        
        logger.info(f"[NetworkX] Compiling {len(frame_files)} frames to video")
        
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
            logger.error(f"[NetworkX] FFmpeg failed: {stderr_text}")
            raise RuntimeError(f"FFmpeg compilation failed: {stderr_text}")
        
        logger.info(f"[NetworkX] Video compiled: {output_path}")
