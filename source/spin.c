/* not shipped: test_keeper.ps1's stand-in for a HUNG control: N threads that keep a CPU busy for S seconds, while
 * the main thread sleeps.  zz_spin.exe 2 40 = hung (two busy threads), zz_spin.exe 1 30 = healthy (one).
 * build.ps1 makes it as build\zz_spin.exe (the "zz_" name: no real program is ever mistaken for it). */
#include <windows.h>
#include <stdlib.h>

static DWORD WINAPI spin(LPVOID unused)
{
    volatile unsigned long long x = 0;
    (void)unused;
    for (;;)
        x++;
    return 0;
}

int main(int argc, char **argv)
{
    int n = argc > 1 ? atoi(argv[1]) : 2, s = argc > 2 ? atoi(argv[2]) : 20, i;
    for (i = 0; i < n; i++)
        CreateThread(NULL, 0, spin, NULL, 0, NULL);
    Sleep((DWORD)s * 1000);
    return 0;
}
