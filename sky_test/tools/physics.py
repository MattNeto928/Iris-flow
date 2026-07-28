#!/usr/bin/env python3
"""
Compute every number and colour the piece puts on screen, and bake to JSON.

The scene reads data/physics.json and never re-derives a quantity. If something
on screen is wrong, it is wrong HERE, not in the renderer.

Sources for the inputs (everything else is derived):
  T_sun      = 5772 K      IAU 2015 Resolution B3 nominal solar effective temperature
  b_Wien     = 2.897771955e-3 m K   (CODATA, exact from h,c,k)
  n_air(l)   Peck & Reeder 1972 dispersion, dry air 15 C, 101.325 kPa
  F_king(l)  Bodhaine et al. 1999 depolarisation / King correction, dry air
  N_std      2.546899e19 cm^-3      number density at 288.15 K, 1013.25 mb
  airmass    Kasten & Young 1989 empirical fit
  CMFs       Wyman, Sloan & Shirley 2013 analytic multi-lobe Gaussian fit to
             the CIE 1931 2-degree observer (~1% of the tabulated curves)
  d_N2       0.364 nm  kinetic diameter of N2
"""

import json
import math
import os

import numpy as np

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
os.makedirs(OUT, exist_ok=True)

# ------------------------------------------------------------------ constants
h_P = 6.62607015e-34          # J s   (exact, SI 2019)
c_0 = 2.99792458e8            # m/s   (exact)
k_B = 1.380649e-23            # J/K   (exact)
b_WIEN = 2.897771955e-3       # m K
T_SUN = 5772.0                # K
N_STD = 2.546899e19           # cm^-3, molecules of air at 288.15 K / 1013.25 mb
P_STD = 101325.0              # Pa
G_STD = 9.80665               # m/s^2
M_AIR = 28.9644e-3 / 6.02214076e23   # kg per air molecule (mean)
D_N2_NM = 0.364               # nm, kinetic diameter of N2

report = {}


def note(k, v, unit="", src=""):
    report[k] = (v, unit, src)
    return v


# ------------------------------------------------------------------ 1. the Sun
def planck(lam_m, T):
    """Spectral radiance per unit WAVELENGTH (W m^-3 sr^-1)."""
    return (2 * h_P * c_0 ** 2) / lam_m ** 5 / np.expm1(h_P * c_0 / (lam_m * k_B * T))


lam_peak_nm = b_WIEN / T_SUN * 1e9
note("wien_peak_nm", lam_peak_nm, "nm", "b_Wien / T_sun")

# ------------------------------------------------------- 2. air optics
def n_air(lam_um):
    """Peck & Reeder (1972), dry air. lam in micrometres."""
    s2 = (1.0 / lam_um) ** 2
    return 1.0 + (8060.51 + 2480990.0 / (132.274 - s2) + 17455.7 / (39.32957 - s2)) * 1e-8


def f_king(lam_um):
    """Bodhaine et al. (1999) eq. 5, dry air with 360 ppm CO2."""
    s2 = (1.0 / lam_um) ** 2
    f_n2 = 1.034 + 3.17e-4 * s2
    f_o2 = 1.096 + 1.385e-3 * s2 + 1.448e-4 * s2 * s2
    return (78.084 * f_n2 + 20.946 * f_o2 + 0.934 * 1.00 + 0.036 * 1.15) / (
        78.084 + 20.946 + 0.934 + 0.036
    )


def sigma_rayleigh_cm2(lam_um):
    """Rayleigh scattering cross-section per molecule, cm^2. Bodhaine eq. 1."""
    lam_cm = lam_um * 1e-4
    n = n_air(lam_um)
    n2 = n * n
    return (
        24.0 * math.pi ** 3 * (n2 - 1.0) ** 2
        / (lam_cm ** 4 * N_STD ** 2 * (n2 + 2.0) ** 2)
        * f_king(lam_um)
    )


# column number density of the whole atmosphere, molecules per cm^2
N_COL_CM2 = P_STD / (M_AIR * G_STD) / 1e4
note("column_density_cm2", N_COL_CM2, "molecules/cm^2", "P/(m_air g)")


def tau_zenith(lam_um):
    """Rayleigh optical depth of the whole atmosphere, looking straight up."""
    return sigma_rayleigh_cm2(lam_um) * N_COL_CM2


