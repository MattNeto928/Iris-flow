#!/usr/bin/env python3
"""
Compute every number and curve the CMB piece puts on screen.

Nothing in the scene invents a value: it reads data/cmb.json, and every field in
that file is either a CODATA/SI constant, a Planck 2018 published parameter used
as an INPUT, or something derived here from a real Boltzmann solve (CAMB).

Run:  .venv/bin/python solve.py
Every derived quantity is printed next to its published counterpart so a drift
is visible rather than silent.
"""

import json
import os

import numpy as np

# ----------------------------------------------------------------- constants
# CODATA 2018 / SI-2019 exact where applicable.
h_P = 6.62607015e-34        # J s        (exact, SI 2019)
k_B = 1.380649e-23          # J/K        (exact, SI 2019)
c_l = 2.99792458e8          # m/s        (exact)
sigma_T = 6.6524587321e-29  # m^2        Thomson cross-section, CODATA 2018
m_p = 1.67262192369e-27     # kg         CODATA 2018
G_N = 6.67430e-11           # m^3/kg/s^2 CODATA 2018
Mpc = 3.0856775814913673e22 # m          IAU
yr = 3.1557e7               # s          Julian year 365.25 d
b_wien_lam = 2.897771955e-3 # m K        Wien displacement (wavelength), CODATA
x_wien_nu = 2.8214393721220787  # root of 3(1-e^-x)=x, Wien peak in frequency

# ------------------------------------------------- Planck 2018 INPUT params
# Planck 2018 results VI, Table 2, column "TT,TE,EE+lowE+lensing" (base LCDM).
# These are INPUTS to the solve; the derived params below are outputs we check.
P18 = dict(H0=67.36, ombh2=0.02237, omch2=0.1200, tau=0.0544,
           ns=0.9649, lnAs1e10=3.044, mnu=0.06)
# FIRAS monopole temperature, Fixsen 2009 (ApJ 707, 916): 2.72548 +/- 0.00057 K
T0 = 2.72548
T0_err = 0.00057
# Fixsen et al. 1996 (ApJ 473, 576): the FIRAS spectrum is a blackbody to within
# 50 ppm of the peak brightness (95% CL).
FIRAS_PPM = 50

# Published values we check the solve against (Planck 2018 VI Table 2).
PUB = dict(zstar=(1089.92, 0.25), rstar=(144.43, 0.26), thetastar100=(1.04110, 0.00031),
           age=(13.797, 0.023), zdrag=(1059.94, 0.30), zeq=(3402, 26))

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(OUT, exist_ok=True)

checks = []
def check(name, got, ref, err=None, tol_sigma=3.0, unit=""):
    """Print derived vs published and record a pass/fail."""
    if err:
        dev = abs(got - ref) / err
        ok = dev <= tol_sigma
        print(f"  {name:28s} {got:12.5f} {unit:8s} vs published {ref} +/- {err}"
              f"   ({dev:.2f} sigma)  {'OK' if ok else 'MISMATCH'}")
    else:
        dev = abs(got - ref) / abs(ref)
        ok = dev <= tol_sigma
        print(f"  {name:28s} {got:12.5f} {unit:8s} vs published {ref}"
              f"   ({dev*100:.2f}%)  {'OK' if ok else 'MISMATCH'}")
    checks.append((name, ok))
    return ok


# =========================================================== 1. CAMB SOLVE
import camb  # noqa: E402

print("== CAMB solve (Planck 2018 base-LCDM) ==")
pars = camb.CAMBparams()
pars.set_cosmology(H0=P18["H0"], ombh2=P18["ombh2"], omch2=P18["omch2"],
                   mnu=P18["mnu"], omk=0.0, tau=P18["tau"], TCMB=T0)
pars.InitPower.set_params(As=np.exp(P18["lnAs1e10"]) * 1e-10, ns=P18["ns"], r=0)
pars.set_for_lmax(2500, lens_potential_accuracy=1)
res = camb.get_results(pars)
d = res.get_derived_params()

zstar = float(d["zstar"])
rstar = float(d["rstar"])                 # Mpc, comoving sound horizon at z*
thetastar = float(d["thetastar"])         # already 100*theta_* in CAMB
age = float(d["age"])                     # Gyr
zdrag = float(d["zdrag"])
zeq = float(d["zeq"])

