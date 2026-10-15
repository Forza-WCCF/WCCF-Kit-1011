# -*- coding: utf-8 -*-
"""test_io_board.py - the I/O board stand-in answers the game at once, whatever its disk does (2026-10-15, "no input":
docs/research/NO-INPUT-2010-11.md). The real io_board.main() on a real named pipe, this test in the game's place:
a write of the outputs file that hangs 2 s does not hold up one answer, a key press still reaches the answers, and an
answer held up with requests waiting is logged as SLOW (check.ps1 runs it; no game).
    python source\\test_io_board.py"""
import ctypes
import ctypes.wintypes as w
import os
import shutil
import sys
import tempfile
import threading
import time

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KIT, "code"))               # only code\, as the kit's python313._pth has it
from hardware import io_board as B  # noqa: E402

fails, n = [], 0
said = sys.stdout                       # the stand-in prints every log line too: those go nowhere, the checks here


def check(cond, what):
    global n
    n += 1
    if not cond:
        fails.append(what)
        print("FAILED: " + what, file=said, flush=True)


k = B.k
k.CreateFileW.restype = w.HANDLE
k.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, ctypes.c_void_p, w.DWORD, w.DWORD, w.HANDLE]

tmp = tempfile.mkdtemp(prefix="wccf-ioboard-")
inpath, logpath = os.path.join(tmp, "_jvs_test_input.txt"), os.path.join(tmp, "jvs_log.txt")
outpath = os.path.join(tmp, "_jvs_test_outputs.txt")         # io_board derives it from the input file's name
pipe = "\\\\.\\pipe\\wccf_test_ioboard_%d" % os.getpid()


def set_inputs(p1):
    """the key driver's way: the whole file replaced at once"""
    with open(inpath + ".tmp", "w", encoding="utf-8") as f:
        f.write("sys=0x00\np1=0x%02X 0x00\np2=0x00 0x00\ncoin1=3\ncoin2=0\n" % p1)
    os.replace(inpath + ".tmp", inpath)


sick = []
real_write = B.write_whole


def sick_disk(path, text):
    """the first write of the outputs file hangs 2 s - a disk (or a virus scan) stopping for a moment"""
    if not sick:
        sick.append(path)
        time.sleep(2.0)
    return real_write(path, text)


made = []


class Watched(B.Inputs):
    """io_board's own Inputs, kept where the test can hold its lock (as a stalled answering thread would be held)"""
    def __init__(self, path):
        super().__init__(path)
        made.append(self)


B.write_whole, B.Inputs = sick_disk, Watched
set_inputs(0x00)
sys.stdout = open(os.devnull, "w", encoding="utf-8")
ended = []
board = threading.Thread(target=lambda: ended.append(B.main([pipe, "6", logpath, inpath])), daemon=True)
board.start()                                               # 6 s, then it ends by itself - as play.py's LIFE does

h = None
for _ in range(500):
    h = k.CreateFileW(pipe, 0xC0000000, 0, None, 3, 0, None)       # read + write, open existing - as the hook does
    if h and h != B.INVALID:
        break
    time.sleep(0.01)
check(h and h != B.INVALID, "the test opens the stand-in's pipe, as the game does")
if not h or h == B.INVALID:
    print("io_board: %d of %d checks passed" % (n - len(fails), n), file=said)
    sys.exit(1)


def send(node, data):
    pkt = B.packet(node, bytes(data))
    put = w.DWORD()
    k.WriteFile(h, pkt, len(pkt), ctypes.byref(put), None)


def answer(timeout=3.0):
    """one whole answer packet, or None"""
    raw, buf, t = bytearray(), (ctypes.c_char * 512)(), time.time()
    while time.time() - t < timeout:
        body, mark = bytearray(), False
        for b in raw[1:]:
            if mark:
                body.append(b + 1)
                mark = False
            elif b == B.MARK:
                mark = True
            else:
                body.append(b)
        if len(body) >= 2 and len(body) >= 2 + body[1]:
            return bytes(raw)
        avail = w.DWORD()
        k.PeekNamedPipe(h, None, 0, None, ctypes.byref(avail), None)
        if avail.value:
            got = w.DWORD()
            k.ReadFile(h, buf, 1, ctypes.byref(got), None)  # byte by byte: never past this packet
            raw += buf.raw[:got.value]
        else:
            time.sleep(0.0005)
    return None


