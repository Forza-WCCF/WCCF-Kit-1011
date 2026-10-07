/* Stand-in for Sega's logowin.exe (WCCF 2010-11), written 2026-10-03.

   Sega's logowin.exe is the server's own screen. control_Release.exe starts it with the message on
   the command line - "logowin.exe error=SYS_NET_error_0014" for an error, or
   "logowin.exe warning=.. sega=.. allnet=.. mainid=.. keychipid=.." for the logo screen - and it
   opens a full-screen, white, ALWAYS-ON-TOP window. On the player's PC that covered his whole screen.

   This stand-in shows nothing. It appends the time, the starting process and its own command line
   to logowin_messages.txt in the current folder (control starts it in the game folder), then waits
   until the program that started it ends, as the real one stays up while control runs.
   Sega's original is kept beside it as logowin_sega.exe; to undo, rename them back. */
#include <windows.h>
#include <tlhelp32.h>
#include <stdio.h>

static DWORD parent_pid(void)
{
    DWORD me = GetCurrentProcessId(), parent = 0;
    PROCESSENTRY32 pe;
    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (snap == INVALID_HANDLE_VALUE)
        return 0;
    pe.dwSize = sizeof(pe);
    if (Process32First(snap, &pe)) {
        do {
            if (pe.th32ProcessID == me) {
                parent = pe.th32ParentProcessID;
                break;
            }
        } while (Process32Next(snap, &pe));
    }
    CloseHandle(snap);
    return parent;
}

int WINAPI WinMain(HINSTANCE inst, HINSTANCE prev, LPSTR cmd, int show)
{
    SYSTEMTIME t;
    FILE *f;
    DWORD ppid = parent_pid();
    HANDLE parent = ppid ? OpenProcess(SYNCHRONIZE, FALSE, ppid) : NULL;

    (void)inst; (void)prev; (void)cmd; (void)show;
    GetLocalTime(&t);
    f = fopen("logowin_messages.txt", "a");
    if (f) {
        fprintf(f, "%04d-%02d-%02d %02d:%02d:%02d  started by pid %lu  %s\n",
                t.wYear, t.wMonth, t.wDay, t.wHour, t.wMinute, t.wSecond,
                (unsigned long)ppid, GetCommandLineA());
        fclose(f);
    }
    if (parent) {
        WaitForSingleObject(parent, INFINITE);
        CloseHandle(parent);
    }
    return 0;
}
