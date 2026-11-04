"""My own minimal unicorn harness for the GR IV 1.11 RTOS (review of the final build; not derived from the projects' test_fw.py).

- image at 0x53000000, initialised data copied to 0x55000000 (0x57480 bytes from 0x5437B640), the rest of RAM zero
- operator new (0x538E09B0) and new[] (0x538E0A24): a bump allocator in 0x58000000.. that can be told to fail (return 0);
  every request is logged; delete / delete[] return at once
- __stack_chk_fail (0x53A786C0) and any unmapped access stop the run with an error
- call(): r0..r3 + stack args, r4..r11 set to sentinels and checked on return (AAPCS), sp checked to be balanced,
  stack below the entry sp poisoned so that the deepest use can be measured
"""
import struct
from unicorn import Uc, UcError, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_UNMAPPED, UC_HOOK_MEM_WRITE, UC_HOOK_MEM_READ
from unicorn.arm_const import *

BASE = 0x53000000
RAM_SRC, RAM_DST, RAM_LEN = 0x5437B640, 0x55000000, 0x57480
HEAP0, HEAP_LEN = 0x58000000, 0x01000000
OBJ0, OBJ_LEN = 0x60000000, 0x04000000
STK0, STK_LEN = 0x7E000000, 0x00200000
STACK_TOP = 0x7E1F0000
RET = 0x7E1FF000                       # return address (a nop is placed there)
NEW, NEW_ARR, DEL, DEL_ARR = 0x538E09B0, 0x538E0A24, 0x538E09EC, 0x538E0A60
STACK_CHK_FAIL = 0x53A786C0
POISON = 0xA5
REGS = [UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3]
CALLEE = [UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7, UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_R11]


class EmuError(Exception):
    pass


class Emu:
    def __init__(self, rtos_path):
        img = open(rtos_path, 'rb').read()
        self.img_len = len(img)
        mu = self.mu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        mu.mem_map(BASE, (len(img) + 0xFFFFF) & ~0xFFFFF)
        mu.mem_write(BASE, img)
        mu.mem_map(0x55000000, 0x01000000)
        mu.mem_write(RAM_DST, img[RAM_SRC - BASE:RAM_SRC - BASE + RAM_LEN])
        mu.mem_map(HEAP0, HEAP_LEN)
        mu.mem_map(OBJ0, OBJ_LEN)
        mu.mem_map(STK0, STK_LEN)
        mu.mem_write(RET, struct.pack('<I', 0xE320F000))      # nop
        mu.reg_write(UC_ARM_REG_C1_C0_2, mu.reg_read(UC_ARM_REG_C1_C0_2) | (0xF << 20))  # VFP access
        mu.reg_write(UC_ARM_REG_FPEXC, 0x40000000)
        self.heap = HEAP0
        self.allocs = []            # (size, pointer, caller lr)
        self.fail_alloc = False
        self.obj = OBJ0
        self.error = None
        for a in (NEW, NEW_ARR, DEL, DEL_ARR, STACK_CHK_FAIL):
            mu.hook_add(UC_HOOK_CODE, self._stub, begin=a, end=a)

        def unmapped(uc, access, addr, size, value, user):
            self.error = f'unmapped access type {access} at {addr:#x} size {size} pc {uc.reg_read(UC_ARM_REG_PC):#x} lr {uc.reg_read(UC_ARM_REG_LR):#x}'
            return False
        mu.hook_add(UC_HOOK_MEM_UNMAPPED, unmapped)

    def _stub(self, uc, addr, size, user):
        lr = uc.reg_read(UC_ARM_REG_LR)
        if addr in (NEW, NEW_ARR):
            n = uc.reg_read(UC_ARM_REG_R0)
            if self.fail_alloc:
                p = 0
            else:
                p = self.heap
                self.heap += (n + 15) & ~15
                uc.mem_write(p, bytes([0xCD]) * n)    # operator new does not clear: fill with garbage
            self.allocs.append((n, p, lr))
            uc.reg_write(UC_ARM_REG_R0, p)
        elif addr == STACK_CHK_FAIL:
            self.error = f'__stack_chk_fail from lr {lr:#x}'
            uc.emu_stop()
            return
        uc.reg_write(UC_ARM_REG_PC, lr)

    # memory helpers
    def alloc_obj(self, n, align=64):
        self.obj = (self.obj + align - 1) & ~(align - 1)
        p = self.obj
        self.obj += n
        self.mu.mem_write(p, bytes(n))
        return p

    def w32(self, a, v): self.mu.mem_write(a, struct.pack('<I', v & 0xFFFFFFFF))
    def w16(self, a, v): self.mu.mem_write(a, struct.pack('<H', v & 0xFFFF))
    def w8(self, a, v): self.mu.mem_write(a, bytes([v & 0xFF]))
    def r32(self, a): return struct.unpack('<I', bytes(self.mu.mem_read(a, 4)))[0]
    def r16(self, a): return struct.unpack('<H', bytes(self.mu.mem_read(a, 2)))[0]
    def r8(self, a): return self.mu.mem_read(a, 1)[0]
    def rb(self, a, n): return bytes(self.mu.mem_read(a, n))
    def wb(self, a, b): self.mu.mem_write(a, bytes(b))

    def call(self, fn, *args, stack=(), count=400_000_000, check_aapcs=True):
        mu = self.mu
        self.error = None
        for r, v in zip(REGS, args[:4]):
            mu.reg_write(r, v & 0xFFFFFFFF)
        extra = list(args[4:]) + list(stack)
        sp = STACK_TOP - 4 * len(extra)
        sp &= ~7
        for i, v in enumerate(extra):
            mu.mem_write(sp + 4 * i, struct.pack('<I', v & 0xFFFFFFFF))
        # poison 64 KB below the entry sp, to measure the deepest stack use
        mu.mem_write(sp - 0x10000, bytes([POISON]) * 0x10000)
        sentinels = [0x5EED0000 + 0x111 * k for k in range(8)]
        for r, v in zip(CALLEE, sentinels):
            mu.reg_write(r, v)
        mu.reg_write(UC_ARM_REG_SP, sp)
        mu.reg_write(UC_ARM_REG_LR, RET)
        mu.reg_write(UC_ARM_REG_CPSR, 0x13)   # SVC, ARM, flags clear
        try:
            mu.emu_start(fn, RET, count=count)
        except UcError as ex:
            raise EmuError(f'{ex} at pc {mu.reg_read(UC_ARM_REG_PC):#x}: {self.error}')
        if self.error:
            raise EmuError(self.error)
        if mu.reg_read(UC_ARM_REG_PC) != RET:
            raise EmuError(f'did not return (pc {mu.reg_read(UC_ARM_REG_PC):#x})')
        if mu.reg_read(UC_ARM_REG_SP) != sp:
            raise EmuError(f'sp not balanced: {mu.reg_read(UC_ARM_REG_SP):#x} != {sp:#x}')
        if check_aapcs:
            got = [mu.reg_read(r) for r in CALLEE]
            if got != sentinels:
                raise EmuError(f'callee-saved registers changed: {[hex(g) for g in got]}')
        low = self.rb(sp - 0x10000, 0x10000)
        used = 0
        for i in range(0x10000):
            if low[i] != POISON:
                used = 0x10000 - i
                break
        self.stack_used = used
        return mu.reg_read(UC_ARM_REG_R0)
