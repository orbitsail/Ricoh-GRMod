"""FFCC-style learned illuminant estimation on GR IV AWB block statistics (own JAX implementation of the published
method: Barron & Tsai, "Fast Fourier Color Constancy", CVPR 2017).

Input per image: the camera's 64x62 block means (R, G, B, valid count) in GR IV statistics space, plus an exposure
term (Av + Tv - Sv) as metadata.  Output: illuminant chromaticity (R/G, B/G) in the same space.

Model: log-chroma histograms u = log(G/R), v = log(G/B) on an n x n torus (2 channels: block colours and local
colour contrast), convolved with learned filters (FFT), plus a learned bias map that depends on scene brightness;
softmax -> circular mean -> estimate.  Trained by minimising angular error with smoothness regularisers."""
import math
import numpy as np
import jax, jax.numpy as jnp
jax.config.update('jax_enable_x64', True)

N = 64                 # histogram bins per axis
H = 1.0 / 32           # bin width in log units (about 3 %)
U0, V0 = 0.0, -0.2     # lower corner of the (wrapped) histogram window
STAT_F = np.array([0.920, 1.0, 0.974])


def block_arrays(s):
    """s: (4, 64, 64) [R, G, B, D] with rows 1..62 used -> (62, 64, 3) float RGB, (62, 64) weight."""
    rgb = np.stack([s[0, 1:63], s[1, 1:63], s[2, 1:63]], -1).astype(np.float64)
    w = s[3, 1:63].astype(np.float64) / 1584.0
    ok = (w > 0.2) & (rgb.min(-1) >= 4) & (rgb.max(-1) <= 0xF6D)
    return rgb, np.where(ok, w, 0.0)


def histograms(s):
    """Two normalised (N, N) histograms: block colours, and local contrast (|block - mean of 3x3 neighbours|)."""
    rgb, w = block_arrays(s)
    eps = 1.0
    def hist(c, wt):
        u = np.log((c[..., 1] + eps) / (c[..., 0] + eps)); v = np.log((c[..., 1] + eps) / (c[..., 2] + eps))
        iu = np.floor((u - U0) / H).astype(np.int64) % N; iv = np.floor((v - V0) / H).astype(np.int64) % N
        h = np.zeros((N, N)); np.add.at(h, (iu.ravel(), iv.ravel()), wt.ravel())
        t = h.sum()
        return h / t if t > 0 else h
    h1 = hist(rgb, w)
    pad = np.pad(rgb, ((1, 1), (1, 1), (0, 0)), mode='edge'); wp = np.pad(w, 1, mode='constant')
    acc = np.zeros_like(rgb); cnt = np.zeros_like(w)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy == 0 and dx == 0: continue
            sl = (slice(1 + dy, 63 + dy), slice(1 + dx, 65 + dx))
            ww = wp[sl] > 0
            acc += pad[sl] * ww[..., None]; cnt += ww
    nb = acc / np.maximum(cnt, 1)[..., None]
    edge = np.abs(rgb - nb)
    we = np.where((w > 0) & (cnt > 0), edge.sum(-1), 0.0)
    h2 = hist(edge, we)
    return np.stack([h1, h2])


def chroma_to_uv(rg, bg):
    return np.log(1.0 / rg), np.log(1.0 / bg)


def uv_to_rgb(u, v):
    return jnp.stack([jnp.exp(-u), jnp.ones_like(u), jnp.exp(-v)], -1)


def meta_features(ev):
    """Scene brightness (Av + Tv - Sv, EV) -> features for the bias map: 1, centred EV, and a soft 'is it dim' term."""
    e = (ev - 4.0) / 4.0
    return jnp.stack([jnp.ones_like(e), e, jnp.tanh(2.0 * e)], -1)


def init_params(n_meta=3):
    return dict(F=jnp.zeros((2, N, N)), B=jnp.zeros((n_meta, N, N)))


def score_map(p, hists, feats):
    Ff = jnp.fft.fft2(p['F'])
    Hf = jnp.fft.fft2(hists)
    conv = jnp.real(jnp.fft.ifft2(Hf * Ff)).sum(0)
    bias = jnp.einsum('k,kij->ij', feats, p['B'])
    return conv + bias


def estimate_uv(p, hists, feats):
    """Circular mean of the softmax over the torus -> (u, v) of the illuminant (unwrapped near the window)."""
    s = score_map(p, hists, feats)
    P = jax.nn.softmax(s.ravel()).reshape(N, N)
    ang = 2 * jnp.pi * jnp.arange(N) / N
    pu = P.sum(1); pv = P.sum(0)
    mu = jnp.arctan2((pu * jnp.sin(ang)).sum(), (pu * jnp.cos(ang)).sum())
    mv = jnp.arctan2((pv * jnp.sin(ang)).sum(), (pv * jnp.cos(ang)).sum())
    iu = jnp.mod(mu, 2 * jnp.pi) / (2 * jnp.pi) * N; iv = jnp.mod(mv, 2 * jnp.pi) / (2 * jnp.pi) * N
    # bins hold the interval [k, k+1): centre at k + 0.5
    return U0 + (iu + 0.5) * H, V0 + (iv + 0.5) * H


def angular_error_deg(a, b):
    a = a / jnp.linalg.norm(a, axis=-1, keepdims=True); b = b / jnp.linalg.norm(b, axis=-1, keepdims=True)
    c = jnp.clip(jnp.sum(a * b, -1), -1 + 1e-12, 1 - 1e-12)
    return jnp.degrees(jnp.arccos(c))


