import json, os, sys, subprocess, shutil, time, threading, collections
from concurrent.futures import ThreadPoolExecutor
S = __import__('os').environ.get('GRIV_WORK', '.')
OUT = S + '/fivek_gr'; DL = S + '/fivek_dl'
D = {}
for f in ['training', 'validation', 'testing']:
    D.update(json.load(open(f'{S}/raw5k/meta/{f}.json')))
def tier(v):
    c = v['categories']
    if c['light'] in ('artificial', 'mixed') and c['location'] in ('indoor', 'unknown'): return 1
    if (c['location'], c['time'], c['light']) in (('indoor', 'day', 'mixed'), ('outdoor', 'night', 'artificial')): return 2
    return 0
def rr(names):
    g = collections.defaultdict(list)
    for n in sorted(names): g[D[n]['camera']['model']].append(n)
    keys = sorted(g, key=lambda k: -len(g[k])); out = []
    i = 0
    while any(g.values()):
        for k in keys:
            if g[k]: out.append(g[k].pop(0))
    return out
Q = {1: rr([n for n, v in D.items() if tier(v) == 1]), 2: rr([n for n, v in D.items() if tier(v) == 2])}
QUOTA = {1: 330, 2: 70}
print({k: len(v) for k, v in Q.items()}, flush=True)
lock = threading.Lock(); done = collections.Counter(); recs = []; skipped = []; nbytes = [0]; dltime = [0.0]
jl = open(OUT + '/progress.jsonl', 'a')
def work(args):
    t, n = args
    with lock:
        if done[t] >= QUOTA[t]: return
        done[t] += 1  # reserve; undone on failure
    v = D[n]; d = f'{DL}/{n}'; os.makedirs(d)  # new empty dir
    try:
        t0 = time.time()
        p = f'{d}/{n}.dng'
        r = subprocess.run(['curl', '-sSL', '--fail', '-o', p, v['urls']['dng']], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError('download failed: ' + r.stderr.strip()[:200])
        dt = time.time() - t0
        sz = os.path.getsize(p)
        pr = subprocess.run(['python3', '-I', S + '/fivek_tools/proc.py', p, n, json.dumps(v), OUT], capture_output=True, text=True)
        res = json.loads(pr.stdout.strip().splitlines()[-1]) if pr.stdout.strip() else dict(ok=False, reason='no output: ' + pr.stderr[-200:])
    except Exception as e:
        res = dict(ok=False, reason=repr(e)); sz = 0; dt = 0
    finally:
        shutil.rmtree(d, ignore_errors=True)
    with lock:
        if res['ok']:
            res['rec']['tier'] = t; recs.append(res['rec']); nbytes[0] += sz; dltime[0] += dt
            jl.write(json.dumps(res['rec']) + '\n'); jl.flush()
        else:
            done[t] -= 1
            skipped.append(dict(name=n, camera=v['camera']['model'], reason=res['reason']))
            print('SKIP', n, res['reason'][:150], flush=True)
        if len(recs) % 20 == 0: print(len(recs), dict(done), flush=True)
        if 'download failed' in res.get('reason', '') and ('403' in res['reason'] or '429' in res['reason']):
            print('SERVER REFUSED', res['reason'], flush=True); os._exit(3)
t0 = time.time()
for t in (1, 2):
    with ThreadPoolExecutor(2) as ex:
        list(ex.map(work, [(t, n) for n in Q[t]]))
wall = time.time() - t0
for r in recs: pass
recs.sort(key=lambda r: r['name'])
json.dump(recs, open(OUT + '/index.json', 'w'), indent=1)
json.dump(skipped, open(OUT + '/skipped.json', 'w'), indent=1)
json.dump(dict(wall_s=wall, bytes=nbytes[0], dl_s=dltime[0], n=len(recs), skipped=len(skipped)), open(OUT + '/run_stats.json', 'w'))
print('DONE', len(recs), len(skipped), wall, nbytes[0] / max(dltime[0], 1e-9) / 1e6, 'MB/s per-stream', flush=True)
