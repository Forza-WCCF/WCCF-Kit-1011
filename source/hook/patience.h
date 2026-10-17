/* patience.h - the game's link to the server waits out an internet outage instead of ending in Error 3000
 * (2026-10-16), on its own so test_patience.c can run it without the game.
 *
 * GROPS's Error 3000 mid-match that day: his internet stopped for ~25-30 s and the link was cut. Measured on the kit
 * (.work/research/link_patience): three things give up on a quiet link, and all three are raised here.
 *  1. Windows: with no answer it stops resending after ~24 s (its own default). TCP_MAXRT on the game's link, both
 *     ends: PATIENCE_TCP_S. Windows resends at ~38 s and ~76 s after the outage starts; 100 keeps the 76 s one.
 *  2. The game: client_Release.exe raises Error 3000 when the server's CONTROL_STATE has not come for 30 s
 *     (0x004072F4: cmp ecx, 0x7530 - the time since it, stamped at +0x354 by FUN_00407a20), and drops the link.
 *  3. The server: control_Release.exe counts each seat's missed KEEP_ALIVE ticks (~3 s each), sends it TRUNCATION
 *     (which the game turns into Error 3000) at 11 and cuts it at 12 (0x0042CDB8 and 0x0042CE16:
 *     cmp dword [ecx+edi*4], 0x0b). Both become PATIENCE_SERVER_TICKS - 1, TRUNCATION still one tick before the cut.
 *  4. The projector (2026-10-17, the online projector through the server's relay): the same client_Release.exe has a
 *     second "30 s without CONTROL_STATE = Error 3000" in the projector's link loop (0x00600FCF: cmp eax, 0x7530 after
 *     sub eax, [ebp+0x74] - the time since it, stamped by the same loop at 0x00600E05). Raised to PATIENCE_GAME_MS too.
 * An outage of up to ~75 s: the link comes back where it was. Longer: cut as before, only later. A seat whose PC is
 * really gone is let go after ~2 min instead of ~36 s. */
#ifndef WCCF_PATIENCE_H
#define WCCF_PATIENCE_H
#include <string.h>

#ifndef TCP_MAXRT
#define TCP_MAXRT 5                     /* IPPROTO_TCP: seconds of resending before Windows gives up (ws2ipdef.h) */
#endif
#define PATIENCE_TCP_S         100
#define PATIENCE_GAME_MS       120000
#define PATIENCE_SERVER_TICKS  40

#define PAT_GAME_AT    0x004072F4u      /* client_Release.exe (Rev D) */
#define PAT_PROJECTOR_AT 0x00600FCCu    /* client_Release.exe (Rev D): sub eax, [ebp+0x74]; cmp eax, 0x7530; jbe */
#define PAT_SERVER_1   0x0042CDB8u      /* control_Release.exe (Rev D): TRUNCATION */
#define PAT_SERVER_2   0x0042CE16u      /*                              the cut */

/* 1 = raised now; 2 = it already was; 0 = not Sega's bytes - nothing changed */
static int patience_game(unsigned char *p)
{
    static const unsigned char sega[6] = {0x81, 0xF9, 0x30, 0x75, 0x00, 0x00};
    unsigned long ms = PATIENCE_GAME_MS;
    if (p[0] == 0x81 && p[1] == 0xF9 && memcmp(p + 2, &ms, 4) == 0)
        return 2;
    if (memcmp(p, sega, 6) != 0)
        return 0;
    memcpy(p + 2, &ms, 4);
    return 1;
}

/* the same answers for the projector's timer; the compare's neighbours checked too, the 5-byte compare alone is common */
static int patience_projector(unsigned char *p)
{
    static const unsigned char orig[9] = {0x2B, 0x45, 0x74, 0x3D, 0x30, 0x75, 0x00, 0x00, 0x76};
    unsigned long ms = PATIENCE_GAME_MS;
    if (memcmp(p, orig, 4) == 0 && memcmp(p + 4, &ms, 4) == 0 && p[8] == 0x76)
        return 2;
    if (memcmp(p, orig, 9) != 0)
        return 0;
    memcpy(p + 4, &ms, 4);
    return 1;
}

/* the same answers; both places or neither */
static int patience_server(unsigned char *a, unsigned char *b)
{
    static const unsigned char sega[4] = {0x83, 0x3C, 0xB9, 0x0B};
    unsigned char ours[4] = {0x83, 0x3C, 0xB9, PATIENCE_SERVER_TICKS - 1};
    if (memcmp(a, ours, 4) == 0 && memcmp(b, ours, 4) == 0)
        return 2;
    if (memcmp(a, sega, 4) != 0 || memcmp(b, sega, 4) != 0)
        return 0;
    a[3] = b[3] = PATIENCE_SERVER_TICKS - 1;
    return 1;
}
#endif
