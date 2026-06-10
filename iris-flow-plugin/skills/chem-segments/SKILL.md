---
name: chem-segments
description: This skill should be used when generating chemistry visualization code for Iris-flow chem segments, including 2D molecular structure animations, 3D molecular rotation, reaction mechanism animations, electron orbital visualization, and chemical bond formation/breaking using RDKit and matplotlib.
version: 1.0.0
---

# Chem Segment Generation

Chemistry segments visualize molecular structures, reactions, and chemical concepts. Claude generates a complete Python script producing `N = int(duration * 30)` PNG frames at 1080×1920.

## Primary Approach: RDKit 2D + matplotlib 3D

Use **RDKit for 2D structures** and **matplotlib 3D** for molecular rotation. py3Dmol is not reliably headless.

## Mandatory Structure

```python
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from mpl_toolkits.mplot3d import Axes3D
from mpl_toolkits.mplot3d.art3d import Line3DCollection
import numpy as np
import os

# RDKit imports
try:
    from rdkit import Chem
    from rdkit.Chem import Draw, AllChem, rdMolDescriptors
    from rdkit.Chem.Draw import rdMolDraw2D
    HAS_RDKIT = True
except ImportError:
    HAS_RDKIT = False

OUTPUT_DIR = os.environ.get('OUTPUT_DIR', '/tmp/frames')
os.makedirs(OUTPUT_DIR, exist_ok=True)
DURATION = float(os.environ.get('DURATION', '8'))
FPS = 30
N_FRAMES = int(DURATION * FPS)

plt.rcParams.update({
    'font.family': 'sans-serif',
    'font.sans-serif': ['Roboto', 'Helvetica Neue', 'DejaVu Sans'],
})

def ease_in_out_cubic(t):
    if t < 0.5: return 4 * t**3
    return 1 - (-2*t + 2)**3 / 2
```

## RDKit — 2D Structure Rendering

### Draw Molecule to Numpy Array

```python
from rdkit import Chem
from rdkit.Chem.Draw import rdMolDraw2D
from PIL import Image
import io

def mol_to_rgba(smiles, width=800, height=600,
                bg_color=(13,13,13,255), bond_color=(180,180,180)):
    """Render SMILES to RGBA numpy array with dark background."""
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"Invalid SMILES: {smiles}")
    AllChem.Compute2DCoords(mol)

    drawer = rdMolDraw2D.MolDraw2DSVG(width, height)
    # Dark background
    drawer.drawOptions().backgroundColour = (bg_color[0]/255, bg_color[1]/255,
                                              bg_color[2]/255, 1.0)
    drawer.drawOptions().bondLineWidth = 2.0
    drawer.drawOptions().atomLabelFontSize = 0.4
    # Atom colors (approximate CPK on dark)
    drawer.drawOptions().updateAtomPalette({
        6:  (0.85, 0.85, 0.85),   # C — light grey
        7:  (0.40, 0.60, 1.00),   # N — blue
        8:  (1.00, 0.30, 0.30),   # O — red
        16: (1.00, 0.80, 0.20),   # S — yellow
        17: (0.20, 0.80, 0.30),   # Cl — green
        9:  (0.70, 0.90, 0.70),   # F — light green
        15: (1.00, 0.60, 0.20),   # P — orange
        1:  (0.70, 0.70, 0.70),   # H — grey
    })
    drawer.DrawMolecule(mol)
    drawer.FinishDrawing()

    svg = drawer.GetDrawingText()
    # Convert SVG → PIL → numpy
    import cairosvg  # pip install cairosvg
    png_bytes = cairosvg.svg2png(bytestring=svg.encode(),
                                  output_width=width, output_height=height)
    img = Image.open(io.BytesIO(png_bytes)).convert('RGBA')
    return np.array(img)
```

### Display 2D Structure with Overlay Animation

```python
# Common educational SMILES
SMILES = {
    'caffeine':     'Cn1cnc2c1c(=O)n(c(=O)n2C)C',
    'aspirin':      'CC(=O)Oc1ccccc1C(=O)O',
    'glucose':      'OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O',
    'benzene':      'c1ccccc1',
    'ethanol':      'CCO',
    'water':        'O',
    'co2':          'O=C=O',
    'ammonia':      'N',
    'methane':      'C',
    'atp':          'c1nc(c2c(n1)n(cn2)[C@@H]3[C@@H]([C@@H]([C@H](O3)COP(=O)(O)OP(=O)(O)OP(=O)(O)O)O)O)N',
    'dna_base_a':   'Nc1ncnc2ncnc12',  # adenine
    'cholesterol':  'C[C@@H](CCCC(C)C)[C@H]1CC[C@@H]2[C@@]1(CC[C@H]3[C@H]2CC=C4[C@@]3(CC[C@@H](C4)O)C)C',
}

mol_img = mol_to_rgba(SMILES['caffeine'], width=900, height=700)

fig, ax = plt.subplots(figsize=(9, 16), dpi=120)
fig.patch.set_facecolor('#0D0D0D')
ax.set_facecolor('#0D0D0D')
ax.axis('off')

# Display molecule centered in frame
img_artist = ax.imshow(mol_img, aspect='auto',
                       extent=[-1, 1, -0.5, 0.5],  # centered
                       interpolation='lanczos')

# Animate: fade in, then highlight atoms one by one
for frame_idx in range(N_FRAMES):
    t = frame_idx / max(N_FRAMES - 1, 1)
    t_e = ease_in_out_cubic(t)
    # Fade in first 20% of animation
    alpha = min(1.0, t_e / 0.2)
    img_artist.set_alpha(alpha)
    fig.savefig(...)
```

