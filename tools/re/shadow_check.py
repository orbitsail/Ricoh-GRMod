from shadow_emu import *
import shadow_ref as R
e = new_emu(); rng = np.random.default_rng(11)
bad = 0; n = 0
for it in range(400):
    kind = rng.integers(0,4)
    if kind == 0: y = rng.integers(0, 4096, 64*62)
    elif kind == 1: y = (rng.gamma(2.0, rng.uniform(5, 600), 64*62)).astype(int) & 0xffff
    elif kind == 2: y = np.where(rng.random(64*62) < rng.uniform(0.5, 0.95), rng.integers(0, 40, 64*62), rng.integers(0, 3000, 64*62))
    else: y = rng.integers(rng.integers(0,200), 400, 64*62)
    s = int(rng.integers(0, 5)); hl = int(rng.integers(0, 2)); idx = int(rng.choice([8, 40, 70, 88, 90, 93, 96, 120, 143]))
    r = run(e, y, setting=s, hl=hl, idx44=idx)
    st, lv, info = R.strength(y, s, hl, idx)
    ok = (r['strength'] == st and r['level'] == lv)
    cnt_s = globals().setdefault('cnt_s', [0,0]); cnt_s[0]+=ok; cnt_s[1]+=1
    # curve table check (this+0x14)
    tab = np.frombuffer(bytes(e.mu.mem_read(THIS+0x14, 0x800)), dtype='<u2')
    tref = R.table(st, hl)
    rebuilt = not (st == 0 and hl == 0)
    ok2 = np.array_equal(tab, tref) if rebuilt else True
    n += 1
    if not (ok and ok2):
        bad += 1
        if bad < 8: print('MISMATCH', s, hl, idx, 'fw', r['strength'], r['level'], 'ref', st, lv, info, 'tab ok', ok2)
print('cases', n, 'mismatches', bad)

print('strength/level agree', cnt_s)
