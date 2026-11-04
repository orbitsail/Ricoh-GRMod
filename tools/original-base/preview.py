"""preview_image: apply a fitted GR Mod slot to a Ricoh Standard JPEG (pixels are treated as Standard-rendered display colours),
a numpy port of slotApply in core/src/color/camera.ts. slot_json: path to {M1, ck, P2?} (or a dict).
    from preview import preview_image; preview_image('in.jpg', 'slot.json', 'out.jpg')"""
import json, os, re
import numpy as np
from PIL import Image

_HERE = os.path.dirname(os.path.abspath(__file__))
def _base_curve():
    txt = open(os.path.join(_HERE, '..', '..', 'core', 'src', 'color', 'data.ts')).read()
    body = re.search(r'BASE_CURVE = new Uint16Array\(\[(.*?)\]\)', txt, re.S).group(1)
    v = np.array([int(x) for x in re.findall(r'\d+', body)], float)
    assert len(v) == 256
    return v
_S_TAB = _base_curve() / 16383.0
_S_X = np.arange(256) / 256.0
_KN = np.linspace(0, 1, 17)

def slot_apply(slot, rgb):
    """rgb: (..., 3) float 0..1 sRGB-encoded Standard colours -> slot rendering. Same maths as camera.ts slotApply."""
    M = np.asarray(slot['M1'], float)
    x = np.clip(np.asarray(rgb, float), 0, 1)
    lin = np.interp(x, _S_TAB, _S_X)                       # S^-1
    lin = np.clip(lin @ M.T, 0, _S_X[-1])
    disp = np.interp(lin, _S_X, _S_TAB)                    # S
    out = np.stack([np.interp(disp[..., c], _KN, np.asarray(slot['ck'][c], float)) for c in range(3)], -1)
    out = np.clip(out, 0, 1)
    if slot.get('P2') is not None:
        out = np.clip(out @ np.asarray(slot['P2'], float).T, 0, 1)
    return out

def preview_image(jpg_in, slot_json, jpg_out, quality=95):
    slot = json.load(open(slot_json)) if isinstance(slot_json, (str, os.PathLike)) else slot_json
    if 'params' in slot: slot = slot['params']
    im = Image.open(jpg_in).convert('RGB')
    a = np.asarray(im, float) / 255.0
    out = slot_apply(slot, a)
    icc = im.info.get('icc_profile')
    Image.fromarray((out * 255 + 0.5).astype(np.uint8)).save(jpg_out, quality=quality, **({'icc_profile': icc} if icc else {}))

if __name__ == '__main__':
    import sys
    preview_image(sys.argv[1], sys.argv[2], sys.argv[3])
