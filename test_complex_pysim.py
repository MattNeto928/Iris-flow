#!/usr/bin/env python3
"""
Complex matplotlib animation test - Particle physics simulation
Demonstrates that matplotlib can create sophisticated scientific visualizations.

Usage: python test_complex_pysim.py
"""
import os
import sys
import subprocess
import tempfile
import shutil

# Complex simulation script - N-body gravitational simulation with trails
COMPLEX_SIMULATION = '''
import sys
import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Circle
from matplotlib.collections import LineCollection

def main(output_dir):
    os.makedirs(output_dir, exist_ok=True)
    
    TOTAL_FRAMES = 180  # 6 seconds at 30fps
    np.random.seed(42)
    
    # Initialize N-body system (gravitational simulation)
    num_bodies = 5
    G = 1.0  # Gravitational constant
    
    # Initial positions in a circular arrangement
    angles = np.linspace(0, 2*np.pi, num_bodies, endpoint=False)
    positions = np.column_stack([3*np.cos(angles), 3*np.sin(angles)])
    
    # Initial velocities - circular orbit velocities + perturbation
    velocities = np.column_stack([-np.sin(angles), np.cos(angles)]) * 0.5
    velocities += np.random.randn(num_bodies, 2) * 0.1
    
    masses = np.random.uniform(0.5, 2.0, num_bodies)
    colors = plt.cm.plasma(np.linspace(0.2, 0.8, num_bodies))
    
    # Store trails
    trail_length = 50
    trails = [[] for _ in range(num_bodies)]
    
    fig, ax = plt.subplots(figsize=(10, 10))
    fig.patch.set_facecolor('#0a0a1a')
    
    dt = 0.02
    
    for frame_num in range(TOTAL_FRAMES):
        ax.clear()
        ax.set_facecolor('#0a0a1a')
        
        # Physics: compute gravitational forces
        forces = np.zeros_like(positions)
        for i in range(num_bodies):
            for j in range(num_bodies):
                if i != j:
                    r = positions[j] - positions[i]
                    dist = np.linalg.norm(r) + 0.1  # Softening
                    force_mag = G * masses[i] * masses[j] / (dist**2)
                    forces[i] += force_mag * r / dist
        
        # Update velocities and positions
        velocities += forces / masses[:, np.newaxis] * dt
        positions += velocities * dt
        
        # Update trails
        for i in range(num_bodies):
            trails[i].append(positions[i].copy())
            if len(trails[i]) > trail_length:
                trails[i].pop(0)
        
        # Draw trails with gradient
        for i in range(num_bodies):
            if len(trails[i]) > 1:
                points = np.array(trails[i])
                segments = np.stack([points[:-1], points[1:]], axis=1)
                alphas = np.linspace(0.0, 0.8, len(segments))
                for j, seg in enumerate(segments):
                    ax.plot(seg[:, 0], seg[:, 1], 
                           color=colors[i], alpha=alphas[j], linewidth=1.5)
        
        # Draw bodies as glowing circles
        for i in range(num_bodies):
            # Outer glow
            for r_mult in [3, 2, 1.5]:
                circle = Circle(positions[i], masses[i] * 0.15 * r_mult, 
                              color=colors[i], alpha=0.1)
                ax.add_patch(circle)
            # Core
            circle = Circle(positions[i], masses[i] * 0.15, 
                          color=colors[i], alpha=0.9)
            ax.add_patch(circle)
        
        ax.set_xlim(-8, 8)
        ax.set_ylim(-8, 8)
        ax.set_aspect('equal')
        ax.axis('off')
        
        # Title
        ax.text(0.5, 0.95, 'N-Body Gravitational Simulation', 
               transform=ax.transAxes, ha='center', 
               fontsize=16, color='white', fontweight='bold')
        ax.text(0.5, 0.02, f'Frame {frame_num + 1}/{TOTAL_FRAMES}', 
               transform=ax.transAxes, ha='center', 
               fontsize=10, color='#666666')
        
        plt.savefig(os.path.join(output_dir, f"frame_{frame_num:05d}.png"), 
                   dpi=100, facecolor=fig.get_facecolor(), 
                   bbox_inches='tight', pad_inches=0.1)
    
    plt.close()
    print(f"Generated {TOTAL_FRAMES} frames")

if __name__ == "__main__":
    main(sys.argv[1])
'''


def run_complex_simulation():
    """Run the complex N-body simulation."""
    print("=" * 60)
    print("COMPLEX TEST: N-Body Gravitational Simulation")
    print("=" * 60)
    print("Features: 5 particles with gravity, trails, glow effects")
    print("Duration: 6 seconds (180 frames at 30fps)")
    print()
    
    with tempfile.TemporaryDirectory() as temp_dir:
        script_path = os.path.join(temp_dir, "nbody_sim.py")
        frames_dir = os.path.join(temp_dir, "frames")
        
        with open(script_path, "w") as f:
            f.write(COMPLEX_SIMULATION)
        
        print("Generating frames...")
        
        try:
            result = subprocess.run(
                ["python", script_path, frames_dir],
                capture_output=True,
                text=True,
                timeout=120  # 2 minute timeout
            )
            
            if result.returncode != 0:
                print(f"❌ Script failed!")
                print(f"stderr: {result.stderr}")
                return
            
            print(f"✓ {result.stdout.strip()}")
            
            # Compile to video
            if os.path.exists(frames_dir):
                frames = [f for f in os.listdir(frames_dir) if f.endswith('.png')]
                print(f"✓ Found {len(frames)} frame files")
                
                output_video = "./test_complex_pysim.mp4"
                print(f"\nCompiling video...")
                
                ffmpeg_result = subprocess.run([
                    "ffmpeg", "-y",
                    "-framerate", "30",
                    "-i", os.path.join(frames_dir, "frame_%05d.png"),
                    "-c:v", "libx264",
                    "-pix_fmt", "yuv420p",
                    "-crf", "18",  # Higher quality
                    "-preset", "slow",
                    output_video
                ], capture_output=True, text=True)
                
                if ffmpeg_result.returncode == 0:
                    size = os.path.getsize(output_video) / 1024
                    print(f"\n✅ SUCCESS!")
                    print(f"   Output: {output_video}")
                    print(f"   Size: {size:.1f} KB")
                    print(f"\n   Open it with: open {output_video}")
                else:
                    print(f"❌ FFmpeg failed: {ffmpeg_result.stderr}")
            else:
                print("❌ No frames directory!")
                
        except subprocess.TimeoutExpired:
            print("❌ Simulation timed out!")
        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    run_complex_simulation()
