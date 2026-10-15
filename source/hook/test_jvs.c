/* test_jvs.c - jvs.h on its own (check.ps1 builds and runs it; no game): the error mark switched off only on Sega's
 * exact bytes, and late answers dropped from a real named pipe.
 *   cl /nologo /W3 test_jvs.c && test_jvs.exe */
#include <stdio.h>
#include "jvs.h"

static int g_fail = 0, g_n = 0;
#define CHECK(c, what) do { g_n++; if (!(c)) { g_fail++; printf("FAILED: %s (line %d)\n", what, __LINE__); } } while (0)

int main(void)
{
    unsigned char a[4] = {0xC6, 0x46, 0x34, 0x01}, b[4] = {0xC6, 0x46, 0x34, 0x01};
    unsigned char odd[4] = {0xC6, 0x46, 0x30, 0x01}, keep[4] = {0xC6, 0x46, 0x34, 0x01};
    unsigned char stale[1500], answer[5] = {0xE0, 0x00, 0x03, 0x01, 0x04}, got[16];
    char name[64];
    HANDLE srv, cli;
    DWORD n = 0, avail = 0;
    int i;

    /* the error mark */
    CHECK(jvs_unlatch(a, b) == 1, "Sega's bytes: both marks switched off");
    CHECK(a[3] == 0 && b[3] == 0 && a[0] == 0xC6 && b[2] == 0x34, "... only the 4th byte of each changed");
    CHECK(jvs_unlatch(a, b) == 2, "a second time: already off, nothing changed");
    CHECK(jvs_unlatch(keep, odd) == 0, "one place not Sega's: refused");
    CHECK(keep[3] == 0x01 && odd[2] == 0x30 && odd[3] == 0x01, "... and neither place touched (never half)");

    /* late answers on a real pipe: the hook's side is the client, the board stand-in the server */
    sprintf(name, "\\\\.\\pipe\\wccf_test_jvs_%lu", GetCurrentProcessId());
    srv = CreateNamedPipeA(name, PIPE_ACCESS_DUPLEX, 0, 1, 4096, 4096, 0, NULL);
    cli = CreateFileA(name, GENERIC_READ | GENERIC_WRITE, 0, NULL, OPEN_EXISTING, 0, NULL);
    CHECK(srv != INVALID_HANDLE_VALUE && cli != INVALID_HANDLE_VALUE, "a test pipe");
    if (srv == INVALID_HANDLE_VALUE || cli == INVALID_HANDLE_VALUE)
        goto done;
    ConnectNamedPipe(srv, NULL);
    CHECK(jvs_drop(cli, ReadFile) == 0, "nothing waiting: nothing dropped");
    WriteFile(srv, answer, 5, &n, NULL);                /* an answer to a poll the game gave up on */
    WriteFile(srv, answer, 5, &n, NULL);
    CHECK(jvs_drop(cli, ReadFile) == 10, "two late answers: 10 bytes dropped");
    CHECK(PeekNamedPipe(cli, NULL, 0, NULL, &avail, NULL) && avail == 0, "... and the pipe is empty");
    for (i = 0; i < (int)sizeof stale; i++)
        stale[i] = (unsigned char)i;
    WriteFile(srv, stale, sizeof stale, &n, NULL);      /* a long stall's backlog: more than one read */
    CHECK(jvs_drop(cli, ReadFile) == sizeof stale, "a backlog of 1,500 bytes: all dropped");
    WriteFile(srv, answer, 5, &n, NULL);                /* the next request's own answer still arrives whole */
    n = 0;
    CHECK(ReadFile(cli, got, 5, &n, NULL) && n == 5 && memcmp(got, answer, 5) == 0, "the next answer: read as it is");
    CloseHandle(cli);
    CloseHandle(srv);
done:
    printf("jvs: %d of %d checks passed\n", g_n - g_fail, g_n);
    return g_fail ? 1 : 0;
}
