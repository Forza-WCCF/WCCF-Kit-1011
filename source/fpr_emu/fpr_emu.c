/* FPR_Emu.exe - stands in for Sega's card-table emulator, which the WCCF 2010-11 client expects but the disc
 * does not have (2026-10-04; protocol: .work/fpr_table.md, checked against the decompile).
 *
 * With FPR_MODE=2 the client (wccf::io::EmulatorFprInterface, FUN_004d2a40) runs
 *     ..\misc\FlatPanelReader_Emulator\exe\FPR_Emu.exe <table> <slots>      (table 0 or 1, slots 32)
 * from its own folder, with this process's stdout set to a pipe it reads.  It waits 2 s, then looks ONCE for a
 * visible, unowned window of this process (no retry), then polls about every 10 ms (vfunction2 @0x004d2c90):
 *     SendMessage(window, WM_USER+1)  ->  we write ONE frame to stdout  ->  it reads up to 4096 bytes.
 * Frame: "slot,card,x,y\r\n" for slots 1..16 (empty slot = "slot,-1,0,0"), then "-1,0,0,0\r\n" = commit.
 *   - Never more than 16 slot lines: the game counts them and warns "max 16 players" above that (see SLOTS_SENT).
 *   - CR LF ends a line; the game copies each field into an 8-byte slot with NO bound: fields <= 7 characters.
 *   - A commit does not clear the other buffer, so every slot is written every frame.
 *   - Never "-2": it ends the game's reader thread for good.
 * WM_USER+2 = the game is closing -> exit.  Also exits when the game process ends or the pipe breaks.
 *
 * Cards: "fpr_table<N>.txt" in the current folder = the game's folder (seat1\ for seat 1; the projector runs from
 * another folder, finds no file and gets empty tables).  Lines "slot card x y" (commas or spaces, # comments),
 * slot 1..16, x/y in the table's units (pitch about -1..+1, bench x > 1.16).  Re-read when its write time
 * changes; a read that fails (file being swapped) keeps the last good table.  Table 1 is always sent empty.
 * Nothing but frames ever goes to stdout: a log goes to fpr_emu_table<N>.log in the same folder.
 */
#include <windows.h>
#include <tlhelp32.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define WM_FPR_POLL  (WM_USER + 1)
#define WM_FPR_CLOSE (WM_USER + 2)
/* 16, not 20 (2026-10-05): the game counts the slot lines of each frame - empty "s,-1,0,0" lines too - into the table
 * interface's +0x138, and FUN_004ed890 (cmp [table0+0x138],0x10 / ja) raises 「1チームに登録できるのは16人までです」 above
 * 16, which blocks the decide button on card arrangement, the Club Make card step and team practice.  With 20 lines it
 * was on whatever cards lay on the table.  The game reads slots 1-20; 17-20, never sent, stay at their empty start
 * value.  The board, the catalogue and fpr_panel.py use slots 1-16 only.  (.work\wccfpanel\REGISTER16.md) */
#define SLOTS_SENT   16
#define LOG_EVERY    6000           /* polls between "still polling" log lines (about a minute) */

typedef struct { int used; int card; float x, y; } entry_t;

static int      g_table = 0;
static HANDLE   g_out = INVALID_HANDLE_VALUE;
static char     g_path[MAX_PATH];
static FILETIME g_stamp;
static int      g_have_stamp = 0;
static entry_t  g_entries[SLOTS_SENT + 1];
static int      g_cards = 0;
static long     g_polls = 0;
static HANDLE   g_parent = NULL;
static FILE    *g_log = NULL;

static void logf_(const char *fmt, ...)
{
    va_list ap;
    SYSTEMTIME t;
    if (!g_log)
        return;
    GetLocalTime(&t);
    fprintf(g_log, "%02d:%02d:%02d.%03d  ", t.wHour, t.wMinute, t.wSecond, t.wMilliseconds);
    va_start(ap, fmt);
    vfprintf(g_log, fmt, ap);
    va_end(ap);
    fputc('\n', g_log);
    fflush(g_log);
}

