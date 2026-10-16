/* test_patience.c - patience.h on its own (check.ps1 builds and runs it; no game): Sega's limits raised only on their
 * exact bytes and never half, and Windows takes the link's waiting time on a real socket.
 *   cl /nologo /W3 test_patience.c && test_patience.exe */
#include <stdio.h>
#include <windows.h>
#include "patience.h"
#pragma comment(lib, "ws2_32.lib")

static int g_fail = 0, g_n = 0;
#define CHECK(c, what) do { g_n++; if (!(c)) { g_fail++; printf("FAILED: %s (line %d)\n", what, __LINE__); } } while (0)

int main(void)
{
    unsigned char game[6] = {0x81, 0xF9, 0x30, 0x75, 0x00, 0x00}, odd[6] = {0x81, 0xF9, 0x31, 0x75, 0x00, 0x00};
    unsigned char a[4] = {0x83, 0x3C, 0xB9, 0x0B}, b[4] = {0x83, 0x3C, 0xB9, 0x0B};
    unsigned char keep[4] = {0x83, 0x3C, 0xB9, 0x0B}, other[4] = {0x83, 0x3C, 0xB8, 0x0B};
    unsigned long ms = 0;
    DWORD secs = 0;
    int len = sizeof(secs);
    WSADATA wd;
    SOCKET s;

    /* the game: 30 s -> PATIENCE_GAME_MS, the compare itself untouched */
    CHECK(patience_game(game) == 1, "the game's Sega bytes: raised");
    memcpy(&ms, game + 2, 4);
    CHECK(ms == PATIENCE_GAME_MS && game[0] == 0x81 && game[1] == 0xF9, "... to PATIENCE_GAME_MS, the compare kept");
    CHECK(patience_game(game) == 2, "a second time: already raised, nothing changed");
    CHECK(patience_game(odd) == 0 && odd[2] == 0x31, "another value: refused, untouched");

    /* the server: 11/12 -> PATIENCE_SERVER_TICKS - 1 at both places, or neither */
    CHECK(patience_server(a, b) == 1, "the server's Sega bytes: raised");
    CHECK(a[3] == PATIENCE_SERVER_TICKS - 1 && b[3] == PATIENCE_SERVER_TICKS - 1 && a[0] == 0x83 && b[2] == 0xB9,
          "... only the limit byte of each, TRUNCATION still one tick before the cut");
    CHECK(patience_server(a, b) == 2, "a second time: already raised");
    CHECK(patience_server(keep, other) == 0 && keep[3] == 0x0B && other[3] == 0x0B, "one place not Sega's: neither touched");
    CHECK(PATIENCE_SERVER_TICKS - 1 <= 0x7F, "the limit fits the compare's signed byte");

    /* Windows: the waiting time is taken, and read back the same */
    CHECK(WSAStartup(MAKEWORD(2, 2), &wd) == 0, "winsock");
    s = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    CHECK(s != INVALID_SOCKET, "a socket");
    if (s != INVALID_SOCKET) {
        DWORD want = PATIENCE_TCP_S;
        CHECK(setsockopt(s, IPPROTO_TCP, TCP_MAXRT, (const char *)&want, sizeof(want)) == 0, "TCP_MAXRT accepted");
        CHECK(getsockopt(s, IPPROTO_TCP, TCP_MAXRT, (char *)&secs, &len) == 0 && secs == PATIENCE_TCP_S,
              "... and read back as PATIENCE_TCP_S");
        closesocket(s);
    }
    WSACleanup();
    printf("patience: %d of %d checks passed\n", g_n - g_fail, g_n);
    return g_fail ? 1 : 0;
}
