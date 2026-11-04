"""Aggregate stats over SP/shadowml/fivek/*.npz (reads only meta_json).  usage: python3 -I fk_stats.py"""
import os, json, sys, collections, numpy as np
R = (__import__('os').environ.get('GRIV_WORK', '.') + '/shadowml')
d = R + '/fivek'
files = sorted(f for f in os.listdir(d) if f.endswith('.npz') and not f.startswith('.'))
tot = sum(os.path.getsize(f'{d}/{f}') for f in files)
order = json.load(open(R + '/tools/order.json')); idx = {n: i for i, n in enumerate(order)}
fl = collections.Counter(); per_exp = collections.defaultdict(list); sz = []; cams = collections.Counter()
sizes5 = []; sizes1 = []; bad = []; trc = collections.Counter(); notes = collections.Counter(); aa_bad = 0; ymat = collections.Counter()
for f in files:
    z = np.load(f'{d}/{f}', allow_pickle=False)
    m = json.loads(str(z['meta_json']))
    cams[m['make'] + ' ' + m['model']] += 1; ymat[m['y_matrix_source']] += 1
    if not m['active_area_matches_libraw']: aa_bad += 1
    s = os.path.getsize(f'{d}/{f}'); (sizes5 if len(m['experts']) > 1 else sizes1).append(s)
    for l, e in m['experts'].items():
        fl[(l, e['align_flag'])] += 1
        if 'rho' not in e: bad.append((m['name'], l, e['align_flag'], e.get('fail_reason'))); continue
        per_exp[l].append((e['rho'], e['pearson_logY'], abs(e['shift_px'][0]), abs(e['shift_px'][1])))
        trc[e['trc']['trc']] += 1
        if not e['size_match_default_crop']: notes['size_mismatch'] += 1
        for n in e['flag_notes']: notes[n.split(' ')[0]] += 1
        if e['align_flag'] not in ('ok',): bad.append((m['name'], l, e['align_flag'], round(e['rho'], 3), e.get('crop_box_frac'), e['tif_size'], m['default_crop_size']))
print('files', len(files), 'total MB %.1f' % (tot / 1e6))
if sizes1: print('c-only files: n=%d mean %.0f KB max %.0f KB' % (len(sizes1), np.mean(sizes1) / 1e3, np.max(sizes1) / 1e3))
if sizes5: print('5-expert files: n=%d mean %.0f KB max %.0f KB' % (len(sizes5), np.mean(sizes5) / 1e3, np.max(sizes5) / 1e3))
print('flags by expert:', sorted(fl.items()))
for l in sorted(per_exp):
    a = np.array(per_exp[l]); print(f'expert {l}: n={len(a)} spearman logY median={np.median(a[:,0]):.4f} p5={np.percentile(a[:,0],5):.3f} min={a[:,0].min():.3f} | pearson logY median={np.median(a[:,1]):.3f} p5={np.percentile(a[:,1],5):.3f} | |shift| px median={np.median(a[:,2]):.2f},{np.median(a[:,3]):.2f} p95={np.percentile(a[:,2],95):.2f},{np.percentile(a[:,3],95):.2f}')
print('trc', dict(trc)); print('notes', dict(notes)); print('Y matrix', dict(ymat)); print('active-area mismatch with libraw', aa_bad)
print('cameras', cams.most_common())
print('non-ok (first 40):'); [print(' ', b) for b in bad[:40]]; print('non-ok total', len(bad))
if os.path.exists(R + '/failures.jsonl'):
    fs = [json.loads(l) for l in open(R + '/failures.jsonl')]
    done = set(f[:-4] for f in files)
    fs = [x for x in fs if x['name'] not in done]
    print('unresolved failures', len(fs)); c = collections.Counter(x['reason'][:90] for x in fs)
    for k, v in c.most_common(10): print(' ', v, k)
print('max index processed (by order)', max(idx[f[:-4]] for f in files))
