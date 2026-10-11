# -*- coding: utf-8 -*-
"""Stand-in for the player cabinet's JVS I/O board (WCCF 2010-11), served over a named pipe.

    python .work/_jvs_board.py PIPE SECONDS [LOGFILE] [INPUTFILE]
    python .work/_jvs_board.py \\\\.\\pipe\\wccf_jvs_seat1 6000 _jvs_seat1_log.txt _jvs_seat1_input.txt

The game opens "\\\\.\\mxjvs" (client amJvstDriverSetup FUN_008398c0); the winmm hook started with
MXHOOK_COM=mxjvs=\\\\.\\pipe\\wccf_jvs_seat1 hands it this pipe (and drives the JVS sense line itself).

JVS framing: E0 (sync), node, length (= data bytes + 1), data..., checksum = (node + length + data) & FF.
After the sync byte, E0 and D0 are sent as D0 then (byte - 1). The game (master) sends to node FF
(broadcast) or to the board's address; the board answers to node 00: STATUS (1 = normal), then for each
command a REPORT (1 = normal) and its data.

INPUTFILE (default _jvs_seat1_input.txt beside this file) is re-read whenever it changes. Lines:
    sys=0x00          system switches (bit 7 = TEST)
    p1=0x00 0x00      player 1 switch bytes (bit 7 START, 6 SERVICE, 5 UP, 4 DOWN, 3 LEFT, 2 RIGHT,
    p2=0x00 0x00          1 BUTTON1, 0 BUTTON2; second byte: buttons 3..10 from bit 7 down)
    coin1=0           coin counters
    coin2=0
Unknown commands are logged and answered "unknown" (status 2). Exit 0 after SECONDS.
"""
import ctypes
import ctypes.wintypes as w
import os
import sys
import time

SYNC, MARK = 0xE0, 0xD0
BOARD_ID = b"SEGA ENTERPRISES,LTD.;I/O BD JVS;837-14572;Ver1.00;2005/10\x00"
FEATURES = bytes([0x01, 2, 13, 0,      # switch inputs: 2 players, 13 switches each
                  0x02, 2, 0, 0,       # coin inputs: 2 slots
                  0x03, 8, 10, 0,      # analog inputs: 8 channels, 10 bits
                  0x12, 20, 0, 0,      # general-purpose outputs: 20
                  0x00])
HERE = os.path.dirname(os.path.abspath(__file__))

k = ctypes.windll.kernel32
k.CreateNamedPipeW.restype = w.HANDLE
k.CreateNamedPipeW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, w.DWORD, w.DWORD, w.DWORD, w.DWORD, ctypes.c_void_p]
k.ConnectNamedPipe.argtypes = [w.HANDLE, ctypes.c_void_p]
k.DisconnectNamedPipe.argtypes = [w.HANDLE]
k.ReadFile.argtypes = [w.HANDLE, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD), ctypes.c_void_p]
k.WriteFile.argtypes = [w.HANDLE, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD), ctypes.c_void_p]
k.PeekNamedPipe.argtypes = [w.HANDLE, ctypes.c_void_p, w.DWORD, ctypes.c_void_p, ctypes.POINTER(w.DWORD), ctypes.c_void_p]
k.CloseHandle.argtypes = [w.HANDLE]
INVALID = w.HANDLE(-1).value
ERROR_PIPE_CONNECTED = 535


def escape(body):
    out = bytearray()
    for b in body:
        if b in (SYNC, MARK):
            out += bytes([MARK, b - 1])
        else:
            out.append(b)
    return bytes(out)


def packet(node, data):
    """SYNC + escaped(node, length, data, checksum)."""
    length = len(data) + 1
    total = (node + length + sum(data)) & 0xFF
    return bytes([SYNC]) + escape(bytes([node, length]) + bytes(data) + bytes([total]))


class Inputs:
    """The switch / coin state, from the input file (re-read when it changes)."""

    def __init__(self, path):
        self.path, self.stamp = path, None
        self.sys, self.p = 0, [[0, 0], [0, 0]]
        self.coin = [0, 0]

    def refresh(self, log):
        try:
            stamp = os.path.getmtime(self.path)
        except OSError:
            return
        if stamp == self.stamp:
            return
        try:
            with open(self.path, encoding="utf-8") as f:
                text = f.read()
        except OSError:
            # the file is being swapped whole (_keys_seat1.py writes it that way): read it on the next poll.
            # Unhandled, this PermissionError killed the board mid-game on 2026-10-04 (_jvs_refresh_race_test.py).
            return
        self.stamp = stamp
        for line in text.splitlines():
            line = line.split("#")[0].strip()
            if "=" not in line:
                continue
            key, val = [s.strip() for s in line.split("=", 1)]
            try:
                nums = [int(v, 0) for v in val.split()]
            except ValueError:
                continue
            if key == "sys" and nums:
                self.sys = nums[0] & 0xFF
            elif key in ("p1", "p2") and nums:
                self.p[int(key[1]) - 1] = [n & 0xFF for n in (nums + [0, 0])[:2]]
            elif key in ("coin1", "coin2") and nums:
                self.coin[int(key[4]) - 1] = nums[0] & 0x3FFF
        log("inputs now: sys=%02x p1=%02x %02x p2=%02x %02x coin=%d,%d" % (
            self.sys, self.p[0][0], self.p[0][1], self.p[1][0], self.p[1][1], self.coin[0], self.coin[1]))


