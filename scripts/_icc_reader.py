# -*- coding: utf-8 -*-
"""Stand-in for the player cabinet's Club Team Card reader (WCCF 2010-11), served over a named pipe.

    python .work/_icc_reader.py PIPE_NAME SECONDS [LOGFILE] [CARDFILE] [NEWCARDFILE]
    python .work/_icc_reader.py \\\\.\\pipe\\wccf_icc_seat1 6000 _icc_seat1_log.txt _card_seat1.bin _card_seat1.new.bin

The game opens "COM1" (client FUN_004d5820); the winmm hook, started with
MXHOOK_COM=COM1=\\\\.\\pipe\\wccf_icc_seat1, hands it this pipe instead. This file answers like the reader.

Link layer, read from the game's side (2026-10-04):
  - start-up probe: the game sends 02 and only needs ANY byte back within ~110 ms;
  - a command: game 02 -> reader 10; game sends the MESSAGE; reader 10 then 02; game 10; reader sends the
    REPLY; game sends one ack byte (any value);
  - MESSAGE (client FUN_004d8270): [cmd, cmd, len, data..., bcc], bcc = XOR of the bytes before it, every 10
    doubled, then 10 03. REPLY (client FUN_004d8540): [cmd, status, len, data..., bcc] in the same framing;
    status 0 = OK, the game copies the data from reply[3].
This version logs every command and answers as a reader WITH a card on it (Card below; the real "in/out" is the
I/O board's card sensor bit). The card lives in CARDFILE: every save writes a temp file, flushes it to the disk and
then replaces the card in one step, so a kill, a crash or a power cut can never leave a short card file; before the
first save of a session (no save for BACKUP_GAP s) the card on disk is copied into the backup folder beside it. A
card file of the wrong size is refused, not touched. Exit 0 after SECONDS, 2 when the pipe or the card file cannot
be used.

NEWCARDFILE (2026-10-08) gives the reader room for a second card, as Flycast's had: when the club card has expired
(its counter's low byte is 1 - the contract ended, or the card's life ran out) a blank card with its own id is put
beside it in NEWCARDFILE, and the game runs Sega's manager transfer (the manager goes to the new card, a new club is
made on it, the old card is marked used up: counter 0, its club left on it). At the next card check the old card is
off the reader and the new one plays; club_wallet.finish_transfer() swaps the two files at the next start. Which cards
lie on the reader is decided only at LoadKey, the start of the game's card check - never in the middle of a session.
Without NEWCARDFILE the reader holds one card, as before.
"""
import ctypes
import ctypes.wintypes as w
import os
import shutil
import sys
import time

CARD_BYTES = 16 + 256 * 16           # the card file: a 16-byte header + 256 blocks of 16 = 4,112 bytes
BACKUP_GAP = 60                      # no save for this many seconds = a new session: back the card up first
BACKUP_KEEP = 20                     # backups kept in backup\ (the newest)

STX, DLE, ETX = 0x02, 0x10, 0x03
NAMES = {0x41: "Request", 0x42: "Anticoll", 0x43: "Select", 0x45: "E?", 0x4C: "LoadKey", 0x4E: "RF Control",
         0x50: "Card Status", 0x52: "Read Blocks"}

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


def frame(payload):
    """payload + bcc, every 10 doubled, then 10 03."""
    bcc = 0
    for b in payload:
        bcc ^= b
    out = bytearray()
    for b in list(payload) + [bcc]:
        out.append(b)
        if b == DLE:
            out.append(DLE)
    return bytes(out) + bytes([DLE, ETX])


def unframe(raw):
    """Bytes of one framed message (up to and including 10 03) -> (payload incl. bcc, bytes used) or None."""
    out = bytearray()
    i = 0
    while i < len(raw):
        b = raw[i]
        if b == DLE:
            if i + 1 >= len(raw):
                return None
            if raw[i + 1] == DLE:
                out.append(DLE)
                i += 2
                continue
            if raw[i + 1] == ETX:
                return bytes(out), i + 2
        out.append(b)
        i += 1
    return None