# --- validation against published values -----------------------------------
val = {
    "sigma_550nm_cm2": sigma_rayleigh_cm2(0.550),   # Bodhaine table: 4.553e-27
    "tau_550nm": tau_zenith(0.550),                 # literature: ~0.0973
    "tau_400nm": tau_zenith(0.400),
    "n_air_550nm": n_air(0.550),                    # literature: ~1.000277
}

# ------------------------------------------------------- 3. the lambda^-4 law
LAM_BLUE_NM, LAM_RED_NM = 400.0, 700.0
ratio_pure = (LAM_RED_NM / LAM_BLUE_NM) ** 4
ratio_full = sigma_rayleigh_cm2(LAM_BLUE_NM / 1000) / sigma_rayleigh_cm2(LAM_RED_NM / 1000)
note("ratio_pure_400_700", ratio_pure, "x", "(700/400)^4, the bare 1/lambda^4 law")
note("ratio_full_400_700", ratio_full, "x", "full cross-section incl. dispersion + King")

# a second, gentler pair often quoted
note("ratio_pure_440_660", (660.0 / 440.0) ** 4, "x", "(660/440)^4 = 1.5^4")

# ------------------------------------------------------- 4. scale of a molecule
size_ratio = lam_peak_nm / D_N2_NM
size_param = math.pi * D_N2_NM / lam_peak_nm      # Rayleigh regime needs x << 1
note("wave_vs_molecule", size_ratio, "x", "wien peak / N2 kinetic diameter")
note("size_parameter_x", size_param, "", "pi d / lambda")

# ------------------------------------------------------- 5. airmass & sunset
def airmass(zenith_deg):
    """Kasten & Young (1989). The secant law diverges at the horizon; this does not."""
    z = float(zenith_deg)
    return 1.0 / (math.cos(math.radians(z)) + 0.50572 * (96.07995 - z) ** -1.6364)


AM_HORIZON = airmass(90.0)
note("airmass_horizon", AM_HORIZON, "x zenith path", "Kasten-Young at z=90 deg")

LAM_B_UM, LAM_R_UM = 0.440, 0.660
tau_b, tau_r = tau_zenith(LAM_B_UM), tau_zenith(LAM_R_UM)
T_b = math.exp(-tau_b * AM_HORIZON)
T_r = math.exp(-tau_r * AM_HORIZON)
note("tau_zenith_440", tau_b, "", "")
note("tau_zenith_660", tau_r, "", "")
note("horizon_transmit_ratio", T_r / T_b, "x", "exp(-tau_r*AM)/exp(-tau_b*AM) at AM=37.92")

# fraction of photons scattered at least once on a straight-up path
frac_b = 1.0 - math.exp(-tau_b)
frac_r = 1.0 - math.exp(-tau_r)
note("zenith_scatter_frac_440", frac_b, "", "1 - exp(-tau)")
note("zenith_scatter_frac_660", frac_r, "", "1 - exp(-tau)")

# ------------------------------------------------------- 6. colour science
def cmf_xyz(lam_nm):
    """CIE 1931 2-deg colour matching functions, Wyman/Sloan/Shirley analytic fit."""

    def g(x, mu, s1, s2):
        t = (x - mu) * np.where(x < mu, 1.0 / s1, 1.0 / s2)
        return np.exp(-0.5 * t * t)

    x = 1.056 * g(lam_nm, 599.8, 37.9, 31.0) + 0.362 * g(lam_nm, 442.0, 16.0, 26.7) \
        - 0.065 * g(lam_nm, 501.1, 20.4, 26.2)
    y = 0.821 * g(lam_nm, 568.8, 46.9, 40.5) + 0.286 * g(lam_nm, 530.9, 16.3, 31.1)
    z = 1.217 * g(lam_nm, 437.0, 11.8, 36.0) + 0.681 * g(lam_nm, 459.0, 26.0, 13.8)
    return x, y, z


LAM = np.arange(360.0, 831.0, 1.0)
XB, YB, ZB = cmf_xyz(LAM)

M_XYZ2RGB = np.array([          # sRGB / Rec.709 primaries, D65
    [3.2406255, -1.5372080, -0.4986286],
    [-0.9689307, 1.8757561, 0.0415175],
    [0.0557101, -0.2040211, 1.0569959],
])