print("\n== derived vs Planck 2018 published ==")
check("z_* (last scattering)", zstar, *PUB["zstar"])
check("r_s(z_*)  [Mpc]", rstar, *PUB["rstar"], unit="Mpc")
check("100 theta_*", thetastar, *PUB["thetastar100"])
check("age of universe [Gyr]", age, *PUB["age"], unit="Gyr")
check("z_drag", zdrag, *PUB["zdrag"])
check("z_eq (matter-radiation)", zeq, *PUB["zeq"])

# Age at recombination. CAMB integrates the same background used for z_*, so
# this is consistent with it rather than a separate hand-rolled cosmology.
t_star_Gyr = float(res.physical_time(zstar))
t_star_yr = t_star_Gyr * 1e9
# Commonly quoted as "380,000 years"; Planck-based integrations give ~370 kyr.
check("t(z_*) [kyr]", t_star_yr / 1e3, 380.0, tol_sigma=0.10, unit="kyr")
print(f"    -> t(z_*) = {t_star_yr:,.0f} yr; the familiar '380,000 years' is this rounded.")

# Angular scale of the sound horizon on the sky.
theta_star_deg = (thetastar / 100.0) * 180.0 / np.pi
# How far away the surface of last scattering is NOW: chi = r_s / theta_*.
chi_star_Mpc = rstar / (thetastar / 100.0)
chi_star_Gly = chi_star_Mpc * Mpc / (c_l * yr) / 1e9
check("comoving dist to LSS [Mpc]", chi_star_Mpc, 13870.0, tol_sigma=0.01, unit="Mpc")
print(f"  -> {chi_star_Gly:.1f} billion light-years away in comoving distance; "
      f"the light itself has been travelling {age - t_star_Gyr:.3f} Gyr.")
travel_Gyr = age - t_star_Gyr

# ================================================== 2. TEMPERATURE HISTORY
T_star = T0 * (1.0 + zstar)
stretch = 1.0 + zstar
print("\n== temperature ==")
print(f"  T_0                          {T0:.5f} K  +/- {T0_err} (FIRAS, Fixsen 2009)")
check("T(z_*) = T_0 (1+z_*)", T_star, 3000.0, tol_sigma=0.02, unit="K")
print(f"  stretch factor 1+z_*         {stretch:.2f}x")

# ================================================== 3. BLACKBODY TODAY
nu_peak = x_wien_nu * k_B * T0 / h_P                      # Hz
lam_peak = b_wien_lam / T0                                # m
# n_gamma = (2 zeta(3)/pi^2) (k T / hbar c)^3
from scipy.special import zeta  # noqa: E402
hbar = h_P / (2 * np.pi)
n_gamma = (2 * zeta(3) / np.pi**2) * (k_B * T0 / (hbar * c_l))**3   # m^-3
a_rad = 8 * np.pi**5 * k_B**4 / (15 * h_P**3 * c_l**3)             # J m^-3 K^-4
rho_gamma = a_rad * T0**4                                          # J/m^3
print("\n== blackbody at T_0 ==")
check("nu_peak [GHz]", nu_peak / 1e9, 160.23, tol_sigma=0.01, unit="GHz")
check("lambda_peak [mm]", lam_peak * 1e3, 1.063, tol_sigma=0.01, unit="mm")
check("n_gamma [cm^-3]", n_gamma / 1e6, 410.7, tol_sigma=0.01, unit="cm^-3")
print(f"  rho_gamma                    {rho_gamma/1.602176634e-19*1e-6:.4f} eV/cm^3")

# Photon mean free path just before recombination, for context (not shown).
n_b0 = P18["ombh2"] * 3 * (100e3 / Mpc)**2 / (8 * np.pi * G_N) / m_p   # m^-3
print(f"  n_b today                    {n_b0/1e6:.3e} cm^-3 "
      f"(cf. 2.503e-7 * ombh2/0.022 = {2.503e-7*P18['ombh2']/0.022:.3e})")

# ============================================ 4. PLANCK SPECTRUM CURVES
def planck_nu(nu, T):
    """Spectral radiance B_nu, W m^-2 sr^-1 Hz^-1."""
    x = h_P * nu / (k_B * T)
    return (2 * h_P * nu**3 / c_l**2) / np.expm1(x)

