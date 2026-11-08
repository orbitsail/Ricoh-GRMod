# tools/re/fwread: static-reading helpers (AE study)

Small helpers used to read the stock AE and the exposure program (`docs/griv-re/exposure.md`). Read-only: they never patch anything. Set
`GRIV_RTOS` (tools/re/README.md); `capstone` is needed.

| file | purpose |
|---|---|
| `s.py` | wraps `../xr.py` (fstart, fend, callers, lits, movwt) and adds `refs`, `litsite_users` |
| `ann.py` | `dis(addr, n)`: disassembly with literal-pool values decoded as floats / strings; `name(addr, text)` keeps labels in `names.json` (cache, not committed) |
| `cg.py` | function starts and a call graph for 0x53640000..0x53690000 (cache `fstarts_ae.pkl`, not committed) |
| `getmap.py`, `pairs.py` | map getter / setter pairs: which settings-struct (P) offset feeds which AE-object (I) field. `python3 -I pairs.py LO HI` |
| `findstr.py`, `u16runs.py`, `u16range.py`, `u16any.py`, `ptrs.py`, `hexctx.py`, `scan_i.py` | UTF-16LE menu-string search, pointers to an address, hex context, uses of an I offset |
