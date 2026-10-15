/* jvs.h - the I/O board's two guards (2026-10-15), on their own so test_jvs.c can run them without the game.
 *
 * "No input" (docs/research/NO-INPUT-2010-11.md): Sega's I/O library in client_Release.exe (FUN_007a61a0) marks the
 * board broken after 10 failed polls in a row, or 60 in a 600-poll window, and then never reads the buttons again in
 * that run - only the node's constructor clears the mark. Seen live: the board stand-in stalled 5 s, every press still
 * reached it, and the game ignored them all until the window was closed (a bad ending).
 *  1. jvs_unlatch: the two "mov byte [esi+0x34], 1" (c6 46 34 01) at 0x007A61DA and 0x007A61E6 write 0 instead, so
 *     failed polls can never switch the buttons off - the first good answer brings them back. Only when both places
 *     hold exactly Sega's bytes (anything else is left alone).
 *  2. jvs_drop: before the game sends a new request, any bytes still waiting on the board's pipe are answers to polls
 *     it gave up on; handed to the next poll they kept every press 90-140 ms late for the rest of a run (seen twice).
 *     They are read and dropped. */
#ifndef WCCF_JVS_H
#define WCCF_JVS_H
#include <windows.h>
#include <string.h>

#define JVS_MARK_1 0x007A61DAu        /* client_Release.exe (Rev D): the 60-in-a-window mark */
#define JVS_MARK_2 0x007A61E6u        /* the 10-in-a-row mark */

/* 1 = both marks switched off now; 2 = they already were; 0 = not Sega's bytes - nothing changed */
static int jvs_unlatch(unsigned char *a, unsigned char *b)
{
    static const unsigned char on[4] = {0xC6, 0x46, 0x34, 0x01}, off[4] = {0xC6, 0x46, 0x34, 0x00};
    if (memcmp(a, off, 4) == 0 && memcmp(b, off, 4) == 0)
        return 2;
    if (memcmp(a, on, 4) != 0 || memcmp(b, on, 4) != 0)
        return 0;
    a[3] = 0;
    b[3] = 0;
    return 1;
}

typedef BOOL (WINAPI *jvs_read_fn)(HANDLE, LPVOID, DWORD, LPDWORD, LPOVERLAPPED);

/* the bytes waiting on the pipe h, read with rd (the real ReadFile) and dropped; returns how many */
static DWORD jvs_drop(HANDLE h, jvs_read_fn rd)
{
    unsigned char junk[512];
    DWORD avail = 0, got, total = 0;
    while (PeekNamedPipe(h, NULL, 0, NULL, &avail, NULL) && avail > 0) {
        got = 0;
        if (!rd(h, junk, avail < sizeof junk ? avail : (DWORD)sizeof junk, &got, NULL) || got == 0)
            break;
        total += got;
    }
    return total;
}
#endif
