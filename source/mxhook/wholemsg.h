/*
 * wholemsg.h - whole messages for control_Release (2026-10-11). Pure C, no Windows calls: mxhook.c uses it inside
 * the server, test_wholemsg.c tests it on its own.
 *
 * What the cabinets send on TCP 20002 is a BATCH (docs: .work\research\control_crash\FRAMING.md, from the
 * disassembly): u32 record count, u32 total size INCLUDING these 8 bytes, then count records of a 16-byte id (text,
 * ended by a NUL unless all 16 are used), a u32 body size and the body. Little-endian.
 *
 * Sega's server reads a batch whole when it arrives whole, as it always did on the arcade's LAN. Over the internet
 * TCP may hand it over in pieces, and the server's code for stitching pieces together is broken: it loses its place
 * and crashes (control_Release+0x129C2 / the memcpy at +0x12A3D) - every player is cut. So the hook keeps the pieces
 * and gives the server only whole batches; the broken stitching code then never runs.
 *
 * Bytes that cannot be a batch never reach the server either: they are skipped up to the next place a batch can start.
 * Nobody is disconnected for them (Ali, 2026-10-11: no player is ever cut).
 */
#ifndef WHOLEMSG_H
#define WHOLEMSG_H

#define WM_MAX_BATCH 0x80000            /* the server's own receive buffer (FUN_00412140: recv(..., 0x80000, 0)) */
#define WM_HEAD      8
#define WM_REC       20                 /* 16-byte id + u32 body size */

static unsigned wm_u32(const unsigned char *p)
{
    return (unsigned)p[0] | (unsigned)p[1] << 8 | (unsigned)p[2] << 16 | (unsigned)p[3] << 24;
}

/* the batch at p, of which n bytes are here: its size when it is all here and adds up; 0 when what is here can be
 * the start of one (wait for the rest); -1 when it cannot be a batch */
static int wm_check(const unsigned char *p, unsigned n)
{
    unsigned count, total, off = WM_HEAD, i, j;
    if (n < WM_HEAD)
        return 0;
    count = wm_u32(p);
    total = wm_u32(p + 4);
    if (total < WM_HEAD || total > WM_MAX_BATCH || count > (total - WM_HEAD) / WM_REC)
        return -1;
    for (i = 0; i < count; i++) {
        unsigned body;
        if (off + WM_REC > n)
            return 0;                   /* that record's head is not here yet (it fits in total: checked above) */
        if (p[off] < 0x20)              /* an id is text: no empty id, no control characters before its end */
            return -1;
        for (j = 1; j < 16 && p[off + j]; j++)
            if (p[off + j] < 0x20)
                return -1;
        body = wm_u32(p + off + 16);
        if (body > total - off - WM_REC)
            return -1;                  /* a body that runs past the batch */
        off += WM_REC + body;
    }
    if (off != total)
        return -1;                      /* the records do not fill the batch exactly */
    return n >= total ? (int)total : 0;
}

/* whole batches at the start of p[0..n) that fit in room together: their size (> 0), or 0. *skip = bytes in front of
 * them that could not be a batch (skipped one at a time up to the next place a batch can start) */
static unsigned wm_whole(const unsigned char *p, unsigned n, unsigned room, unsigned *skip)
{
    unsigned s = 0, used = 0;
    int r;
    while (s < n && (r = wm_check(p + s, n - s)) < 0)
        s++;
    *skip = s;
    while (s + used < n && (r = wm_check(p + s + used, n - s - used)) > 0 && used + (unsigned)r <= room)
        used += (unsigned)r;
    return used;
}

#endif