class Card:
    """A Club Team Card's memory and state. Default: a FORMATTED BLANK card the game accepts as NEW
    (-> Club Make), per icc_protocol_notes.md section 4. 256 flat 16-byte blocks."""

    def __init__(self, path=None):
        self.uid = bytes([0xDE, 0xAD, 0xBE, 0xEF])
        self.status_type = 0x18                      # 'P' Card Status byte - anything but 0x20
        self.blocks = [bytearray(16) for _ in range(256)]
        self.blocks[0][:] = bytes([0xDE, 0xAD, 0xBE, 0xEF, 0x22, 0x18, 0x02, 0x00]) + bytes(8)
        self.blocks[4][:] = bytes(8) + bytes([0x95, 0x71, 0x66, 0x40]) + bytes(4)   # sig dword LE = 0x40667195
        self.blocks[6][:] = bytes(12) + bytes([0x00, 0x98, 0x96, 0x81])            # serial 10,000,001 big-endian
        self.counter = 0xFFFF                        # block 5 value; 0xFFFF = NEW card
        self.present = True
        self.halted = False
        self.path = path
        self.log = None                              # set by main(): reports backups and slow replaces
        self.last_save = 0.0
        if path and os.path.exists(path):
            self.load(path)

    @classmethod
    def blank(cls, path):
        """a fresh BLANK card with its own id, for a transfer: two cards with the kit's one UID could not be told
        apart (the game re-selects each card by UID).  Block 0 = UID + its check byte (the XOR of the four) + 18 02 00,
        as on the kit's card; its own serial, above the 10,000,000 the game requires."""
        c = cls()
        uid = bytes(c.uid)
        while uid == bytes(c.uid) or uid[0] == 0x88:   # 0x88 is MIFARE's cascade tag, never a UID's first byte
            uid = os.urandom(4)
        c.uid = uid
        c.blocks[0][:] = uid + bytes([uid[0] ^ uid[1] ^ uid[2] ^ uid[3], 0x18, 0x02, 0x00]) + bytes(8)
        c.blocks[6][12:16] = (10000002 + int.from_bytes(os.urandom(3), "big")).to_bytes(4, "big")
        c.path = path
        return c

    def load(self, path):
        with open(path, "rb") as f:
            raw = f.read()
        if len(raw) != CARD_BYTES:
            raise CardFileError("%s is %d bytes, a card file is %d - not loaded and not touched; restore it from %s"
                                % (path, len(raw), CARD_BYTES, os.path.join(os.path.dirname(os.path.abspath(path)),
                                                                            "backup")))
        self.uid = raw[:4]
        self.status_type = raw[4]
        self.counter = raw[5] | (raw[6] << 8)
        for i in range(256):
            self.blocks[i][:] = raw[16 + i * 16: 32 + i * 16].ljust(16, b"\x00")

    def image(self):
        out = bytearray(self.uid[:4].ljust(4, b"\x00"))
        out += bytes([self.status_type, self.counter & 0xFF, (self.counter >> 8) & 0xFF]) + bytes(9)
        for b in self.blocks:
            out += bytes(b)
        return bytes(out)

    def note(self, msg):
        if self.log:
            self.log(msg)

    def backup(self):
        """Copy the card file as it is on disk into backup\\ beside it; keep the newest BACKUP_KEEP."""
        if not (self.path and os.path.exists(self.path)):
            return None
        folder = os.path.join(os.path.dirname(os.path.abspath(self.path)), "backup")
        os.makedirs(folder, exist_ok=True)
        base = os.path.basename(self.path)
        dst = os.path.join(folder, "%s.%s.bak" % (base, time.strftime("%Y%m%d-%H%M%S")))
        shutil.copyfile(self.path, dst)
        old = sorted(f for f in os.listdir(folder) if f.startswith(base + ".") and f.endswith(".bak"))
        for f in old[:-BACKUP_KEEP]:
            os.remove(os.path.join(folder, f))
        return dst

    def save(self):
        """The whole card goes to CARDFILE.tmp, is flushed to the disk, then replaces CARDFILE in one step: a kill, a
        crash or a power cut at any moment leaves the old card or the new one, never a short file (writing CARDFILE in
        place could: a test killed the old way 150 times and found 83 empty files)."""
        if not self.path:
            return
        now = time.time()
        if now - self.last_save > BACKUP_GAP:
            try:
                kept = self.backup()
                if kept:
                    self.note("  card backed up -> %s" % kept)
            except OSError as e:
                self.note("  card backup FAILED (%s) - saving anyway" % e)
        self.last_save = now
        data = self.image()
        try:
            self.replace_with(data)
        except Exception as e:                       # never stop the reader over a save: the game is mid-session
            self.note("  safe save FAILED (%s) - writing the card in place this once" % e)
            try:
                with open(self.path, "wb") as f:
                    f.write(data)
            except Exception as e2:
                self.note("  card NOT SAVED (%s) - the reader still holds it in memory" % e2)

    def replace_with(self, data):
        tmp = self.path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())                     # on the disk before it replaces the card (a power cut)
        for attempt in range(50):
            try:
                os.replace(tmp, self.path)
                if attempt:
                    self.note("  card saved after %d refused replaces (the file was busy)" % attempt)
                return
            except PermissionError:                  # another program holds the card file for a moment
                time.sleep(0.02)
        raise OSError("the card file stayed busy for 1 s")