nu_ax = np.linspace(1e9, 700e9, 700)                 # 1 - 700 GHz
I_T0 = planck_nu(nu_ax, T0)
# MJy/sr is the unit FIRAS is plotted in: 1 Jy = 1e-26 W m^-2 Hz^-1
I_T0_MJy = I_T0 / 1e-26 / 1e6
print(f"\n  peak brightness at T_0       {I_T0_MJy.max():.1f} MJy/sr "
      f"(FIRAS peak ~385 MJy/sr)")
check("peak B_nu [MJy/sr]", I_T0_MJy.max(), 385.0, tol_sigma=0.02, unit="MJy/sr")

# The same spectrum at recombination, expressed on a normalised axis so both fit
# one plot: a blackbody redshifts INTO a blackbody, so on axes scaled by T the
# two curves are identical -- that is the point the beat makes.
xs = np.linspace(0.05, 12.0, 400)                    # x = h nu / k T
bb_shape = xs**3 / np.expm1(xs)
bb_shape /= bb_shape.max()

# ================================================ 5. IONISATION HISTORY
zg = np.concatenate([np.linspace(500, 2500, 800)])
bg = res.get_background_redshift_evolution(zg, ["x_e", "visibility"], format="array")
xe = np.asarray(bg[:, 0], dtype=float)
vis = np.asarray(bg[:, 1], dtype=float)
vis = vis / vis.max()
# Where the visibility function peaks IS the surface of last scattering.
z_vis_peak = float(zg[int(np.argmax(vis))])
check("z at visibility peak", z_vis_peak, zstar, tol_sigma=0.01)
# Half-max width of the visibility function -> thickness of last scattering.
above = zg[vis > 0.5]
dz_lss = float(above.max() - above.min())
print(f"  last-scattering thickness    Delta z ~ {dz_lss:.0f} (FWHM of visibility)")
# x_e at z_*
xe_star = float(np.interp(zstar, zg, xe))
print(f"  x_e at z_*                   {xe_star:.3f}  (free electrons per H nucleus)")

# ================================================ 6. ANISOTROPY SPECTRUM
powers = res.get_cmb_power_spectra(pars, CMB_unit="muK", spectra=["total"])
tot = powers["total"]          # [l, (TT,EE,BB,TE)], l index 0..lmax
lmax = tot.shape[0] - 1
ell = np.arange(lmax + 1)
Dl = tot[:, 0]                                       # l(l+1)C_l/2pi in muK^2
with np.errstate(divide="ignore", invalid="ignore"):
    Cl = np.where(ell >= 2, 2 * np.pi * Dl / (ell * (ell + 1)), 0.0)
Cl[:2] = 0.0

rms_uK = float(np.sqrt(np.sum((2 * ell[2:] + 1) / (4 * np.pi) * Cl[2:])))
print("\n== anisotropies ==")
check("rms Delta T [muK]", rms_uK, 110.0, tol_sigma=0.15, unit="muK")
print(f"  Delta T / T                  {rms_uK*1e-6/T0:.3e}  "
      f"= 1 part in {T0/(rms_uK*1e-6):,.0f}")

# The canonical "one part in 100,000" is the LARGE-ANGLE amplitude COBE measured,
# not the full-resolution rms above: most of the 112 muK sits in the acoustic
# peaks at l ~ 200-1000, which COBE's 7 deg beam could not resolve. Apply a
# Gaussian beam window and the familiar number falls out.
def rms_smoothed(fwhm_deg):
    sb = np.radians(fwhm_deg) / np.sqrt(8 * np.log(2))
    Bl = np.exp(-ell * (ell + 1) * sb**2 / 2)
    return float(np.sqrt(np.sum((2 * ell[2:] + 1) / (4 * np.pi) * Cl[2:] * Bl[2:]**2)))

rms_10deg = rms_smoothed(10.0)
rms_7deg = rms_smoothed(7.0)
print(f"  rms at 10 deg smoothing      {rms_10deg:.1f} muK "
      f"= 1 part in {T0/(rms_10deg*1e-6):,.0f}")
print(f"  rms at 7 deg smoothing       {rms_7deg:.1f} muK")
# COBE-DMR's familiar "29 +/- 1 muK at 10 deg" is NOT a 10 deg Gaussian applied
# to the theory spectrum -- it is the DMR beam times pixel window, with the
# dipole and (in most quotes) the quadrupole removed. A clean 10 deg Gaussian
# keeps more large-scale power and lands at ~39 muK. Both say the same physical
# thing -- large-angle anisotropy is a few tens of muK, i.e. ~1e-5 -- so this is
# gated as an order-of-magnitude band, not forced onto COBE's exact convention.
# NOTHING derived from this goes on screen; the on-screen ripple numbers are the
# full-resolution rms, which is what the map actually shown has.
check("large-angle rms in 20-60 muK band", rms_10deg, 40.0, tol_sigma=0.50, unit="muK")