static float clampf(float v)
{
    if (!(v == v))                   /* NaN */
        return 0.0f;
    if (v > 9.99f)
        return 9.99f;
    if (v < -9.99f)
        return -9.99f;
    return v;                        /* "%.3f" of this is at most 6 characters */
}

/* Re-read the table file if it changed.  On any failure keep what we had: the panel swaps the file whole. */
static void load_table(void)
{
    WIN32_FILE_ATTRIBUTE_DATA a;
    entry_t fresh[SLOTS_SENT + 1];
    char line[256];
    FILE *f;
    int n = 0, s;

    if (!GetFileAttributesExA(g_path, GetFileExInfoStandard, &a))
        return;
    if (g_have_stamp && CompareFileTime(&a.ftLastWriteTime, &g_stamp) == 0)
        return;
    f = fopen(g_path, "r");
    if (!f)
        return;                      /* being swapped: the stamp is not taken, so the next poll tries again */
    memset(fresh, 0, sizeof(fresh));
    while (fgets(line, sizeof(line), f)) {
        int slot, card;
        float x, y;
        char *p = strchr(line, '#');
        if (p)
            *p = 0;
        for (p = line; *p; p++)
            if (*p == ',')
                *p = ' ';
        if (sscanf(line, "%d %d %f %f", &slot, &card, &x, &y) == 4 && slot >= 1 && slot <= SLOTS_SENT
            && card >= 1 && card <= 999999) {
            fresh[slot].used = 1;
            fresh[slot].card = card;
            fresh[slot].x = clampf(x);
            fresh[slot].y = clampf(y);
        }
    }
    fclose(f);
    memcpy(g_entries, fresh, sizeof(g_entries));
    g_stamp = a.ftLastWriteTime;
    g_have_stamp = 1;
    for (s = 1; s <= SLOTS_SENT; s++)
        n += g_entries[s].used;
    if (n != g_cards || g_polls < 2)
        logf_("table file read: %d card(s)", n);
    g_cards = n;
}

static int build_frame(char *buf, int cap)
{
    int len = 0, s;
    for (s = 1; s <= SLOTS_SENT; s++) {
        entry_t *e = &g_entries[s];
        if (g_table == 0 && e->used)
            len += _snprintf_s(buf + len, cap - len, _TRUNCATE, "%d,%d,%.3f,%.3f\r\n", s, e->card, e->x, e->y);
        else
            len += _snprintf_s(buf + len, cap - len, _TRUNCATE, "%d,-1,0,0\r\n", s);
    }
    len += _snprintf_s(buf + len, cap - len, _TRUNCATE, "-1,0,0,0\r\n");
    return len;
}

static void send_frame(HWND hwnd)
{
    char buf[2048];
    DWORD put = 0;
    int len;
    if (g_table == 0)
        load_table();
    len = build_frame(buf, sizeof(buf));
    if (!WriteFile(g_out, buf, (DWORD)len, &put, NULL) || put != (DWORD)len) {
        logf_("writing to the game failed (err %lu) - exiting", GetLastError());
        DestroyWindow(hwnd);
        return;
    }
    g_polls++;
    if (g_polls == 1)
        logf_("first poll answered (%d bytes, %d card(s))", len, g_cards);
    else if (g_polls % LOG_EVERY == 0)
        logf_("%ld polls answered, %d card(s)", g_polls, g_cards);
}