def write_whole(path, text):
    """replace a small state file whole; a reader that hits the swap just reads it next time. Never fatal."""
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="ascii", newline="\n") as f:
            f.write(text)
        for _ in range(40):
            try:
                os.replace(tmp, path)
                return True
            except PermissionError:
                time.sleep(0.005)
    except OSError:
        pass
    return False


class Board:
    def __init__(self, inputs, log, outputs_path=None):
        self.addr, self.inputs, self.log, self.last = None, inputs, log, None
        # the game's general-purpose outputs (lamps, solenoids - e.g. the card ejector), from command 0x32.
        # Every change is logged and the latest bytes kept in outputs_path for other tools (2026-10-04).
        self.outputs, self.outputs_path, self.output_changes = None, outputs_path, 0

    def note_outputs(self, outs):
        if outs == self.outputs:
            return
        self.outputs = outs
        self.output_changes += 1
        self.log("outputs now: %s" % (outs.hex(" ") or "(none)"))
        if self.outputs_path:
            write_whole(self.outputs_path, "# the game's JVS outputs (command 0x32), latest; change %d\n%s\n"
                        % (self.output_changes, outs.hex(" ")))

    def handle(self, node, data):
        """One request packet -> the reply packet (or None)."""
        if node != 0xFF and node != self.addr:
            return None
        out, i, status = bytearray(), 0, 1
        while i < len(data):
            c = data[i]
            if c == 0xF0 and i + 1 < len(data):                 # reset
                self.addr = None
                self.log("  reset")
                return None
            if c == 0xF1 and i + 1 < len(data):                 # set address
                self.addr = data[i + 1]
                self.log("  address set to %d" % self.addr)
                out += b"\x01"
                i += 2
            elif c == 0x10:
                out += b"\x01" + BOARD_ID
                i += 1
            elif c == 0x11:
                out += b"\x01\x13"
                i += 1
            elif c == 0x12:
                out += b"\x01\x30"
                i += 1
            elif c == 0x13:
                out += b"\x01\x10"
                i += 1
            elif c == 0x14:
                out += b"\x01" + FEATURES
                i += 1
            elif c == 0x15:                                     # main board id: a text up to its NUL
                j = data.find(0, i + 1)
                j = len(data) if j < 0 else j + 1
                self.log("  main board says: %r" % bytes(data[i + 1:j]).rstrip(b"\x00"))
                out += b"\x01"
                i = j
            elif c == 0x20 and i + 2 < len(data):               # switches: players, bytes each
                players, nbytes = data[i + 1], data[i + 2]
                out += b"\x01" + bytes([self.inputs.sys])
                for pl in range(players):
                    sw = self.inputs.p[pl] if pl < 2 else [0, 0]
                    out += bytes((sw + [0] * nbytes)[:nbytes])
                i += 3
            elif c == 0x21 and i + 1 < len(data):               # coins: slots
                out += b"\x01"
                for s in range(data[i + 1]):
                    n = self.inputs.coin[s] if s < 2 else 0
                    out += bytes([(n >> 8) & 0x3F, n & 0xFF])
                i += 2
            elif c == 0x22 and i + 1 < len(data):               # analog: channels
                out += b"\x01" + bytes(2 * data[i + 1])
                i += 2
            elif c == 0x2F:                                     # retransmit
                return self.last
            elif c in (0x30, 0x31) and i + 3 < len(data):       # coin decrease / increase
                s, n = data[i + 1] - 1, (data[i + 2] << 8) | data[i + 3]
                if 0 <= s < 2:
                    self.inputs.coin[s] = max(0, self.inputs.coin[s] + (-n if c == 0x30 else n))
                out += b"\x01"
                i += 4
            elif c == 0x32 and i + 1 < len(data):               # general-purpose output: n bytes
                self.note_outputs(bytes(data[i + 2:i + 2 + data[i + 1]]))
                out += b"\x01"
                i += 2 + data[i + 1]
            elif c in (0x37, 0x38) and i + 1 < len(data):       # analog / character outputs
                out += b"\x01"
                i += 2 + (data[i + 1] if c == 0x38 else 0)
            else:
                self.log("  UNKNOWN command %02x (rest %s)" % (c, bytes(data[i:]).hex(" ")))
                status = 2
                break
        reply = packet(0x00, bytes([status]) + bytes(out))
        self.last = reply
        return reply