class CardFileError(Exception):
    pass


class Reader:
    """Answers one command (cmd, data) -> (status, reply_data). status 0 = OK. Implements the 12 commands
    the game uses (icc_protocol_notes.md section 2); block 4 writes MUST fail (a successful one = the game
    rejects the card). 'A' Request returns 0 when a card is present and not halted, 0x01 otherwise.
    The cards on the reader are `field`; `card` is the selected one, which every block command reads or writes.  As a
    real reader: Anticoll answers with the first card that is awake, a Halt puts the selected card to sleep, so the
    next Request reaches the other one, and RF Control wakes them all.  The game re-selects a card by comparing its UID
    and halting the wrong one (client FUN_004d6a90), so this order is all a second card needs."""

    def __init__(self, card, log, new_path=None):
        self.main, self.log, self.new_path = card, log, new_path
        self.second = None                           # the card beside it: a blank for a transfer, then the new club
        self.bad_new = False                         # NEWCARDFILE could not be loaded: never written over
        self.field = [card]
        self.card = card

    def lay_out(self):
        """which cards lie on the reader for the card check now starting (the class docstring of the module)"""
        if not self.new_path:
            return
        main, sec = self.main, self.second
        if sec is None and not self.bad_new and os.path.exists(self.new_path):
            try:
                sec = Card(self.new_path)
                sec.log = main.log
            except CardFileError as e:
                self.bad_new = True
                self.log("NEW CARD FILE REFUSED: %s - only the club card is on the reader" % e)
        low = main.counter & 0xFF
        if low == 0 and sec is not None and sec.counter == 0xFFFF:
            # Sega's order marks the old card used up (job 4) BEFORE it writes the new one: a cut in between leaves
            # the old club untouched on a "used up" card and a still-blank new one - set the old card back to expired
            # and the transfer simply runs again
            main.counter = 0xFF01
            main.save()
            self.log("  the last transfer was cut half way - the old card is expired again (0xFF01), it runs again")
            low = 1
        if low == 0 and sec is not None:
            field = [sec]                            # transfer done: the old card is off the reader
        elif low == 1 and not self.bad_new:
            if sec is None:
                sec = Card.blank(self.new_path)
                sec.log = main.log
                sec.save()
                self.log("  contract ended: a NEW blank card (id %s) is on the reader beside the club card - the game "
                         "moves the manager to it" % sec.uid.hex(" "))
            if sec.counter == 0xFFFF:
                field = [main, sec]
            else:
                field = [main]
                self.log("  %s is a written card, not a blank - not put beside the expired one" % self.new_path)
        else:
            field = [main]
        if [id(x) for x in field] != [id(x) for x in self.field]:
            self.log("  on the reader now: %s" % ", ".join("%s (counter 0x%04X)" % (x.uid.hex(" "), x.counter)
                                                          for x in field))
        self.second, self.field = sec, field
        if self.card not in field:
            self.card = field[0]

    def answer(self, cmd, data):
        c = self.card
        if cmd == 0x4E:                              # 'N' RF Control: wakes every card on the reader
            for x in self.field:
                x.halted = False
            return 0, b""
        if cmd == 0x4C:                              # 'L' LoadKey: accept any key - the game's card check starts here
            self.lay_out()
            return 0, b""
        if cmd == 0x41:                              # 'A' Request: is a card awake?
            return (0, b"") if any(x.present and not x.halted for x in self.field) else (0x01, b"")
        if cmd == 0x42:                              # 'B' Anticoll -> the first awake card's 4-byte UID
            awake = [x for x in self.field if x.present and not x.halted]
            return (0, bytes(awake[0].uid[:4])) if awake else (0x01, b"")
        if cmd == 0x43:                              # 'C' Select: the card with that UID
            for x in self.field:
                if bytes(x.uid[:4]) == bytes(data[:4]):
                    self.card = x
                    return 0, b""
            return 0x01, b""
        if cmd == 0x45:                              # 'E' Halt
            c.halted = True
            return 0, b""
        if cmd == 0x49:                              # 'I' Decrement block 5 by amount (data: 05 00 lo hi)
            amount = (data[2] | (data[3] << 8)) if len(data) >= 4 else 0
            c.counter = (c.counter - amount) & 0xFFFF
            if amount:
                self.log("  counter -%d -> 0x%04X" % (amount, c.counter))
                c.save()
            return 0, bytes([c.counter & 0xFF, (c.counter >> 8) & 0xFF, 0, 0])
        if cmd == 0x50:                              # 'P' Card Status -> type byte
            return 0, bytes([c.status_type])
        if cmd == 0x52:                              # 'R' Read Blocks: start LE16, count (always 0x0F)
            start, count = data[0] | (data[1] << 8), data[2]
            return 0, b"".join(bytes(c.blocks[(start + i) & 0xFF]) for i in range(count))
        if cmd == 0x54:                              # 'T' Read one block: block LE16
            return 0, bytes(c.blocks[(data[0] | (data[1] << 8)) & 0xFF])
        if cmd == 0x55:                              # 'U' Write one block: block LE16 + 16 bytes
            blk = (data[0] | (data[1] << 8)) & 0xFF
            if blk == 4:
                return 0x04, b""                     # block 4 is write-protected - MUST fail
            c.blocks[blk][:] = bytes(data[2:18]).ljust(16, b"\x00")
            c.save()
            return 0, b""
        if cmd == 0x53:                              # 'S' Write Blocks: start LE16, n, n*16 bytes
            start, n = data[0] | (data[1] << 8), data[2]
            for i in range(n):
                blk = (start + i) & 0xFF
                if blk != 4:
                    c.blocks[blk][:] = bytes(data[3 + i * 16: 19 + i * 16]).ljust(16, b"\x00")
            c.save()
            return 0, b""
        self.log("  (unknown command %02x - accepted)" % cmd)
        return 0, b""


