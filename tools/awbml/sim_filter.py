# SPDX-License-Identifier: GPL-2.0-only
"""Behaviour of the temporal filter: frames of a daylight scene, a warm indoor scene, daylight again, then ambiguous
(low-confidence) frames; the output per call without smoothing (v7: every computing call's estimate, repeated between) and
with it (v8). Frames of a scene are the same shot with 20 % of the blocks dropped at random and 2 % noise, as a live view varies."""
import numpy as np

import ref
import scenes

import sys
T = ref.build_tables()[0]
if len(sys.argv) > 1:                              # try another R_conf (standard deviation, log units): python3 sim_filter.py 0.13
    T['KF'][3] = int(round(float(sys.argv[1]) ** 2 * 2 ** 32))
rng = np.random.default_rng(5)
studio = {s['name']: s for s in scenes.load_studio()}
cube, _ = scenes.load_cube()
gallery = {g['name']: g for g in scenes.load_gallery()}


def frame(sc):
    a = scenes.scene_args(sc['s'], sc['ev'])
    cnt = a['cnt'].copy()
    cnt[rng.random(cnt.shape) < 0.2] = 0
    out = dict(a, cnt=cnt)
    for k in ('R', 'Gr', 'B'):
        out[k] = np.clip((a[k] * (1 + 0.02 * rng.standard_normal(a[k].shape))).round(), 0, 4095).astype(np.int64)
    out['Gb'] = out['Gr']
    return out


def obs(f):
    return ref.observe(T, f['R'], f['Gr'], f['Gb'], f['B'], f['cnt'], f['x0'], f['y0'], f['w'], f['h'], f['stride'], f['v24'], f['e30'], 0)


# ambiguous scenes: the cube scenes with the widest uncertainty
amb = []
for i in range(0, len(cube), 6):
    o = obs(frame(cube[i]))
    if o: amb.append((max(o[2], o[3]), i))
amb = [cube[i] for _, i in sorted(amb, reverse=True)[:4]]
plan = [('daylight (day100)', studio['day100'], 12), ('warm indoor (low100)', studio['low100'], 14), ('daylight (day200)', studio['day200'], 12),
        ('ambiguous', None, 20), ('daylight (day100)', studio['day100'], 8)]
seq7 = None
state = None
left = 0
cached7 = cached8 = None
n = 0
print(f'{"call":>4} {"scene":22s} {"comp":4s} | {"v7 g0":>6s} {"g3":>6s} | {"v8 g0":>6s} {"g3":>6s} | {"z_u":>6s} {"z_v":>6s} {"sd_u":>6s} {"sd_v":>6s} (log units x 1000) | note')
for name, sc, cnt in plan:
    for k in range(cnt):
        s = sc if sc is not None else amb[(k // 2) % len(amb)]
        f = frame(s)
        n += 1
        comp = left == 0
        note = ''
        if comp:
            o = obs(f)
            if o is None:
                cached7 = cached8 = None; note = 'fallback'
            else:
                before = state
                state = ref.kalman(T, state, o[:2], o[2:])
                if before is not None and state['sg'] == list(o[2:]) and state['mu'] == list(o[:2]): note = 'scene change: reset'
                cached7 = (ref.exp_gain(T, 0, o[0]), ref.exp_gain(T, 1, o[1]))
                cached8 = (ref.exp_gain(T, 0, state['mu'][0]), ref.exp_gain(T, 1, state['mu'][1]))
                zu, zv, ru, rv = o
            left = ref.PERIOD - 1
        else:
            left -= 1
        g7 = cached7 or (0, 0); g8 = cached8 or (0, 0)
        if comp and o:
            print(f'{n:4d} {name:22s} {"C":4s} | {g7[0]:6d} {g7[1]:6d} | {g8[0]:6d} {g8[1]:6d} | {zu / 65.536:6.0f} {zv / 65.536:6.0f} {np.sqrt(ru / 2**32) * 1000:6.1f} {np.sqrt(rv / 2**32) * 1000:6.1f} | {note}')
        else:
            print(f'{n:4d} {name:22s} {"":4s} | {g7[0]:6d} {g7[1]:6d} | {g8[0]:6d} {g8[1]:6d} |')