def main(argv):
    if len(argv) < 2 or not argv[1].isdigit():
        print(__doc__)
        return 2
    pipe_name, seconds = argv[0], int(argv[1])
    logf = open(argv[2], "a", encoding="utf-8") if len(argv) > 2 else None
    inpath = argv[3] if len(argv) > 3 else os.path.join(HERE, "_jvs_seat1_input.txt")
    if not os.path.isabs(inpath):
        inpath = os.path.join(HERE, inpath)
    t0 = time.time()
    quiet = {"polls": 0}

    def log(msg):
        line = "%8.3f  %s" % (time.time() - t0, msg)
        print(line, flush=True)
        if logf:
            logf.write(line + "\n")
            logf.flush()

    if not os.path.exists(inpath):
        with open(inpath, "w", encoding="utf-8") as f:
            f.write("# JVS inputs for the player cabinet - edit and save; read by _jvs_board.py\n"
                    "sys=0x00\np1=0x00 0x00\np2=0x00 0x00\ncoin1=0\ncoin2=0\n")
    inputs = Inputs(inpath)
    inputs.refresh(log)
    h = k.CreateNamedPipeW(pipe_name, 3, 0, 1, 4096, 4096, 0, None)
    if not h or h == INVALID:
        log("cannot create pipe %s (err %d) - another board running?" % (pipe_name, k.GetLastError()))
        return 2
    log("JVS I/O board stand-in on %s for %d s; inputs from %s" % (pipe_name, seconds, inpath))
    outpath = (inpath[:-len("_input.txt")] + "_outputs.txt") if inpath.endswith("_input.txt") else inpath + ".outputs"
    board = Board(inputs, log, outpath)
    buf = (ctypes.c_char * 4096)()
    got = w.DWORD()
    while time.time() - t0 < seconds:
        log("waiting for the game to open \\\\.\\mxjvs...")
        if not k.ConnectNamedPipe(h, None) and k.GetLastError() != ERROR_PIPE_CONNECTED:
            time.sleep(1)
            continue
        log("game connected")
        raw = bytearray()
        while time.time() - t0 < seconds:
            avail = w.DWORD()
            if not k.PeekNamedPipe(h, None, 0, None, ctypes.byref(avail), None):
                log("game closed the port")
                break
            if avail.value == 0:
                time.sleep(0.001)
                continue
            k.ReadFile(h, buf, min(avail.value, 4096), ctypes.byref(got), None)
            raw += buf.raw[:got.value]
            while True:                                         # take every complete packet
                s = raw.find(bytes([SYNC]))
                if s < 0:
                    raw.clear()
                    break
                del raw[:s]
                body, j, mark = bytearray(), 1, False
                while j < len(raw):
                    b = raw[j]
                    j += 1
                    if mark:
                        body.append(b + 1)
                        mark = False
                    elif b == MARK:
                        mark = True
                    elif b == SYNC:
                        break
                    else:
                        body.append(b)
                    if len(body) >= 2 and len(body) >= 2 + body[1]:
                        break
                if len(body) < 2 or len(body) < 2 + body[1]:
                    break                                       # wait for more bytes
                del raw[:j]
                node, length = body[0], body[1]
                data, total = bytes(body[2:1 + length]), body[1 + length]
                ok = ((node + length + sum(data)) & 0xFF) == total
                inputs.refresh(log)
                reply = board.handle(node, data)
                routine = data[:1] in (b"\x20", b"\x21") and ok
                if routine:
                    quiet["polls"] += 1
                    if quiet["polls"] % 600 == 1:
                        log("<- node %02x %s (input polls so far: %d)" % (node, data.hex(" "), quiet["polls"]))
                else:
                    log("<- node %02x %s%s" % (node, data.hex(" "), "" if ok else "  CHECKSUM WRONG"))
                if reply:
                    n = w.DWORD()
                    k.WriteFile(h, reply, len(reply), ctypes.byref(n), None)
                    if not routine:
                        log("-> %s" % reply.hex(" "))
        k.DisconnectNamedPipe(h)
    log("stopping after %d s" % seconds)
    k.CloseHandle(h)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