def spec_to_xyz(spd):
    X = np.trapezoid(spd * XB, LAM)
    Y = np.trapezoid(spd * YB, LAM)
    Z = np.trapezoid(spd * ZB, LAM)
    return np.array([X, Y, Z])


def encode_srgb(lin):
    lin = np.clip(lin, 0.0, 1.0)
    return np.where(lin <= 0.0031308, lin * 12.92, 1.055 * lin ** (1 / 2.4) - 0.055)


def xyz_to_hex(xyz, desat=True, boost=1.0):
    """XYZ -> sRGB hex. Desaturates toward white to bring out-of-gamut hues in."""
    xyz = xyz / max(xyz[1], 1e-12)
    rgb = M_XYZ2RGB @ xyz
    if desat and rgb.min() < 0:
        # pull toward equal-energy white until the darkest primary reaches 0
        rgb = rgb - rgb.min()
    rgb = rgb / max(rgb.max(), 1e-12) * boost
    s = encode_srgb(rgb)
    return "#%02x%02x%02x" % tuple(int(round(v * 255)) for v in s)


# white-point sanity: an equal-energy spectrum must land on x = y = 1/3
ee = spec_to_xyz(np.ones_like(LAM))
val["equal_energy_xy"] = [float(ee[0] / ee.sum()), float(ee[1] / ee.sum())]
sun_xyz = spec_to_xyz(planck(LAM * 1e-9, T_SUN))
val["sun_5772K_xy"] = [float(sun_xyz[0] / sun_xyz.sum()), float(sun_xyz[1] / sun_xyz.sum())]

# --- the spectrum strip: one sRGB swatch per wavelength ---------------------
strip = []
for lam in np.arange(380.0, 721.0, 2.0):
    x, y, z = cmf_xyz(np.array([lam]))
    xyz = np.array([x[0], y[0], z[0]])
    lin = M_XYZ2RGB @ (xyz / max(xyz.sum(), 1e-12))
    lin = np.clip(lin, 0, None)
    lin = lin / max(lin.max(), 1e-9)
    # dim the deep ends the way the eye does, so 400 and 700 nm read as faint
    lum = float(np.clip(cmf_xyz(np.array([lam]))[1][0], 0, 1)) ** 0.32
    s = encode_srgb(lin * max(lum, 0.10))
    strip.append([float(lam), "#%02x%02x%02x" % tuple(int(round(v * 255)) for v in s)])

# --- derived colours -------------------------------------------------------
solar = planck(LAM * 1e-9, T_SUN)
lam_um = LAM / 1000.0
sig = np.array([sigma_rayleigh_cm2(l) for l in lam_um])

# single-scattered zenith sky: solar spectrum weighted by the scattering
# cross-section. Real sky is paler (multiple scattering, ozone, aerosol).
sky_hex = xyz_to_hex(spec_to_xyz(solar * sig))

# direct sun through a given airmass
tau = sig * N_COL_CM2


def sun_hex(am):
    return xyz_to_hex(spec_to_xyz(solar * np.exp(-tau * am)))


colours = {
    "sky_single_scatter": sky_hex,
    "sun_am1": sun_hex(1.0),
    "sun_am5": sun_hex(5.0),
    "sun_am15": sun_hex(15.0),
    "sun_horizon": sun_hex(AM_HORIZON),
    "blue_440": strip[min(range(len(strip)), key=lambda i: abs(strip[i][0] - 440))][1],
    "red_660": strip[min(range(len(strip)), key=lambda i: abs(strip[i][0] - 660))][1],
    "violet_410": strip[min(range(len(strip)), key=lambda i: abs(strip[i][0] - 410))][1],
}

# --- why not violet: how much violet actually reaches the eye ---------------
# scattered radiance x cone-ish sensitivity. Compare the band 380-450 against
# 450-520 in terms of what the luminous observer registers.
scat = solar * sig
band = lambda a, b: float(np.trapezoid((scat * YB)[(LAM >= a) & (LAM < b)],
                                       LAM[(LAM >= a) & (LAM < b)]))
v_band, b_band = band(380, 450), band(450, 520)
note("violet_vs_blue_seen", b_band / v_band, "x",
     "luminance-weighted scattered energy 450-520 nm vs 380-450 nm")