static LRESULT CALLBACK wndproc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp)
{
    switch (msg) {
    case WM_FPR_POLL:
        send_frame(hwnd);
        return 0;
    case WM_FPR_CLOSE:
        logf_("the game said goodbye (WM_USER+2) after %ld polls", g_polls);
        DestroyWindow(hwnd);
        return 0;
    case WM_TIMER:                   /* the game gone without saying goodbye */
        if (g_parent && WaitForSingleObject(g_parent, 0) == WAIT_OBJECT_0) {
            logf_("the game process ended - exiting after %ld polls", g_polls);
            DestroyWindow(hwnd);
        }
        return 0;
    case WM_DESTROY:
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcA(hwnd, msg, wp, lp);
}

/* The game's command line is " %s %d" with NO program name in front (CreateProcessA with the exe as the
 * application name), so argv[0] may be eaten by the C runtime.  Take the table number from the raw command
 * line instead: the second-to-last whole-number word (the last one is the slot count, 32). */
static int table_from_command_line(void)
{
    char buf[512], *tok, *ctx = NULL;
    int nums[16], n = 0;
    lstrcpynA(buf, GetCommandLineA(), sizeof(buf));
    for (tok = strtok_s(buf, " \t", &ctx); tok; tok = strtok_s(NULL, " \t", &ctx)) {
        char *end;
        long v = strtol(tok, &end, 10);
        if (*tok && *end == 0 && n < 16)
            nums[n++] = (int)v;
    }
    if (n >= 2)
        return nums[n - 2];
    if (n == 1)
        return nums[0];
    return 0;
}

static DWORD parent_pid(void)
{
    PROCESSENTRY32 pe;
    DWORD me = GetCurrentProcessId(), pp = 0;
    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (snap == INVALID_HANDLE_VALUE)
        return 0;
    pe.dwSize = sizeof(pe);
    if (Process32First(snap, &pe)) {
        do {
            if (pe.th32ProcessID == me) {
                pp = pe.th32ParentProcessID;
                break;
            }
        } while (Process32Next(snap, &pe));
    }
    CloseHandle(snap);
    return pp;
}

int main(int argc, char **argv)
{
    WNDCLASSA wc;
    HWND hwnd;
    MSG m;
    char logpath[MAX_PATH];
    DWORD pp;

    /* the stdout handle IS the game's pipe: take it, then leave the console the game made for us */
    g_out = GetStdHandle(STD_OUTPUT_HANDLE);
    FreeConsole();
    g_table = table_from_command_line();
    if (g_table < 0 || g_table > 1)
        g_table = 1;                 /* unknown: serve it empty rather than give our cards to the wrong reader */

    /* the window first: the game looks for it once, about 2 s after starting us */
    memset(&wc, 0, sizeof(wc));
    wc.lpfnWndProc = wndproc;
    wc.hInstance = GetModuleHandleA(NULL);
    wc.lpszClassName = "WCCF_FPR_Emu";
    RegisterClassA(&wc);
    hwnd = CreateWindowExA(WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE, "WCCF_FPR_Emu",
                           g_table ? "FPR_Emu table 1" : "FPR_Emu table 0",
                           WS_POPUP, 0, 0, 1, 1, NULL, NULL, wc.hInstance, NULL);
    if (!hwnd)
        return 1;
    ShowWindow(hwnd, SW_SHOWNOACTIVATE);   /* visible (the game checks IsWindowVisible), 1x1 px, no taskbar */

    _snprintf_s(g_path, sizeof(g_path), _TRUNCATE, "fpr_table%d.txt", g_table);
    _snprintf_s(logpath, sizeof(logpath), _TRUNCATE, "fpr_emu_table%d.log", g_table);
    g_log = fopen(logpath, "a");
    pp = parent_pid();
    g_parent = pp ? OpenProcess(SYNCHRONIZE, FALSE, pp) : NULL;
    logf_("==== FPR_Emu table %d (command line [%s], argc %d), parent pid %lu, stdout %p, cards from .\\%s ====",
          g_table, GetCommandLineA(), argc, pp, g_out, g_path);
    if (g_out == NULL || g_out == INVALID_HANDLE_VALUE)
        logf_("no stdout handle - the game will get nothing");
    if (g_table == 0)
        load_table();
    SetTimer(hwnd, 1, 1000, NULL);

    while (GetMessageA(&m, NULL, 0, 0) > 0) {
        TranslateMessage(&m);
        DispatchMessageA(&m);
    }
    logf_("exit");
    if (g_log)
        fclose(g_log);
    return 0;
}
