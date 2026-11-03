# SPDX-License-Identifier: GPL-2.0-only
"""Memory safety of awbml.c when the scratch is corrupted at random points (as a second task using the same scratch would):
the module is built with ASan + bounds UBSan and the AWBML_FUZZ hooks; the result is not checked, only that nothing reads or
writes out of bounds. Usage: test_fuzz.py [path to an alternative awbml source dir] (default: this directory)."""
import ctypes
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

import ref
import scenes
import test_host as T

HERE = Path(__file__).resolve().parent
SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE


def main():
    tab, blob, offs = ref.build_tables()
    rng = np.random.default_rng(2024)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / 'libfuzz.so'
        subprocess.run(['gcc', '-Wall', '-DAWBML_HOST', '-DAWBML_FUZZ', '-shared', '-fPIC', '-O1', '-g', '-fsanitize=address,undefined',
                        '-fno-sanitize=signed-integer-overflow,shift', '-fno-sanitize-recover=undefined', str(SRC / 'host.c'),
                        '-o', str(out)], check=True, cwd=str(SRC))
        lib = T.load(out)
        legacy = SRC != HERE         # v7 source: host_run has no af89 / still / e30 arguments
        if legacy:
            lib.host_run.argtypes = lib.host_run.argtypes[:-3]
        lib.host_fuzz.argtypes = [ctypes.c_ulonglong, ctypes.c_uint]
        r = T.Runner(lib, blob, offs)
        cube, _ = scenes.load_cube()
        pool = [scenes.scene_args(cube[i]['s'], cube[i]['ev']) for i in rng.integers(0, len(cube), 30)]
        ncalls = nfz = 0
        for sq in range(int(os.environ.get('FUZZ_SEQ', 150))):
            lib.host_fuzz(int(rng.integers(1, 2 ** 62)), int(rng.choice([0, 20, 100, 300, 700, 1000])))
            first = True
            for step in range(int(rng.integers(6, 20))):
                if rng.random() < 0.7:
                    a = pool[int(rng.integers(0, len(pool)))]
                    arrs = [a[k] for k in ('R', 'Gr', 'Gb', 'B', 'cnt')]
                    p = {k: a[k] for k in ('x0', 'y0', 'w', 'h', 'stride', 'v24', 'e30', 'mode')}
                else:
                    arrs, p = T.gen_random(rng)
                p['mode'] = int(rng.choice([0] * 12 + [1]))
                mem, s_off, obj, _ = T.pack_case(*arrs, p['x0'], p['y0'], p['w'], p['h'], p['stride'], p['v24'], p['e30'], p['mode'], rng)
                still = int(rng.random() < 0.3)
                out_ = ctypes.create_string_buffer(T.OBJ_SIZE)
                args = (mem, len(mem), s_off, obj, out_, blob, len(blob), r.offs, 0, int(first), int(rng.choice([1, 4])))
                lib.host_run(*args) if legacy else lib.host_run(*args, int(rng.random() < 0.5), still, int(rng.random() < 0.5))
                first = False
                ncalls += 1
        print(f'fuzz: {ncalls} calls with random scratch corruption: no out-of-bounds access (ASan / bounds / UBSan clean)')


if __name__ == '__main__':
    main()
