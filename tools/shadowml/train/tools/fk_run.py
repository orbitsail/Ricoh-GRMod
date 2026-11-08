"""Driver: download -> process -> delete, <=3 parallel streams, resumable.
usage: python3 fk_run.py <wall_seconds>
Order: SP/shadowml/tools/order.json (default_rng(0) permutation of sorted names). First 300: experts a-e; rest: c only.
Stop early by creating SP/shadowml/STOP.  On HTTP 403/429: stop everything and exit 3."""
import json, os, sys, time, shutil, subprocess, threading, tempfile, urllib.parse
SP = __import__('os').environ.get('GRIV_WORK', '.')
R = SP + '/shadowml'; OUT = R + '/fivek'; DL = R + '/dl'; TOOLS = R + '/tools'
NFULL = 300; STREAMS = 3
os.makedirs(OUT, exist_ok=True); os.makedirs(DL, exist_ok=True)
D = {}
for f in ['training', 'validation', 'testing']: D.update(json.load(open(f'{SP}/raw5k/meta/{f}.json')))
order = json.load(open(TOOLS + '/order.json'))
wall = float(sys.argv[1]) if len(sys.argv) > 1 else 14400.0
T0 = time.time(); deadline = T0 + wall
lock = threading.Lock(); st = dict(i=0, done=0, skipped=0, failed=0, bytes_dl=0, refused=None)
prog = open(R + '/progress.log', 'a'); fails = open(R + '/failures.jsonl', 'a')
def log(msg):
    with lock:
        prog.write(time.strftime('%H:%M:%S ') + msg + '\n'); prog.flush()
# clean stale download dirs from a previous (killed) run -- ours only
for d in os.listdir(DL): shutil.rmtree(os.path.join(DL, d), ignore_errors=True)

class Refused(Exception): pass

def fetch(url, dest):
    url = urllib.parse.quote(url, safe=':/%')
    last = ''
    for attempt in range(3):
        r = subprocess.run(['curl', '-sSL', '--connect-timeout', '20', '--max-time', '900', '-o', dest, '-w', '%{http_code}', url], capture_output=True, text=True)
        code = r.stdout.strip()[-3:]
        if r.returncode == 0 and code == '200':
            return os.path.getsize(dest)
        last = f'http={code} rc={r.returncode} {r.stderr.strip()[:100]}'
        if code in ('403', '429'): raise Refused(last + ' ' + url)
        if code == '404': break
        time.sleep(5 * (attempt + 1))
    raise RuntimeError('download failed: ' + last + ' ' + url)

def work(i, name):
    out = f'{OUT}/{name}.npz'
    if os.path.exists(out):
        with lock: st['skipped'] += 1
        return
    v = D[name]; letters = 'abcde' if i < NFULL else 'c'
    d = tempfile.mkdtemp(dir=DL, prefix='im_')   # brand-new empty dir per image
    t0 = time.time(); nb = 0
    try:
        dng = d + '/in.dng'
        nb += fetch(v['urls']['dng'], dng)
        args = []; missing = []
        for l in letters:
            try:
                nb += fetch(v['urls']['tiff16'][l], f'{d}/{l}.tif'); args.append(f'{l}={d}/{l}.tif')
            except Refused: raise
            except Exception as e:
                if l == 'c': raise
                missing.append(l)
        dt = time.time() - t0
        pr = subprocess.run(['python3', '-I', TOOLS + '/fk_proc.py', dng, name, json.dumps(v), OUT] + args, capture_output=True, text=True, timeout=900)
        res = json.loads(pr.stdout.strip().splitlines()[-1]) if pr.stdout.strip() else dict(ok=False, reason='no output: ' + pr.stderr[-300:])
        if res['ok']:
            with lock: st['done'] += 1; st['bytes_dl'] += nb
            log(f"OK {i} {name} {res['bytes']//1024}KB flags={res['flags']} rho={res['rho']} dl={dt:.1f}s({nb/dt/1e6:.1f}MB/s) tot={time.time()-t0:.1f}s miss={missing} {res.get('notes') or ''}")
        else:
            raise RuntimeError(res['reason'])
    except Refused as e:
        with lock: st['refused'] = str(e)
        log('SERVER REFUSED ' + str(e))
    except Exception as e:
        with lock: st['failed'] += 1
        fails.write(json.dumps(dict(i=i, name=name, reason=str(e)[:600])) + '\n'); fails.flush()
        log(f'FAIL {i} {name} {str(e)[:200]}')
    finally:
        shutil.rmtree(d, ignore_errors=True)

def worker():
    while True:
        with lock:
            if st['refused'] or time.time() > deadline or os.path.exists(R + '/STOP') or st['i'] >= len(order): return
            if shutil.disk_usage(R).free < 2.2e9:
                log('LOW DISK, stopping'); st['refused'] = 'low disk'; return
            i = st['i']; st['i'] += 1
        work(i, order[i])

log(f'START wall={wall}s streams={STREAMS} existing={len(os.listdir(OUT))}')
ths = [threading.Thread(target=worker) for _ in range(STREAMS)]
for t in ths: t.start()
last = 0
while any(t.is_alive() for t in ths):
    time.sleep(30)
    if time.time() - last > 300:
        last = time.time(); log(f'PROGRESS idx={st["i"]} done={st["done"]} skipped={st["skipped"]} failed={st["failed"]} elapsed={time.time()-T0:.0f}s dl={st["bytes_dl"]/1e9:.2f}GB free={shutil.disk_usage(R).free/1e9:.1f}GB')
for t in ths: t.join()
log(f'END idx={st["i"]} done={st["done"]} skipped={st["skipped"]} failed={st["failed"]} elapsed={time.time()-T0:.0f}s refused={st["refused"]}')
sys.exit(3 if st['refused'] else 0)
