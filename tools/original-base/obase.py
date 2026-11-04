"""Original-base targets for GR Mod: render the scene-referred calibration colours through a camera-maker's
log -> look LUT (F-Log2 / LogC3), producing a 1026x3 display target for convert.ts `convertTarget`.

Assumption (also in README): the LUT's BT.709 output is used directly as GR Mod's display (sRGB-encoded) target,
no transfer-function conversion -- exactly how the existing photo-input .cube files treat their output.
"""
import json, os, subprocess, tempfile, shutil
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
SCENE_JSON = os.path.join(REPO, 'tools', 'scene-from-adobe', 'out', 'cal_scene.json')

# ---------------------------------------------------------------------------------- bridge
class Bridge:
    def __init__(self):
        esb = os.path.join(REPO, 'node_modules', '.bin', 'esbuild')
        self.tmp = tempfile.mkdtemp(prefix='obase_bridge_')
        self.js = os.path.join(self.tmp, 'bridge.mjs')
        subprocess.run([esb, os.path.join(HERE, 'bridge.ts'), '--bundle', '--platform=node', '--format=esm',
                        '--outfile=' + self.js, '--log-level=error'], check=True)
    def call(self, **req):
        r = subprocess.run(['node', self.js], input=json.dumps(req), capture_output=True, text=True, check=True)
        return json.loads(r.stdout)
    def cam(self):
        return np.array(self.call(op='cam')['cam']).reshape(-1, 3)
    def fit_target(self, target, title=''):
        return self.call(op='fitTarget', target=np.asarray(target).ravel().tolist(), title=title)
    def fit_cube(self, path, base='ricoh'):
        return self.call(op='fitCube', path=path, base=base)
    def fit_cube_text(self, text, base='ricoh'):
        return self.call(op='fitCubeText', text=text, base=base)
    def apply(self, params, rgb):
        rgb = np.asarray(rgb)
        return np.array(self.call(op='apply', params=params, rgb=rgb.ravel().tolist())['out']).reshape(-1, 3)
    def de2000(self, a, b):
        return np.array(self.call(op='de2000', a=np.asarray(a).ravel().tolist(), b=np.asarray(b).ravel().tolist())['d'])
    def close(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

# ---------------------------------------------------------------------------------- colour maths
M_PROPHOTO_TO_XYZ_D50 = np.array([[0.7976749, 0.1351917, 0.0313534],     # ROMM RGB / ProPhoto, ISO 22028-2
                                  [0.2880402, 0.7118741, 0.0000857],
                                  [0.0000000, 0.0000000, 0.8252100]])
D50 = np.array([0.96422, 1.0, 0.82521])
D65 = np.array([0.95047, 1.0, 1.08883])
BRADFORD = np.array([[0.8951, 0.2664, -0.1614], [-0.7502, 1.7135, 0.0367], [0.0389, -0.0685, 1.0296]])
def bradford(src, dst):
    s, d = BRADFORD @ src, BRADFORD @ dst
    return np.linalg.inv(BRADFORD) @ np.diag(d / s) @ BRADFORD
M_D50_TO_D65 = bradford(D50, D65)

def rgb_to_xyz_matrix(prim, white):
    """RGB->XYZ from xy primaries (3x2) and white XYZ."""
    xyz = np.array([[x / y, 1.0, (1 - x - y) / y] for x, y in prim]).T
    s = np.linalg.solve(xyz, white)
    return xyz * s
# ITU-R BT.2020 (= F-Gamut) primaries, D65 white.
M_BT2020_TO_XYZ = rgb_to_xyz_matrix([(0.708, 0.292), (0.170, 0.797), (0.131, 0.046)], D65)
# ARRI Wide Gamut 3 -> XYZ (D65), as published by ARRI ("ALEXA LogC Curve - Usage in VFX", 2017; ARRI Look File / colour-science `ALEXA_WIDE_GAMUT_RGB_TO_XYZ_MATRIX`).
M_AWG3_TO_XYZ = np.array([[0.638008, 0.214704, 0.097744],
                          [0.291954, 0.823841, -0.115795],
                          [0.002798, -0.067034, 1.153294]])

def srgb_to_lin(v):
    v = np.asarray(v, float)
    return np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)
M_SRGB_TO_XYZ = rgb_to_xyz_matrix([(0.64, 0.33), (0.30, 0.60), (0.15, 0.06)], D65)
def srgb_to_lab(rgb):
    xyz = srgb_to_lin(rgb) @ M_SRGB_TO_XYZ.T / D65
    f = np.where(xyz > 216 / 24389, np.cbrt(xyz), (24389 / 27 * xyz + 16) / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)

# ---------------------------------------------------------------------------------- log curves (scene linear, 0.18 = mid grey -> code 0..1)
def flog2_encode(x):
    """Fujifilm F-Log2 (F-Log2 Data Sheet Ver.1.0, Fujifilm; constants as in colour-science CONSTANTS_FLOG2).
    x >= cut1: y = c*log10(a*x + b) + d ; else y = e*x + f.  Input = scene-linear reflection (0.18 grey)."""
    a, b, c, d, e, f, cut1 = 5.555556, 0.064829, 0.245281, 0.384316, 8.799461, 0.092864, 0.000889
    x = np.asarray(x, float)
    return np.where(x >= cut1, c * np.log10(a * np.maximum(x, cut1) + b) + d, e * x + f)

