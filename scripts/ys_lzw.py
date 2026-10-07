# -*- coding: utf-8 -*-
"""YS ("YS\\x02\\x00") decompressor for WCCF 2010-11 wccf_data.xaf entries.

Ported from the game's own decompiler (yabukita::StreamAdapterLZW), not reversed blind:
  - client\\yabukita__StreamAdapterLZW__vfunction8  (the decompress read loop)
  - client\\FUN_0072cc10                            (decompress-mode init / constants)

Format (confirmed from the decompile):
  - 4-byte header 'Y' 'S' 0x02 0x00, then a variable-width LZW bitstream.
  - 256 single-byte root codes (0..255). First free code = 256.
  - Initial code width = 9 bits; grows up to 12 bits; dictionary max = 4096 codes.
  - MSB-first (big-endian) bit packing.
  - Width grows one code early (decoder leads the encoder by one entry): after a new
    code is assigned, if next_code + 1 == 2**width -> width += 1.
  - No clear/EOI code in the stream: when the dictionary is about to fill
    (next_code == max_codes - 1) it is reset (next_code -> 256, width -> 9) and the
    next code is read fresh (no entry added for it).
  - Decompresses to exactly `expected_size` bytes (known from the TOC).

The two subtle constants (EARLY_CHANGE, reset threshold) were validated against the
known-plaintext DDS header and against decoded-image quality on many cards.
"""

MAGIC = b"YS\x02\x00"
ROOT = 256
INIT_WIDTH = 9
MAX_WIDTH = 12
MAX_CODES = 4096


def decompress(data, expected_size, early_change=True, reset_at=MAX_CODES - 1):
    """Decompress a 'YS\\x02\\x00' LZW stream to exactly expected_size bytes.

    data          : the stored bytes of the archive entry (including the 4-byte magic).
    expected_size : uncompressed size from the TOC (the 'size' field).
    early_change  : True  -> width++ when next_code + 1 == 2**width (matches decompile).
                    False -> width++ when next_code     == 2**width (classic GIF).
    reset_at      : next_code value that triggers a dictionary reset (max_codes - 1).
    """
    if data[:4] != MAGIC:
        raise ValueError("not a YS\\x02\\x00 stream: %r" % (data[:4],))

    src = data
    n = len(src)
    pos = 4                      # byte cursor, past the 4-byte magic
    acc = 0                      # bit accumulator (MSB-first)
    nbits = 0                    # number of valid bits in acc

    out = bytearray(expected_size)
    oi = 0                       # output cursor

    # LZW dictionary as parallel arrays (linked-list of prefixes).
    prefix = [-1] * MAX_CODES    # prefix code (-1 for roots)
    char = bytearray(MAX_CODES)  # the byte appended by this code
    first = bytearray(MAX_CODES)  # first byte of this code's string (O(1))
    for i in range(ROOT):
        char[i] = i
        first[i] = i

    def read_code(width):
        nonlocal pos, acc, nbits
        while nbits < width:
            if pos >= n:
                return -1        # input exhausted
            acc = (acc << 8) | src[pos]
            pos += 1
            nbits += 8
        nbits -= width
        return (acc >> nbits) & ((1 << width) - 1)

    stack = bytearray(MAX_CODES + 16)

    def emit(code):
        """Write code's string to out[oi:], return new oi."""
        nonlocal oi
        sp = len(stack)
        c = code
        while c >= 0:
            sp -= 1
            stack[sp] = char[c]
            c = prefix[c]
        ln = len(stack) - sp
        out[oi:oi + ln] = stack[sp:]
        oi += ln
        return ln

    width = INIT_WIDTH
    next_code = ROOT
    need_restart = True          # True => next code read starts a fresh run (no entry added)
    prev_code = -1

    while oi < expected_size:
        code = read_code(width)
        if code < 0:
            break

        if need_restart:
            # First code of a run: must be an existing (root) code; emit directly.
            if code >= next_code:
                raise ValueError("bad first code %d >= %d" % (code, next_code))
            emit(code)
            prev_code = code
            need_restart = False
            continue

        if code < next_code:
            emit(code)
            new_first = first[code]
        elif code == next_code:
            # KwKwK special case: string(prev_code) + firstChar(prev_code)
            new_first = first[prev_code]
            emit(prev_code)
            out[oi] = new_first
            oi += 1
        else:
            raise ValueError("code %d > next_code %d (desync)" % (code, next_code))

        # Add a new dictionary entry: prev_string + firstChar(current)
        if next_code < MAX_CODES:
            prefix[next_code] = prev_code
            char[next_code] = new_first
            first[next_code] = first[prev_code]
            next_code += 1
            if early_change:
                if next_code + 1 == (1 << width) and width < MAX_WIDTH:
                    width += 1
            else:
                if next_code == (1 << width) and width < MAX_WIDTH:
                    width += 1

        prev_code = code

        # Dictionary (nearly) full -> reset, next run starts fresh.
        if next_code >= reset_at:
            next_code = ROOT
            width = INIT_WIDTH
            need_restart = True

    return bytes(out[:oi])