# How sensitive the eye is at 400 nm. NOTE: taken from the TABULATED CIE 1931
# ybar, not from the analytic fit above -- the Wyman fit is good to ~1% through
# the body of the curve but is ~3x too high in the deep-blue tail (it returns
# 0.13% here against the table's 0.04%). Anything quoted from the far tail has
# to come off the table.
YBAR_TABLE = {400: 0.0004, 450: 0.038, 555: 1.000}   # CIE 1931 2-deg observer
note("eye_sens_400_pct", 100.0 * YBAR_TABLE[400] / YBAR_TABLE[555], "% of peak",
     "tabulated CIE 1931 ybar(400)/ybar(555)")
note("eye_sens_450_pct", 100.0 * YBAR_TABLE[450] / YBAR_TABLE[555], "% of peak",
     "tabulated CIE 1931 ybar(450)/ybar(555)")
val["ybar400_fit_vs_table_pct"] = [
    100.0 * float(cmf_xyz(np.array([400.0]))[1][0]), 100.0 * YBAR_TABLE[400]]
# and how much less violet the Sun emits than blue-green
p = lambda l: float(planck(float(l) * 1e-9, T_SUN))
note("solar_400_vs_502_pct", 100.0 * p(400) / p(502), "%",
     "Planck(400nm)/Planck(peak) at 5772 K")

# ------------------------------------------------------- 7. photon Monte Carlo
# Two populations of photons crossing the real atmosphere on a straight-up
# sightline, stepping with the REAL Rayleigh mean free path for their
# wavelength and turning through the REAL Rayleigh phase function.
#
# The slab is 1.0 "screen unit" tall and carries the true zenith optical depth
# of its wavelength, so the geometry is a free choice but the physics -- how
# often a photon turns, and through what angle -- is not.
rng = np.random.default_rng(20260726)


def sample_rayleigh_mu(u):
    """Invert the Rayleigh phase CDF: pdf(mu) = (3/8)(1+mu^2) on [-1,1]."""
    q = -8.0 * (u - 0.5)
    disc = np.sqrt(q * q / 4.0 + 1.0)
    return np.cbrt(-q / 2.0 + disc) + np.cbrt(-q / 2.0 - disc)


