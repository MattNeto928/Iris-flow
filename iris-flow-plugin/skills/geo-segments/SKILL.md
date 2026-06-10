---
name: geo-segments
description: This skill should be used when generating geographic visualization code for Iris-flow geo segments, including globe rotation animations, choropleth maps, earthquake/weather data overlays, cartopy projections, and any geographic or geospatial educational visualization.
version: 1.0.0
---

# Geo Segment Generation

Geo segments visualize geographic data and global phenomena. Claude generates a complete Python script producing `N = int(duration * 30)` frames at 1080×1920 using cartopy + matplotlib Agg.

## Mandatory Structure

```python
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import cartopy.crs as ccrs
import cartopy.feature as cfeature
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

def ease_in_out_cubic(t):
    if t < 0.5: return 4 * t**3
    return 1 - (-2*t + 2)**3 / 2
```

## Rotating Globe (Orthographic Projection)

The most cinematic geo animation — Earth rotating slowly:

```python
# NOTE: Cartopy projections cannot be changed on an existing axes.
# For rotation: recreate figure+axes each frame (cartopy requirement)
# This is the correct pattern for globe rotation.

LON_START = -30.0
LON_TOTAL = 120.0  # total degrees to rotate

for frame_idx in range(N_FRAMES):
    t = frame_idx / max(N_FRAMES - 1, 1)
    t_e = ease_in_out_cubic(t)
    lon = LON_START + LON_TOTAL * t_e

    fig = plt.figure(figsize=(9, 16), dpi=120)
    fig.patch.set_facecolor('#050A14')

    # Orthographic = globe view
    proj = ccrs.Orthographic(central_longitude=lon, central_latitude=15)
    ax = fig.add_subplot(1, 1, 1, projection=proj)
    ax.set_facecolor('#050A14')

    # Background space color
    fig.patch.set_facecolor('#050A14')

    # Globe outline
    ax.add_feature(cfeature.OCEAN.with_scale('110m'),
                   facecolor='#0A1628', zorder=0)
    ax.add_feature(cfeature.LAND.with_scale('110m'),
                   facecolor='#1A2E1A', edgecolor='#2A3A2A',
                   linewidth=0.4, zorder=1)
    ax.add_feature(cfeature.COASTLINE.with_scale('110m'),
                   edgecolor='#3A5A3A', linewidth=0.6, zorder=2)
    ax.add_feature(cfeature.BORDERS.with_scale('110m'),
                   edgecolor='#2A3A2A', linewidth=0.3, zorder=2)
    ax.add_feature(cfeature.LAKES.with_scale('110m'),
                   facecolor='#0A1628', zorder=2)

    # Globe boundary (circular clip)
    ax.set_global()

    # Optional: add night/day shading or data points
    # ax.scatter([lon_data], [lat_data], transform=ccrs.PlateCarree(),
    #            c=values, cmap='plasma', s=15, alpha=0.7, zorder=5)

    # Title
    fig.text(0.5, 0.93, "Title Text", ha='center', va='top',
             fontsize=26, color='#F5F5F5', fontfamily='Roboto')

    plt.tight_layout(pad=0.5)
    fig.savefig(
        os.path.join(OUTPUT_DIR, f'frame_{frame_idx:04d}.png'),
        dpi=120, bbox_inches='tight', pad_inches=0,
        facecolor='#050A14',
    )
    plt.close(fig)
```

## Dark Earth Aesthetic — Color Palette

```python
DEEP_OCEAN  = '#061020'   # deep ocean
SHELF_OCEAN = '#0A1628'   # shallow ocean
LAND        = '#1A2810'   # land (dark green-grey)
HIGHLAND    = '#2A3018'   # mountains
COAST_LINE  = '#3A5A3A'   # coastlines
BORDER      = '#2A3020'   # country borders
SPACE_BG    = '#050A14'   # space background for globe

# Alternative: space/satellite night view
NIGHT_OCEAN = '#040810'
NIGHT_LAND  = '#0F1510'
CITY_COLOR  = '#FFD54F'   # city lights color
```