def logc3_encode(x):
    """ARRI LogC3, EI 800 (ARRI "ALEXA LogC Curve - Usage in VFX", 2017-03; scene exposure factor method).
    x > cut: y = c*log10(a*x + b) + d ; else y = e*x + f."""
    cut, a, b, c, d, e, f = 0.010591, 5.555556, 0.052272, 0.247190, 0.385537, 5.367655, 0.092809
    x = np.asarray(x, float)
    return np.where(x > cut, c * np.log10(a * np.maximum(x, cut) + b) + d, e * x + f)

# ---------------------------------------------------------------------------------- scene -> encoded log RGB
def scene_to_gamut(scene_pp, k, family):
    """scene_pp: Nx3 linear ProPhoto D50. Returns linear RGB in the family's camera gamut (D65), scaled by k."""
    xyz50 = (np.asarray(scene_pp) * k) @ M_PROPHOTO_TO_XYZ_D50.T
    xyz65 = xyz50 @ M_D50_TO_D65.T
    m = M_BT2020_TO_XYZ if family == 'fuji' else M_AWG3_TO_XYZ
    return xyz65 @ np.linalg.inv(m).T

def encode(scene_pp, k, family):
    lin = scene_to_gamut(scene_pp, k, family)
    return (flog2_encode if family == 'fuji' else logc3_encode)(lin)

# ---------------------------------------------------------------------------------- .cube reading / lookup
class Cube:
    def __init__(self, path):
        n, vals = 0, []
        with open(path, encoding='utf-8-sig') as fh:
            for line in fh:
                line = line.split('#')[0].strip()
                if not line: continue
                t = line.split()
                if t[0] == 'LUT_3D_SIZE': n = int(t[1])
                elif t[0] in ('TITLE', 'DOMAIN_MIN', 'DOMAIN_MAX') :
                    if t[0] != 'TITLE': raise ValueError('domain not supported: ' + line)
                elif t[0] == 'LUT_1D_SIZE': raise ValueError('1D LUT not supported')
                else: vals.append([float(v) for v in t[:3]])
        self.n = n
        self.data = np.array(vals).reshape(n, n, n, 3)   # [b, g, r, c], red fastest in file

    def lookup(self, rgb):
        """Trilinear lookup; inputs clamped to 0..1. Returns (out unclamped, number of inputs that were clamped)."""
        rgb = np.asarray(rgb, float)
        t = np.clip(rgb, 0, 1) * (self.n - 1)
        i = np.minimum(np.floor(t).astype(int), self.n - 2)
        f = t - i
        out = 0
        for db in (0, 1):
            for dg in (0, 1):
                for dr in (0, 1):
                    w = (f[:, 2] if db else 1 - f[:, 2]) * (f[:, 1] if dg else 1 - f[:, 1]) * (f[:, 0] if dr else 1 - f[:, 0])
                    out = out + w[:, None] * self.data[i[:, 2] + db, i[:, 1] + dg, i[:, 0] + dr]
        return out

# ---------------------------------------------------------------------------------- scene data
def load_scene():
    return np.array(json.load(open(SCENE_JSON))['scene_linear_prophoto_d50']).reshape(-1, 3)

def render(scene_pp, k, family, cube):
    """Scene colours -> look LUT output, clipped to 0..1 (as GR Mod clips LUT output)."""
    enc = encode(scene_pp, k, family)
    return np.clip(cube.lookup(enc), 0, 1)

def fit_exposure(scene_pp, cam, provia):
    """1-D least squares in log k: PROVIA L* vs CAL_CAM L* on near-neutral (chroma<6, CAL_CAM L* 25..75) colours."""
    lc = srgb_to_lab(cam)
    chroma = np.hypot(lc[:, 1], lc[:, 2])
    sel = (chroma < 6) & (lc[:, 0] >= 25) & (lc[:, 0] <= 75)
    def resid(logk):
        out = render(scene_pp[sel], np.exp(logk), 'fuji', provia)
        return srgb_to_lab(out)[:, 0] - lc[sel, 0]
    from scipy.optimize import least_squares
    grid = np.linspace(np.log(1e-3), np.log(1e3), 241)
    g = grid[np.argmin([np.sum(resid(x) ** 2) for x in grid])]
    r = least_squares(resid, [g], diff_step=1e-4)
    rr = resid(r.x[0])
    return float(np.exp(r.x[0])), dict(n=int(sel.sum()), rms=float(np.sqrt(np.mean(rr ** 2))), mean=float(rr.mean()), max_abs=float(np.abs(rr).max()))

def _adobe(self): return np.array(self.call(op='adobe')['adobe']).reshape(-1, 3)
Bridge.adobe = _adobe
