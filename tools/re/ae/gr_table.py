# SPDX-License-Identifier: GPL-2.0-only
import os, sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sys, os, json, glob, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import features as F
mn = {r['name']: r for r in json.load(open('mnscan.json'))}
rows = []
for f in sorted(glob.glob('gr/*.npz')):
    z = np.load(f); m = json.loads(str(z['meta_json']))
    nm = m['name']; r = mn[nm]
    row = {'name': nm, 't': m['t'], 'N': m['N'], 'iso': m['iso'], 'ec': m['ec'], 'prog': m['prog'], 'metering': m['metering'],
           'be': m['baseline_exposure'], 'hc': r['hc'], 'lv_cam': r['lv'], 'orient': m['orient'], 'sw': r['sw'], 'model': r['model'],
           'date': m['date'], 'pm': r['pm'], 'isoauto': r['isoauto'], 'ael': r['ael']}
    row['ev100'] = math.log2(m['N'] ** 2 / m['t']) - math.log2(m['iso'] / 100.0)
    row.update(F.raw_features(z['raw_y'], z['blocks_clip']))
    row['disp'] = F.display_profile(z['jpg_y'])
    row['slope_Lstar_per_stop'] = F.exposure_per_stop_slope(z['jpg_y'])
    g = np.maximum(z['raw_g'].astype(np.float64), 2.0 ** -12)
    lg = np.log2(g)
    row['g_meanlog'] = float(lg.mean()); row['g_p50'] = float(np.percentile(lg, 50)); row['g_p99'] = float(np.percentile(lg, 99)); row['g_p999'] = float(np.percentile(lg, 99.9))
    rows.append(row)
json.dump(rows, open('gr_table.json', 'w'), indent=0)
print(len(rows))
print('%-11s %5s %4s %2s %5s | %6s %6s %6s %6s | %6s %6s %6s %5s' % ('name','iso','ec','hc','ev100','g_mlog','g_p50','g_p999','clip%','Lmean','Lp50','Lp99','sl'))
for r in rows:
    d = r['disp']
    print('%-11s %5d %4.1f %2d %5.1f | %6.2f %6.2f %6.2f %6.2f | %6.1f %6.1f %6.1f %5.1f' % (r['name'], r['iso'], r['ec'], r['hc'], r['ev100'], r['g_meanlog'], r['g_p50'], r['g_p999'], 100*r['lvl_clip_frac'], d['L_mean'], d['L_p50'], d['L_p99'], r['slope_Lstar_per_stop']))
