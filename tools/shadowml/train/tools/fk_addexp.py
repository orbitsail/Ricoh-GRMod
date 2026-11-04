"""Add experts to an existing npz (no DNG).  usage: python3 -I fk_addexp.py <npz> <letter>=<tif|FAILED:reason> ...
Rewrites the npz atomically.  Same alignment checks as fk_proc, done against the stored raw side."""
import sys, os, json, time, traceback
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import numpy as np, cv2
import fk_proc as P, fk_common as C

def main():
    path = sys.argv[1]; args = dict(a.split('=', 1) for a in sys.argv[2:])
    z = np.load(path, allow_pickle=False); arrs = {k: z[k] for k in z.files}
    m = json.loads(str(arrs['meta_json'])); raw_y = C.dec_logy(arrs['raw_y']); Hr, Wr = raw_y.shape
    o = m['raw_side']['orient_used']; cw, ch = m['default_crop_size']
    summ = {}
    for l, p in sorted(args.items()):
        if p.startswith('FAILED:'):
            m['experts'][l] = dict(align_flag='failed', fail_reason=p[7:]); summ[l] = 'failed'; continue
        try:
            ey, note = P.expert_Y(p)
        except Exception as e:
            m['experts'][l] = dict(align_flag='failed', fail_reason='decode: ' + repr(e)[:200]); summ[l] = 'failed'; continue
        He, We = ey.shape
        info = dict(tif_size=[We, He], trc=note, orient_used=o, flag_notes=[])
        sm = abs(We - round(cw if o < 5 else ch)) <= 2 and abs(He - round(ch if o < 5 else cw)) <= 2
        info['size_match_default_crop'] = bool(sm)
        if sm:
            ea = P.rs(ey, Wr, Hr); ra = raw_y; rawcut = None
        else:
            sc, box = P.crop_search(P.logY(raw_y), ey)
            info['crop_search_score'] = sc; info['crop_box_frac'] = [round(v, 4) for v in box] if box else None
            Wn, Hn = (P.LONG, max(1, int(round(P.LONG * He / We)))) if We >= He else (max(1, int(round(P.LONG * We / He))), P.LONG)
            ea = P.rs(ey, Wn, Hn)
            if box:
                x0, y0, x1, y1 = box
                sub = raw_y[int(round(y0 * Hr)):max(int(round(y1 * Hr)), int(round(y0 * Hr)) + 1), int(round(x0 * Wr)):max(int(round(x1 * Wr)), int(round(x0 * Wr)) + 1)]
                ra = P.rs(sub, Wn, Hn)
            else: ra = P.rs(raw_y, Wn, Hn)
            rawcut = ra
        la, lb = P.logY(ra), P.logY(ea)
        rho = P.spearman(la, lb); pr = float(np.corrcoef(la.ravel(), lb.ravel())[0, 1])
        try:
            win = cv2.createHanningWindow((la.shape[1], la.shape[0]), cv2.CV_32F)
            ga = cv2.Laplacian(cv2.GaussianBlur(la, (0, 0), 1.0), cv2.CV_32F); gb = cv2.Laplacian(cv2.GaussianBlur(lb, (0, 0), 1.0), cv2.CV_32F)
            (sx, sy), resp = cv2.phaseCorrelate(ga, gb, win)
        except Exception: sx = sy = resp = float('nan')
        info.update(rho=rho, pearson_logY=pr, shift_px=[float(sx), float(sy)], shift_resp=float(resp), shape=list(ea.shape), added_later=True)
        if sm: flag = 'ok' if (rho >= 0.8 and abs(sx) <= 4 and abs(sy) <= 4) else 'poor'
        else: flag = 'crop' if (info.get('crop_search_score', 0) >= 0.85 and rho >= 0.8) else 'poor'
        info['align_flag'] = flag; m['experts'][l] = info; summ[l] = flag
        arrs['exp_' + l] = C.enc_logy(ea)
        if rawcut is not None: arrs['rawcut_' + l] = C.enc_logy(rawcut)
    arrs['meta_json'] = np.array(json.dumps(m, default=float))
    d = os.path.dirname(path); tmp = os.path.join(d, '.' + os.path.basename(path)[:-4] + '.add.npz')
    np.savez_compressed(tmp, **arrs); os.replace(tmp, path)
    return dict(ok=True, bytes=os.path.getsize(path), flags=summ)
try: r = main()
except Exception as e: r = dict(ok=False, reason='exception: ' + repr(e) + ' | ' + traceback.format_exc()[-300:])
print(json.dumps(r, default=float))