def main(argv):
    if len(argv) < 2 or not argv[1].isdigit():
        print(__doc__)
        return 2
    pipe_name, seconds = argv[0], int(argv[1])
    logf = open(argv[2], "a", encoding="utf-8") if len(argv) > 2 else None
    cardfile = argv[3] if len(argv) > 3 else None
    newfile = argv[4] if len(argv) > 4 and cardfile else None
    t0 = time.time()

    def log(msg):
        line = "%8.3f  %s" % (time.time() - t0, msg)
        print(line, flush=True)
        if logf:
            logf.write(line + "\n")
            logf.flush()

    try:
        card = Card(cardfile)
    except CardFileError as e:
        log("CARD FILE REFUSED: %s" % e)
        return 2
    card.log = log
    h = k.CreateNamedPipeW(pipe_name, 3, 0, 1, 4096, 4096, 0, None)
    if not h or h == INVALID:
        log("cannot create pipe %s (err %d) - another reader running?" % (pipe_name, k.GetLastError()))
        return 2
    kind = "NEW (blank, counter 0xFFFF)" if card.counter == 0xFFFF else "existing (counter 0x%04X)" % card.counter
    log("card reader stand-in on %s for %d s; a card IS on the reader: %s%s%s" % (
        pipe_name, seconds, kind, (" <- %s" % cardfile) if cardfile else "",
        ("; room for a second card (a manager transfer) in %s" % newfile) if newfile else ""))
    reader = Reader(card, log, newfile)
    buf = (ctypes.c_char * 4096)()
    got = w.DWORD()

    def send(data, what):
        n = w.DWORD()
        k.WriteFile(h, data, len(data), ctypes.byref(n), None)
        log("  -> %-10s %s" % (what, data.hex(" ")))

    while time.time() - t0 < seconds:
        log("waiting for the game to open its COM port...")
        if not k.ConnectNamedPipe(h, None) and k.GetLastError() != ERROR_PIPE_CONNECTED:
            log("ConnectNamedPipe failed (err %d)" % k.GetLastError())
            time.sleep(1)
            continue
        log("game connected")
        state, raw, cmd_seen = "IDLE", bytearray(), None
        while time.time() - t0 < seconds:
            avail = w.DWORD()
            if not k.PeekNamedPipe(h, None, 0, None, ctypes.byref(avail), None):
                log("game closed the port")
                break
            if avail.value == 0:
                time.sleep(0.001)
                continue
            k.ReadFile(h, buf, min(avail.value, 4096), ctypes.byref(got), None)
            incoming = bytes(buf.raw[:got.value])
            log("<-  %s   (state %s)" % (incoming.hex(" "), state))
            for b in incoming:
                if state == "IDLE":
                    if b == STX:
                        send(bytes([DLE]), "DLE")
                        state, raw = "MSG", bytearray()
                    else:
                        log("  (ignored stray byte %02x)" % b)
                elif state == "MSG":
                    if not raw and b == STX:              # the game started over
                        send(bytes([DLE]), "DLE")
                        continue
                    raw.append(b)
                    got_msg = unframe(bytes(raw))
                    if got_msg:
                        payload = got_msg[0]
                        bcc = 0
                        for x in payload[:-1]:
                            bcc ^= x
                        cmd, length, data = payload[0], payload[2], payload[3:-1]
                        ok = "bcc ok" if bcc == payload[-1] else "BCC WRONG (want %02x)" % bcc
                        log("  CMD %02x %-11s len %d data [%s]  %s" % (cmd, NAMES.get(cmd, "?"), length, data.hex(" "), ok))
                        status, rdata = reader.answer(cmd, data)
                        cmd_seen = (cmd, status, rdata)
                        send(bytes([DLE, STX]), "DLE STX")
                        state = "WAIT_DLE"
                elif state == "WAIT_DLE":
                    if b == DLE:
                        cmd, status, rdata = cmd_seen
                        send(frame(bytes([cmd, status, len(rdata)]) + rdata), "REPLY st=%d" % status)
                        state = "WAIT_ACK"
                    elif b == STX:
                        send(bytes([DLE]), "DLE")
                        state, raw = "MSG", bytearray()
                elif state == "WAIT_ACK":
                    state = "IDLE"                         # any byte is the ack
        k.DisconnectNamedPipe(h)
    log("stopping after %d s" % seconds)
    k.CloseHandle(h)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