## 3D Molecular Rotation with RDKit Conformer

```python
from rdkit import Chem
from rdkit.Chem import AllChem

def get_3d_coords(smiles):
    """Generate 3D coordinates from SMILES."""
    mol = Chem.MolFromSmiles(smiles)
    mol = Chem.AddHs(mol)
    AllChem.EmbedMolecule(mol, AllChem.ETKDGv3())
    AllChem.MMFFOptimizeMolecule(mol)
    conf = mol.GetConformer()
    atoms = []
    for atom in mol.GetAtoms():
        pos = conf.GetAtomPosition(atom.GetIdx())
        atoms.append({
            'symbol': atom.GetSymbol(),
            'pos': np.array([pos.x, pos.y, pos.z]),
            'idx': atom.GetIdx(),
        })
    bonds = [(b.GetBeginAtomIdx(), b.GetEndAtomIdx(), b.GetBondTypeAsDouble())
             for b in mol.GetBonds()]
    # Remove H for cleaner display
    heavy = [a for a in atoms if a['symbol'] != 'H']
    heavy_idx = {a['idx'] for a in heavy}
    bonds_heavy = [(i,j,t) for i,j,t in bonds
                   if i in heavy_idx and j in heavy_idx]
    return heavy, bonds_heavy

CPK_COLORS = {
    'C': '#909090', 'N': '#4FC3F7', 'O': '#FF5252',
    'S': '#FFD54F', 'P': '#FF7043', 'F': '#80CBC4',
    'Cl': '#69F0AE', 'Br': '#FF8A65', 'H': '#FFFFFF',
}
CPK_RADII = {'C': 150, 'N': 140, 'O': 160, 'S': 200,
             'P': 180, 'F': 120, 'Cl': 180, 'H': 80}

atoms, bonds = get_3d_coords(SMILES['caffeine'])
positions = np.array([a['pos'] for a in atoms])

# Center
positions -= positions.mean(axis=0)

# Scale to fit 3D axes
scale = 2.0 / (positions.max() - positions.min() + 1e-8)
positions *= scale

fig = plt.figure(figsize=(9, 16), dpi=120)
ax3d = fig.add_subplot(111, projection='3d')
fig.patch.set_facecolor('#0D0D0D')
ax3d.set_facecolor('#0D0D0D')
ax3d.set_axis_off()

for frame_idx in range(N_FRAMES):
    t = frame_idx / max(N_FRAMES - 1, 1)
    azim = -60 + ease_in_out_cubic(t) * 240  # rotate 240°
    ax3d.view_init(elev=25, azim=azim)

    if frame_idx == 0:
        # Draw once (3D rotation is just view change, not redraw)
        # Bonds
        for i, j, bond_type in bonds:
            p1, p2 = positions[i], positions[j]
            ax3d.plot([p1[0], p2[0]], [p1[1], p2[1]], [p1[2], p2[2]],
                      color='#505050', lw=2, zorder=1)

        # Atoms
        for k, atom in enumerate(atoms):
            color = CPK_COLORS.get(atom['symbol'], '#AAAAAA')
            size = CPK_RADII.get(atom['symbol'], 100)
            ax3d.scatter(*positions[k], c=color, s=size,
                         depthshade=True, alpha=0.92, edgecolors='none', zorder=2)

    fig.savefig(os.path.join(OUTPUT_DIR, f'frame_{frame_idx:04d}.png'),
                dpi=120, bbox_inches='tight', pad_inches=0,
                facecolor='#0D0D0D')
```

## Reaction Mechanism Animation (2D)

Show bond breaking and forming with curved arrows:

```python
import matplotlib.patheffects as pe

fig, ax = plt.subplots(figsize=(9, 16), dpi=120)
fig.patch.set_facecolor('#0D0D0D')
ax.set_facecolor('#0D0D0D')
ax.set_xlim(-5, 5)
ax.set_ylim(-8, 8)
ax.axis('off')

# Draw reactants and products as text/simplified structures
# Animate the transformation with FancyArrowPatch

def draw_curved_arrow(ax, start, end, color='#FFD54F', lw=2, alpha=1.0):
    """Draw curved electron-pushing arrow."""
    ax.annotate('',
        xy=end, xytext=start,
        arrowprops=dict(
            arrowstyle='->', color=color,
            lw=lw, alpha=alpha,
            connectionstyle='arc3,rad=0.4',
        ),
    )

# Animate: show reactant → TS → product over time
PHASES = [
    (0.0, 0.3, "Reactants"),
    (0.3, 0.5, "Transition State"),
    (0.5, 1.0, "Products"),
]

for frame_idx in range(N_FRAMES):
    t = frame_idx / max(N_FRAMES - 1, 1)
    # Determine current phase
    for start_t, end_t, label in PHASES:
        if start_t <= t < end_t:
            phase_t = (t - start_t) / (end_t - start_t)
            current_label = label
            break
    # Draw appropriate state
    ax.clear()
    # ... draw structures for current phase ...
    ax.text(0, 7.0, current_label, ha='center', va='top',
            fontsize=28, color='#F5F5F5', fontfamily='Roboto')
    fig.savefig(...)
```