peak1 = int(ell[150:300][np.argmax(Dl[150:300])])
peak1_Dl = float(Dl[peak1])
check("first acoustic peak l", peak1, 220.6, tol_sigma=0.02)
print(f"  D_l at first peak            {peak1_Dl:.0f} muK^2 (published ~5750)")
check("D_l first peak [muK^2]", peak1_Dl, 5750.0, tol_sigma=0.05, unit="muK^2")
peak1_deg = 180.0 / peak1
print(f"  first peak angular scale     {peak1_deg:.2f} deg  "
      f"(sound horizon theta_* = {theta_star_deg:.3f} deg)")

# =============================================== 7. SKY MAP REALISATION
import healpy as hp  # noqa: E402

NSIDE = 512
np.random.seed(20260727)
sky = hp.synfast(Cl, nside=NSIDE, lmax=min(lmax, 3 * NSIDE - 1), new=True, verbose=False) \
    if "verbose" in hp.synfast.__code__.co_varnames else \
    hp.synfast(Cl, nside=NSIDE, lmax=min(lmax, 3 * NSIDE - 1), new=True)
sky = np.asarray(sky, dtype=float)
print(f"\n== sky realisation ==")
print(f"  map rms                      {sky.std():.1f} muK "
      f"(theory {rms_uK:.1f}; a single realisation scatters)")
print(f"  map min/max                  {sky.min():.0f} / {sky.max():.0f} muK")

# A real experiment has a beam, and so must this map: at nside 512 the pixels are
# finer than the projected image, and bilinear interpolation on the healpix ring
# grid stamps visible arcs across the projection. Smoothing with a 10 arcmin
# Gaussian -- close to Planck's 143 GHz beam of 7.3 arcmin -- removes them and is
# the physically right thing to do rather than a cosmetic blur.
BEAM_ARCMIN = 10.0
_sm = dict(fwhm=np.radians(BEAM_ARCMIN / 60.0))
sky_disp = np.asarray(hp.smoothing(sky, **_sm), dtype=float)
print(f"  after {BEAM_ARCMIN:.0f}' beam            rms {sky_disp.std():.1f} muK, "
      f"min/max {sky_disp.min():.0f}/{sky_disp.max():.0f}  (this is what is displayed)")

# Equirectangular projection, for wrapping on a sphere the camera sits inside.
EW, EH = 4096, 2048
lon = np.linspace(-np.pi, np.pi, EW, endpoint=False)
lat = np.linspace(np.pi / 2, -np.pi / 2, EH)
LON, LAT = np.meshgrid(lon, lat)
theta = np.pi / 2 - LAT
phi = LON % (2 * np.pi)
grid = hp.get_interp_val(sky_disp, theta, phi)

# Divergent cold->hot ramp. Clipped at +/-300 muK, which is the range Planck's
# own published maps use, so hot/cold reads the same way as in the real figures.
CLIP = 300.0
STOPS = np.array([
    [0.02, 0.05, 0.28], [0.10, 0.32, 0.72], [0.42, 0.72, 0.93],
    [0.96, 0.96, 0.92], [0.99, 0.78, 0.36], [0.93, 0.36, 0.11], [0.55, 0.05, 0.05],
])
def ramp(v):
    """v in [-1,1] -> sRGB float triplet."""
    t = np.clip((v + 1) / 2, 0, 1) * (len(STOPS) - 1)
    i = np.clip(t.astype(int), 0, len(STOPS) - 2)
    f = (t - i)[..., None]
    return STOPS[i] * (1 - f) + STOPS[i + 1] * f

from PIL import Image  # noqa: E402
img = (np.clip(ramp(np.clip(grid / CLIP, -1, 1)), 0, 1) * 255).astype(np.uint8)
Image.fromarray(img).save(os.path.join(OUT, "sky_equirect.png"))