def poll(lamp, p1=0x00):
    """the game's poll: switches (2 players, 2 bytes), coins (2 slots), its 3 lamp bytes; and the answer it expects"""
    return ([0x20, 2, 2, 0x21, 2, 0x32, 3, lamp, 0x00, 0xE0],
            B.packet(0x00, bytes([1, 1, 0x00, p1, 0x00, 0x00, 0x00, 1, 0x00, 3, 0x00, 0x00, 1])))


# the game's start: reset (no answer), then the address
send(0xFF, [0xF0, 0xD9])
send(0xFF, [0xF1, 0x01])
check(answer() == B.packet(0x00, bytes([1, 1])), "set address: answered")

# 60 polls, every one with new lamps: each change is logged and written to the outputs file; the first write hangs 2 s
worst, right = 0.0, 0
for i in range(60):
    req, want = poll(i * 4 & 0xFC)
    t = time.time()
    send(0x01, req)
    got = answer()
    worst = max(worst, time.time() - t)
    right += got == want
    time.sleep(0.015)                                       # the game polls about every 15.6 ms
check(right == 60, "60 polls, 60 right answers (%d)" % right)
check(sick, "the outputs file's first write did hang (the test's sick disk)")
check(worst < 0.5, "while the disk hung 2 s, the slowest answer took %d ms (before: 2,000 or more)" % (worst * 1000))

# a key press while the disk may still be busy: START reaches the answers
set_inputs(0x80)
t, seen = time.time(), None
while time.time() - t < 2.0 and seen is None:
    req, want = poll(0xF0, p1=0x80)
    send(0x01, req)
    if answer() == want:
        seen = time.time() - t
    time.sleep(0.015)
check(seen is not None and seen < 0.5, "START pressed: in the answers after %s ms" % (
    "never" if seen is None else "%d" % (seen * 1000)))

# the answering thread held up 0.5 s while the game keeps asking: logged as SLOW, then every request answered
check(len(made) == 1, "the test can see the stand-in's input state")
with made[0].lock:
    for _ in range(5):
        send(0x01, poll(0xF0, p1=0x80)[0])
        time.sleep(0.1)
check(all(answer() == poll(0xF0, p1=0x80)[1] for _ in range(5)), "held up: all 5 requests answered afterwards")

text, t = "", time.time()
while time.time() - t < 8.0:                                # the writer catches up after its 2 s
    with open(logpath, encoding="utf-8") as f:
        text = f.read()
    if "requests were waiting" in text and "writing the outputs file took" in text:
        break
    time.sleep(0.1)
check("SLOW" in text and "requests were waiting" in text, "the held-up answers: a SLOW line with the requests waiting")
check("writing the outputs file took" in text and "no answer waited for it" in text, "the hung write: a SLOW line")
check(0 <= text.find("<- node ff f1 01") < text.find("-> e0 00 03 01 01 05"),
      "the log keeps its order: the request, then its answer")
check("high priority" in text, "the stand-in says its priority")
with open(outpath, encoding="ascii") as f:
    check(f.read().splitlines()[1] == "f0 00 e0", "the outputs file ends with the last lamps")

board.join(15)                                              # its time is up: it ends, and writes what it had queued
k.CloseHandle(h)
check(ended == [0], "the stand-in ends when its time is up")
with open(logpath, encoding="utf-8") as f:
    check(f.read().rstrip().endswith("stopping after 6 s"), "... and its last line is written before it ends")
shutil.rmtree(tmp, ignore_errors=True)
sys.stdout.close()
sys.stdout = said
print("io_board: %d of %d checks passed" % (n - len(fails), n))
sys.exit(1 if fails else 0)