## Choropleth Map (Static World + Animated Data)

For data overlaid on a Mollweide/Robinson projection:

```python
# Use Robinson for world maps — minimal distortion, good for 9:16
fig = plt.figure(figsize=(9, 16), dpi=120)
fig.patch.set_facecolor('#0D0D0D')

ax = fig.add_subplot(1, 1, 1,
                      projection=ccrs.Robinson(central_longitude=0))
ax.set_global()
ax.set_facecolor('#0A1628')

ax.add_feature(cfeature.OCEAN.with_scale('110m'), facecolor='#061020', zorder=0)
ax.add_feature(cfeature.LAND.with_scale('110m'),  facecolor='#1A2810', zorder=1)
ax.add_feature(cfeature.COASTLINE.with_scale('110m'),
               edgecolor='#3A5A3A', linewidth=0.5, zorder=2)

# Data points (e.g., earthquake locations)
lons = np.random.uniform(-180, 180, 200)
lats = np.random.uniform(-60, 70, 200)
magnitudes = np.random.exponential(scale=2, size=200) + 2.0

scatter = ax.scatter(lons, lats, c=magnitudes,
                     transform=ccrs.PlateCarree(),
                     cmap='plasma', vmin=2, vmax=8,
                     s=magnitudes**2 * 3, alpha=0.7,
                     linewidths=0.3, edgecolors='white',
                     zorder=5)
```

## Zoom Into a Region

```python
# Animate zoom into a specific region using extent
START_EXTENT = [-180, 180, -85, 85]   # global
END_EXTENT   = [-15, 45, 35, 65]      # Europe

for frame_idx in range(N_FRAMES):
    t_e = ease_in_out_cubic(frame_idx / max(N_FRAMES-1, 1))

    extent = [
        START_EXTENT[0] + (END_EXTENT[0] - START_EXTENT[0]) * t_e,
        START_EXTENT[1] + (END_EXTENT[1] - START_EXTENT[1]) * t_e,
        START_EXTENT[2] + (END_EXTENT[2] - START_EXTENT[2]) * t_e,
        START_EXTENT[3] + (END_EXTENT[3] - START_EXTENT[3]) * t_e,
    ]

    fig = plt.figure(figsize=(9, 16), dpi=120)
    ax = fig.add_subplot(1, 1, 1, projection=ccrs.PlateCarree())
    ax.set_extent(extent, crs=ccrs.PlateCarree())
    # ... add features ...
    fig.savefig(...)
    plt.close(fig)
```

## Projection Reference for 9:16

| Projection | Best for | Class |
|-----------|----------|-------|
| Orthographic | Globe rotation | `ccrs.Orthographic(lon, lat)` |
| Robinson | World choropleth | `ccrs.Robinson()` |
| Mollweide | Equal-area world | `ccrs.Mollweide()` |
| LambertConformal | Regional (continents) | `ccrs.LambertConformal()` |
| PlateCarree | Simple regional zoom | `ccrs.PlateCarree()` |
| Mercator | City/country zoom | `ccrs.Mercator()` |

## Important: Cartopy Figure Recreation

Unlike matplotlib, **cartopy axes with a projection cannot be updated in place** when the projection itself must change (e.g., changing `central_longitude` for globe rotation). Always:
1. Create a new `fig, ax` each frame
2. Close with `plt.close(fig)` after saving
3. This is ~2-3x slower but necessary for correct globe rotation

For animations where the projection is FIXED (only data changes), you can initialize once and update:
```python
fig, ax = plt.subplots(subplot_kw={'projection': ccrs.Robinson()}, ...)
scatter = ax.scatter(...)  # initialize
for frame_idx in range(N_FRAMES):
    scatter.set_offsets(new_data)   # update data only
    fig.savefig(...)
# Do NOT plt.close() inside the loop in this case
```