def predict(p, H_, M_):
    return jax.vmap(lambda h, f: estimate_uv(p, h, f))(H_, M_)


def tv(x):
    return jnp.sum((x - jnp.roll(x, 1, -1)) ** 2) + jnp.sum((x - jnp.roll(x, 1, -2)) ** 2)


def loss_fn(p, H_, M_, U_, V_, lam_tv=1e-3, lam_l2=1e-5):
    u, v = predict(p, H_, M_)
    err = angular_error_deg(uv_to_rgb(u, v), uv_to_rgb(U_, V_))
    reg = lam_tv * (tv(p['F']) + tv(p['B'])) + lam_l2 * (jnp.sum(p['F'] ** 2) + jnp.sum(p['B'] ** 2))
    return jnp.mean(jnp.sqrt(err ** 2 + 0.25)) + reg


def train(H_, M_, U_, V_, steps=1500, lr=0.05, lam_tv=1e-3, lam_l2=1e-5, use_meta=True, seed=0, log=None):
    p = init_params(M_.shape[-1])
    if not use_meta:
        M_ = M_.at[:, 1:].set(0.0)
    vg = jax.jit(jax.value_and_grad(lambda q: loss_fn(q, H_, M_, U_, V_, lam_tv, lam_l2)))
    m = jax.tree_util.tree_map(jnp.zeros_like, p); v = jax.tree_util.tree_map(jnp.zeros_like, p)
    b1, b2 = 0.9, 0.999
    for t in range(1, steps + 1):
        L, g = vg(p)
        m = jax.tree_util.tree_map(lambda a, b: b1 * a + (1 - b1) * b, m, g)
        v = jax.tree_util.tree_map(lambda a, b: b2 * a + (1 - b2) * b * b, v, g)
        lr_t = lr * (0.1 ** (t / steps))
        p = jax.tree_util.tree_map(lambda q, a, b: q - lr_t * (a / (1 - b1 ** t)) / (jnp.sqrt(b / (1 - b2 ** t)) + 1e-8), p, m, v)
        if log and (t % 250 == 0 or t == 1):
            log(f'  step {t:5d} loss {float(L):.4f}')
    return p, M_


# ---------------------------------------------------------------- stable training: cross-entropy to a soft target first
def soft_target(U_, V_, sigma=1.0):
    """(n, N, N) wrapped Gaussian around the ground-truth bin (in bin units)."""
    cu = (U_ - U0) / H - 0.5; cv = (V_ - V0) / H - 0.5
    k = jnp.arange(N)
    du = jnp.mod(k[None, :] - cu[:, None] + N / 2, N) - N / 2
    dv = jnp.mod(k[None, :] - cv[:, None] + N / 2, N) - N / 2
    g = jnp.exp(-0.5 * (du[:, :, None] ** 2 + dv[:, None, :] ** 2) / sigma ** 2)
    return g / g.sum((1, 2), keepdims=True)


def ce_loss(p, H_, M_, T_, lam_tv, lam_l2):
    s = jax.vmap(lambda h, f: score_map(p, h, f))(H_, M_)
    logp = jax.nn.log_softmax(s.reshape(s.shape[0], -1), axis=-1).reshape(s.shape)
    ce = -jnp.sum(T_ * logp, axis=(1, 2)).mean()
    return ce + lam_tv * (tv(p['F']) + tv(p['B'])) + lam_l2 * (jnp.sum(p['F'] ** 2) + jnp.sum(p['B'] ** 2))


def _adam(vg, p, steps, lr, log=None, tag=''):
    m = jax.tree_util.tree_map(jnp.zeros_like, p); v = jax.tree_util.tree_map(jnp.zeros_like, p)
    b1, b2 = 0.9, 0.999
    for t in range(1, steps + 1):
        L, g = vg(p)
        m = jax.tree_util.tree_map(lambda a, b: b1 * a + (1 - b1) * b, m, g)
        v = jax.tree_util.tree_map(lambda a, b: b2 * a + (1 - b2) * b * b, v, g)
        lr_t = lr * (0.1 ** (t / steps))
        p = jax.tree_util.tree_map(lambda q, a, b: q - lr_t * (a / (1 - b1 ** t)) / (jnp.sqrt(b / (1 - b2 ** t)) + 1e-8), p, m, v)
        if log and (t % 500 == 0 or t == 1):
            log(f'  {tag} step {t:5d} loss {float(L):.4f}')
    return p


def train2(H_, M_, U_, V_, steps_ce=2000, steps_ang=500, lr_ce=0.05, lr_ang=0.005, lam_tv=1e-4, lam_l2=1e-6, use_meta=True, log=None):
    if not use_meta:
        M_ = M_.at[:, 1:].set(0.0)
    p = init_params(M_.shape[-1])
    T_ = soft_target(U_, V_)
    vg = jax.jit(jax.value_and_grad(lambda q: ce_loss(q, H_, M_, T_, lam_tv, lam_l2)))
    p = _adam(vg, p, steps_ce, lr_ce, log, 'ce')
    if steps_ang:
        vg2 = jax.jit(jax.value_and_grad(lambda q: loss_fn(q, H_, M_, U_, V_, lam_tv, lam_l2)))
        p = _adam(vg2, p, steps_ang, lr_ang, log, 'ang')
    return p, M_