def walk(tau_total, n_photons, max_scatter=14, seed_dir=(0.0, -1.0, 0.0)):
    """Return polylines in a unit-height slab (y from 1 down to 0)."""
    paths = []
    for _ in range(n_photons):
        # ALL photons enter on the same line: this is one sunbeam, not a
        # rain of independent ones. The scattered fraction then visibly peels
        # OUT of a single bright column, which is what "the sky is blue" looks
        # like. The jitter only stops coincident tubes from z-fighting.
        pos = np.array([rng.uniform(-0.02, 0.02), 1.0, rng.uniform(-0.02, 0.02)])
        d = np.array(seed_dir, dtype=float)
        pts = [pos.copy()]
        nscat = 0
        for _ in range(max_scatter):
            # optical depth to travel before the next scatter
            t_opt = rng.exponential(1.0)
            # convert to geometric length: tau_total optical depths per unit y-height
            step = t_opt / tau_total
            nxt = pos + d * step
            if nxt[1] <= 0.0 or nxt[1] >= 1.35 or abs(nxt[0]) > 1.5:
                # left the slab: clip exactly to the first boundary crossed, so
                # exit points sit ON the box and the polyline can be drawn raw
                ts = [step]
                for axis, lim in ((1, 0.0), (1, 1.35), (0, -1.5), (0, 1.5)):
                    if abs(d[axis]) > 1e-9:
                        t = (lim - pos[axis]) / d[axis]
                        if 1e-9 < t <= step:
                            ts.append(t)
                pts.append((pos + d * min(ts)).tolist())
                break
            pos = nxt
            pts.append(pos.copy().tolist() if isinstance(pos, np.ndarray) else list(pos))
            nscat += 1
            mu = float(sample_rayleigh_mu(rng.random()))
            phi = rng.random() * 2 * math.pi
            # rotate d by (mu, phi) in its own frame
            w = d / np.linalg.norm(d)
            a = np.array([1.0, 0.0, 0.0]) if abs(w[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
            u1 = np.cross(w, a); u1 /= np.linalg.norm(u1)
            u2 = np.cross(w, u1)
            st = math.sqrt(max(0.0, 1.0 - mu * mu))
            d = mu * w + st * math.cos(phi) * u1 + st * math.sin(phi) * u2
        paths.append({"pts": [[round(float(v), 4) for v in p] for p in
                              (p.tolist() if isinstance(p, np.ndarray) else p for p in pts)],
                      "n": nscat})
    return paths


N_PH = 76
mc = {
    "blue": walk(tau_b, N_PH),
    "red": walk(tau_r, N_PH),
    "tau_blue": tau_b,
    "tau_red": tau_r,
}
mc["blue_scattered"] = sum(1 for p in mc["blue"] if p["n"] > 0)
mc["red_scattered"] = sum(1 for p in mc["red"] if p["n"] > 0)

# ------------------------------- 7b. scattered spectrum vs perceived spectrum
# Two curves for the violet beat: how much of each wavelength Rayleigh scatters
# out of the beam, and how much of THAT the eye actually registers.
#
# CAVEAT, and it happens to fall the safe way: the analytic ybar fit is ~3x too
# HIGH in the deep-blue tail (0.13% at 400 nm against the table's 0.04%). So the
# "seen" curve here is more generous to violet than reality, and the conclusion
# it supports -- that violet contributes little of what you see -- is understated
# rather than overstated.
lam_p = np.arange(380.0, 701.0, 2.5)
scat_p = planck(lam_p * 1e-9, T_SUN) * np.array([sigma_rayleigh_cm2(l / 1000) for l in lam_p])
ybar_p = cmf_xyz(lam_p)[1]
seen_p = scat_p * ybar_p
violet_curves = {
    "lam": [float(v) for v in lam_p],
    "scattered": [float(v) for v in scat_p / scat_p.max()],
    "seen": [float(v) for v in seen_p / seen_p.max()],
    "peak_scattered_nm": float(lam_p[int(scat_p.argmax())]),
    "peak_seen_nm": float(lam_p[int(seen_p.argmax())]),
}
note("peak_scattered_nm", violet_curves["peak_scattered_nm"], "nm",
     "argmax of solar x sigma_R")
note("peak_seen_nm", violet_curves["peak_seen_nm"], "nm",
     "argmax of solar x sigma_R x ybar")

# ------------------------------------------------------- 8. lambda^-4 curve
curve = [[float(l), float((550.0 / l) ** 4)] for l in np.arange(380.0, 721.0, 5.0)]

# ------------------------------------------------------- bake
data = {
    "meta": {"generated_by": "tools/physics.py"},
    "numbers": {k: v[0] for k, v in report.items()},
    "provenance": {k: {"unit": v[1], "from": v[2]} for k, v in report.items()},
    "validation": {k: (float(v) if not isinstance(v, list) else v) for k, v in val.items()},
    "colours": colours,
    "spectrum_strip": strip,
    "lambda4_curve": curve,
    "montecarlo": mc,
    "violet_curves": violet_curves,
}
with open(os.path.join(OUT, "physics.json"), "w") as f:
    json.dump(data, f, indent=1)

# ------------------------------------------------------- print
print("VALIDATION (left = computed, right = published)")
print(f"  sigma(550nm)      {val['sigma_550nm_cm2']:.4e} cm^2   vs 4.553e-27 (Bodhaine)")
print(f"  tau_zenith(550)   {val['tau_550nm']:.5f}             vs ~0.0973")
print(f"  n_air(550nm)      {val['n_air_550nm']:.8f}          vs ~1.00027726")
print(f"  equal-energy xy   {val['equal_energy_xy'][0]:.4f},{val['equal_energy_xy'][1]:.4f}   vs 0.3333,0.3333")
print(f"  5772K sun xy      {val['sun_5772K_xy'][0]:.4f},{val['sun_5772K_xy'][1]:.4f}   vs ~0.3252,0.3348")
print()
print("ON-SCREEN NUMBERS")
for k, (v, unit, src) in report.items():
    print(f"  {k:26s} {v:>14.4f} {unit:<22s} {src}")
print()
print("COLOURS (derived by spectral integration)")
for k, v in colours.items():
    print(f"  {k:22s} {v}")
print()
print(f"MONTE CARLO  blue scattered {mc['blue_scattered']}/{N_PH}   "
      f"red scattered {mc['red_scattered']}/{N_PH}")
print(f"  expected from 1-exp(-tau): blue {frac_b*N_PH:.1f}, red {frac_r*N_PH:.1f}")