# Mollweide, for the "this is the whole sky" panel.
MW, MH = 2048, 1024
xs_m = (np.arange(MW) + 0.5) / MW * 4 - 2          # x in [-2,2]
ys_m = 1 - (np.arange(MH) + 0.5) / MH * 2          # y in [-1,1]
XM, YM = np.meshgrid(xs_m, ys_m)
inside = (XM**2 / 4 + YM**2) <= 1
with np.errstate(invalid="ignore"):
    gamma = np.arcsin(np.clip(YM, -1, 1))
    lat_m = np.arcsin(np.clip((2 * gamma + np.sin(2 * gamma)) / np.pi, -1, 1))
    lon_m = np.pi * XM / (2 * np.cos(gamma))
ok = inside & (np.abs(lon_m) <= np.pi)
th_m = np.pi / 2 - np.nan_to_num(lat_m)
ph_m = np.nan_to_num(lon_m) % (2 * np.pi)
gm = hp.get_interp_val(sky_disp, th_m, ph_m)
rgba = np.zeros((MH, MW, 4), dtype=np.uint8)
rgba[..., :3] = (np.clip(ramp(np.clip(gm / CLIP, -1, 1)), 0, 1) * 255).astype(np.uint8)
rgba[..., 3] = np.where(ok, 255, 0)
Image.fromarray(rgba, "RGBA").save(os.path.join(OUT, "sky_moll.png"))

# Downsampled, smoothed map -> seed positions for the structure beat.
# Sachs-Wolfe on large scales gives DeltaT/T = -Phi/3, so the COLD spots are the
# overdense ones. Seeds are placed at cold spots for that reason.
sky_sm = hp.smoothing(sky, fwhm=np.radians(2.0), verbose=False) \
    if "verbose" in hp.smoothing.__code__.co_varnames else \
    hp.smoothing(sky, fwhm=np.radians(2.0))
GW, GH = 128, 64
lon_g = np.linspace(-np.pi, np.pi, GW, endpoint=False)
lat_g = np.linspace(np.pi / 2 - np.pi / (2 * GH), -np.pi / 2 + np.pi / (2 * GH), GH)
LG, TG = np.meshgrid(lon_g, lat_g)
seedgrid = hp.get_interp_val(sky_sm, np.pi / 2 - TG, LG % (2 * np.pi))

# ============================================ 8. BLACKBODY COLOURS vs T
# CIE 1931 colour matching via the Wyman/Sloan/Shirley (2013) multi-lobe
# Gaussian fits -- an accurate published analytic approximation to the tables,
# used so the redshifting wave's colour is computed, not art-directed.
def _g(x, mu, s1, s2):
    s = np.where(x < mu, s1, s2)
    return np.exp(-0.5 * ((x - mu) / s) ** 2)

def cie_xyz_bar(lam_nm):
    x = (1.056 * _g(lam_nm, 599.8, 37.9, 31.0) + 0.362 * _g(lam_nm, 442.0, 16.0, 26.7)
         - 0.065 * _g(lam_nm, 501.1, 20.4, 26.2))
    y = 0.821 * _g(lam_nm, 568.8, 46.9, 40.5) + 0.286 * _g(lam_nm, 530.9, 16.3, 31.1)
    z = 1.217 * _g(lam_nm, 437.0, 11.8, 36.0) + 0.681 * _g(lam_nm, 459.0, 26.0, 13.8)
    return x, y, z

def planck_lam(lam_m, T):
    return (2 * h_P * c_l**2 / lam_m**5) / np.expm1(h_P * c_l / (lam_m * k_B * T))

XYZ2RGB = np.array([[3.2406, -1.5372, -0.4986],
                    [-0.9689, 1.8758, 0.0415],
                    [0.0557, -0.2040, 1.0570]])

lam_nm = np.linspace(360.0, 830.0, 471)
xb, yb, zb = cie_xyz_bar(lam_nm)
Ts = np.geomspace(3000.0, 400.0, 96)
cols, lums = [], []
Y_ref = None
for T in Ts:
    B = planck_lam(lam_nm * 1e-9, T)
    X, Y, Z = np.trapezoid(B * xb, lam_nm), np.trapezoid(B * yb, lam_nm), np.trapezoid(B * zb, lam_nm)
    if Y_ref is None:
        Y_ref = Y
    lums.append(float(Y / Y_ref))                 # luminance relative to 3000 K
    rgb = XYZ2RGB @ np.array([X, Y, Z])
    rgb = np.clip(rgb, 0, None)
    rgb = rgb / max(rgb.max(), 1e-30)             # chromaticity only; scale later
    srgb = np.where(rgb <= 0.0031308, 12.92 * rgb, 1.055 * rgb**(1 / 2.4) - 0.055)
    cols.append([float(v) for v in np.clip(srgb, 0, 1)])
