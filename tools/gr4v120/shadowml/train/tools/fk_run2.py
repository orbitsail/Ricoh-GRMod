"""Phase 2: add experts a,b,d,e to existing npz files in permutation order from #300.  usage: fk_run2.py <wall_s> [max_index]
403/429 -> stop (exit 3). STOP file stops. Disk < 2.2GB stops."""
import json, os, sys, time, shutil, subprocess, threading, tempfile, urllib.parse
import numpy as np
SP = __import__('os').environ.get('GRIV_WORK', '.')
R = SP + '/shadowml'; OUT = R + '/fivek'; DL = R + '/dl2'; TOOLS = R + '/tools'
os.makedirs(DL, exist_ok=True)
D = {}
for f in ['training', 'validation', 'testing']: D.update(json.load(open(f'{SP}/raw5k/meta/{f}.json')))
order = json.load(open(TOOLS + '/order.json'))
wall = float(sys.argv[1]); maxi = int(sys.argv[2]) if len(sys.argv) > 2 else len(order)
T0 = time.time(); deadline = T0 + wall
lock = threading.Lock(); st = dict(i=300, done=0, skipped=0, nonex=0, failed=0, refused=None, nb=0)
prog = open(R + '/progress2.log', 'a')
def log(m):
    with lock: prog.write(time.strftime('%H:%M:%S ') + m + '\n'); prog.flush()
for d in os.listdir(DL): shutil.rmtree(os.path.join(DL, d), ignore_errors=True)
class Refused(Exception): pass
def fetch(url, dest):
    url = urllib.parse.quote(url, safe=':/%'); last = ''
    for a in range(3):
        r = subprocess.run(['curl', '-sSL', '--connect-timeout', '20', '--max-time', '900', '-o', dest, '-w', '%{http_code}', url], capture_output=True, text=True)
        code = r.stdout.strip()[-3:]
        if r.returncode == 0 and code == '200': return os.path.getsize(dest)
        last = f'http={code} rc={r.returncode} {r.stderr.strip()[:100]}'
        if code in ('403', '429'): raise Refused(last + ' ' + url)
        if code == '404': break
        time.sleep(5 * (a + 1))
    raise RuntimeError(last)
def have(path):
    try:
        z = np.load(path, allow_pickle=False); m = json.loads(str(z['meta_json'])); return set(m['experts'])
    except Exception: return None
def work(i, name):
    p = f'{OUT}/{name}.npz'
    if not os.path.exists(p):
        with lock: st['nonex'] += 1
        return
    h = have(p)
    if h is None or set('abcde') <= h:
        with lock: st['skipped'] += 1
        return
    v = D[name]; d = tempfile.mkdtemp(dir=DL, prefix='im_'); args = []; t0 = time.time(); nb = 0
    try:
        for l in 'abde':
            if l in h: continue
            try:
                nb += fetch(v['urls']['tiff16'][l], f'{d}/{l}.tif'); args.append(f'{l}={d}/{l}.tif')
            except Refused: raise
            except Exception as e: args.append(f'{l}=FAILED:download {str(e)[:100]}')
        pr = subprocess.run(['python3', '-I', TOOLS + '/fk_addexp.py', p] + args, capture_output=True, text=True, timeout=900)
        res = json.loads(pr.stdout.strip().splitlines()[-1]) if pr.stdout.strip() else dict(ok=False, reason=pr.stderr[-300:])
        if not res['ok']: raise RuntimeError(res['reason'])
        with lock: st['done'] += 1; st['nb'] += nb
        log(f"OK {i} {name} {res['bytes']//1024}KB {res['flags']} {time.time()-t0:.1f}s")
    except Refused as e:
        with lock: st['refused'] = str(e)
        log('SERVER REFUSED ' + str(e))
    except Exception as e:
        with lock: st['failed'] += 1
        log(f'FAIL {i} {name} {str(e)[:200]}')
    finally: shutil.rmtree(d, ignore_errors=True)
def worker():
    while True:
        with lock:
            if st['refused'] or time.time() > deadline or os.path.exists(R + '/STOP') or st['i'] >= min(maxi, len(order)): return
            if shutil.disk_usage(R).free < 2.2e9: log('LOW DISK, stopping'); st['refused'] = 'low disk'; return
            i = st['i']; st['i'] += 1
        work(i, order[i])
log(f'START wall={wall} maxi={maxi}')
ths = [threading.Thread(target=worker) for _ in range(3)]
[t.start() for t in ths]; last = 0
while any(t.is_alive() for t in ths):
    time.sleep(20)
    if time.time() - last > 300: last = time.time(); log(f'PROGRESS idx={st["i"]} done={st["done"]} skipped={st["skipped"]} nonexistent={st["nonex"]} failed={st["failed"]} free={shutil.disk_usage(R).free/1e9:.1f}GB')
[t.join() for t in ths]
log(f'END idx={st["i"]} done={st["done"]} skipped={st["skipped"]} nonexistent={st["nonex"]} failed={st["failed"]} refused={st["refused"]}')
sys.exit(3 if st['refused'] else 0)