print("\n== blackbody colour (computed, CIE 1931 via Wyman et al. 2013 fits) ==")
for T in (3000, 2000, 1500, 1000, 700):
    i = int(np.argmin(np.abs(Ts - T)))
    r, g, bl = cols[i]
    print(f"  {Ts[i]:7.0f} K  sRGB #{int(r*255):02x}{int(g*255):02x}{int(bl*255):02x}"
          f"   relative luminance {lums[i]:.3e}")

# ==================================================== 9. WRITE THE JSON
def thin(a, n):
    a = np.asarray(a, dtype=float)
    idx = np.linspace(0, len(a) - 1, n).astype(int)
    return [round(float(v), 6) for v in a[idx]]

lsel = np.unique(np.concatenate([np.arange(2, 60),
                                 np.round(np.geomspace(60, 2500, 260)).astype(int)]))
lsel = lsel[lsel <= lmax]

data = {
    "_source": "solve.py; CAMB from Planck 2018 VI base-LCDM inputs; CODATA constants",
    "cosmology": P18,
    "recomb": {
        "z_star": round(zstar, 2),
        "T_star_K": round(T_star, 1),
        "t_star_yr": round(t_star_yr),
        "t_star_kyr_round": 380,
        "rs_star_Mpc": round(rstar, 2),
        "theta_star_deg": round(theta_star_deg, 4),
        "chi_star_Gly": round(chi_star_Gly, 1),
        "travel_Gyr": round(travel_Gyr, 3),
        "xe_at_zstar": round(xe_star, 4),
        "dz_lss_fwhm": round(dz_lss),
        "z_drag": round(zdrag, 2),
        "z_eq": round(zeq),
    },
    "today": {
        "T0_K": T0, "T0_err_K": T0_err,
        "age_Gyr": round(age, 3),
        "nu_peak_GHz": round(nu_peak / 1e9, 2),
        "lam_peak_mm": round(lam_peak * 1e3, 4),
        "n_gamma_cm3": round(n_gamma / 1e6, 1),
        "peak_MJy_sr": round(float(I_T0_MJy.max()), 1),
        "firas_ppm": FIRAS_PPM,
    },
    "stretch": round(stretch, 2),
    "aniso": {
        "rms_uK": round(rms_uK, 1),
        "one_part_in": round(T0 / (rms_uK * 1e-6)),
        "rms_10deg_uK": round(rms_10deg, 1),
        "one_part_in_10deg": round(T0 / (rms_10deg * 1e-6)),
        "peak1_l": peak1,
        "peak1_Dl": round(peak1_Dl),
        "peak1_deg": round(peak1_deg, 3),
        "map_rms_uK": round(float(sky.std()), 1),
        "map_disp_rms_uK": round(float(sky_disp.std()), 1),
        "beam_arcmin": BEAM_ARCMIN,
        "clip_uK": CLIP,
    },
    "curves": {
        "bb_x": [round(float(v), 4) for v in xs],
        "bb_shape": [round(float(v), 5) for v in bb_shape],
        "nu_GHz": thin(nu_ax / 1e9, 240),
        "I_MJy": thin(I_T0_MJy, 240),
        "xe_z": thin(zg, 200), "xe": thin(xe, 200), "vis": thin(vis, 200),
        "cl_l": [int(v) for v in lsel],
        "cl_Dl": [round(float(Dl[v]), 1) for v in lsel],
        "bb_T": [round(float(v), 1) for v in Ts],
        "bb_rgb": [[round(v, 4) for v in c] for c in cols],
        "bb_lum": [float(f"{v:.4e}") for v in lums],
    },
    "seedgrid": {"w": GW, "h": GH,
                 "v": [round(float(v), 2) for v in (seedgrid / CLIP).ravel()]},
}
with open(os.path.join(OUT, "cmb.json"), "w") as f:
    json.dump(data, f, separators=(",", ":"))

print("\n== validation summary ==")
bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(f"  {'PASS' if ok else 'FAIL'}  {n}")
print(f"\n{len(checks)-len(bad)}/{len(checks)} checks passed"
      + ("" if not bad else f"   FAILED: {bad}"))
sz = os.path.getsize(os.path.join(OUT, 'cmb.json')) / 1024
print(f"wrote data/cmb.json ({sz:.0f} kB), data/sky_equirect.png, data/sky_moll.png")
