// wccfpanel.dll - in-game panel overlay for WCCF 2010-11 (seat 1), drawn by the GAME'S OWN Direct3D 9.
//
// The panels the player sketched, around the game's own picture, in the game's own window (no second window,
// no reparenting - reparenting froze the game on 2026-10-04):
//   LEFT  strip : TACTICS d-pad (up / down / left / right)
//   RIGHT strip : FORMATION pitch with his placed cards (top) + action buttons (bottom)
//   MIDDLE      : the game's own frame, scaled to fit with its shape kept - never covered, never stretched
// A click on a button injects the matching keyboard key (SendInput), so the existing keyboard driver
// (_keys_seat1.py, which polls GetAsyncKeyState) turns it into the real cabinet button - no shared-file fight.
//
// How it draws: the game's Direct3D 9 "Present" (put-frame-on-screen) call is detoured.  The game renders at a size
// fixed at boot (1440x900); stretching that to a bigger window blurs and distorts it (the player saw it with _resizable.py).
// So each frame we copy the game's finished frame, compose OUR picture at the window's real size on an extra swap
// chain of the game's device - panels from skin.tex, the game scaled into the middle - and present that instead.
// That is what lets the window be maximized - normal title bar kept; F11 or its own button toggles - with nothing
// stretched.  If the extra swap chain cannot be made, the old way runs (compose inside the game's own back-buffer)
// and the window stays at the game's own size.
// Raw D3D9 only (there is no d3dx9 on this PC).  DEFAULT-pool things (the frame copy, the swap chain) are released
// in the Reset detour; textures are MANAGED and survive a reset.
//
// Windows-11 note: each D3D9 device has its OWN vtable copy (D3D9-on-12), so we hook the shared Present FUNCTION
// (read from a throwaway device's slot 17), not a vtable slot.  Built by build.bat with the Win10 SDK's d3d9.lib.
//
// Test switches, read from the environment of the process that loads the DLL (fakegame.exe; the real game sets none):
//   WCCFPANEL_FULLSCREEN=0       start at the game's own window size (F11 still toggles)
//   WCCFPANEL_FS_RECT=x,y,w,h    "maximized" = moved onto this rectangle, never activated (an off-screen test;
//                                a real maximize would cover the player's screen and take focus from the live game)
//   WCCFPANEL_DRYKEYS=1          log button keys instead of pressing them, so a test can never press the live game

#define CINTERFACE
#define COBJMACROS
#define WIN32_LEAN_AND_MEAN
#define _WINSOCK_DEPRECATED_NO_WARNINGS          // inet_addr / inet_ntoa: IPv4 only, as the game itself
#include <winsock2.h>                    // the match relay: the game's own sendto/recvfrom (below the frame wait)
#include <windows.h>
#include <mmsystem.h>                    // JOYINFOEX / JOYCAPSA only: the joystick calls are looked up, never linked
#include <d3d9.h>
#include <wincodec.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <math.h>
#include <intrin.h>                      // _ReturnAddress: where the game called from (money with commas)
#pragma intrinsic(_ReturnAddress)
#pragma comment(lib, "advapi32.lib")     // the controllers' names (the registry), KEYS panel
#pragma comment(lib, "ws2_32.lib")       // the match relay

// ---- file paths: NONE fixed (the kit is unpacked anywhere).  Our own files sit beside this DLL: skin.tex, cards\,
// catalogue.tsv.  The game's card table and fpr_panel.py's saved formation sit in the GAME's folder (seat1\):
// fpr_table0.txt, fpr_panel_state.json.  g_dlldir is set in DllMain from this module's own path.
static char  g_dlldir[MAX_PATH];
static char  g_skin_path[MAX_PATH], g_cat_path[MAX_PATH];
static WCHAR g_cards_dirw[MAX_PATH];

typedef HRESULT (WINAPI *PresentFn)(IDirect3DDevice9 *, const RECT *, const RECT *, HWND, const RGNDATA *);

static PresentFn g_orig_present = NULL;
static long      g_frames = 0;
static int       g_ready = 0;

// the game window (subclassed for the mouse) and its maximized state - changed only on the window's own thread;
// the Present hook only ASKS for a change (by posting WM_WCCF_FS)
#define WM_WCCF_FS (WM_APP + 0x57)       // ours: wParam 1 = maximize, 0 = back to the game's own window size
static WNDPROC g_oldproc = NULL;
static HWND    g_hwnd = NULL;
static int     g_want_fs = 1;            // start maximized (WCCFPANEL_FULLSCREEN=0 starts at the game's own size)
static int     g_fs_asked = 0;           // the start-up switch was posted
static volatile LONG g_fs_msg_pending = 0;
static int     is_maximized(HWND h);
static void    dispenser_tick(void);         // the card dispenser fix (below the Present hook's helpers)
static void    set_tick(void);               // the SETTINGS panel's status (below the KEYS panel)
static void    club_tick(void);              // the CLUB CARD panel's view (below the SETTINGS panel)
static int     pad_tick(void);               // the KEYS panel's controllers (in the KEYS panel); 1 = back soon
static void    frame_stats_tick(void);       // seat 1's frame timing, when asked (the frame wait, below the money)

// ---------------------------------------------------------------- logging
static int g_projector = 0;              // in the projector (money only): the log goes to the kit's logs, WCCF_LOGS

static void logline(const char *fmt, ...)
{
    char path[MAX_PATH], dir[MAX_PATH], *slash; DWORD n = 0;
    if (g_projector) n = GetEnvironmentVariableA("WCCF_LOGS", dir, MAX_PATH);
    if (n > 0 && n < MAX_PATH - 32) {
        _snprintf(path, MAX_PATH, "%s\\wccfpanel_projector.log", dir);
    } else {                             // seat 1: beside the program (seat1\wccfpanel.log), as before
        GetModuleFileNameA(NULL, dir, MAX_PATH);
        slash = strrchr(dir, '\\'); if (slash) *slash = 0;
        _snprintf(path, MAX_PATH, "%s\\wccfpanel.log", dir);
    }
    path[MAX_PATH - 1] = 0;
    FILE *f = fopen(path, "a"); if (!f) return;
    va_list ap; va_start(ap, fmt); vfprintf(f, fmt, ap); va_end(ap);
    fputc('\n', f); fclose(f);
}

// ---------------------------------------------------------------- the cards on the table (the game's table file)
// fpr_table0.txt in the GAME'S OWN folder (seat1\ for seat 1; a test's own folder for fakegame - never the real
// seat-1 file from a test): what FPR_Emu.exe hands the game every ~10 ms.  Lines "slot card x y", fpr_panel.py's
// format.  The board thread re-reads it when someone else changes it; the board rewrites it on every move of a
// dragged card.  g_board_cs guards the cards: the render, window and board threads all touch them.
#define MAXCARDS 16
struct Card { int slot, no; float x, y; char name[40]; char pos[6]; RECT px; };
static struct Card g_cards[MAXCARDS];
static int    g_ncards = 0;
static CRITICAL_SECTION g_board_cs;
static char   g_table_path[MAX_PATH], g_table_tmp[MAX_PATH], g_state_path[MAX_PATH];
static ULONGLONG g_table_stamp = 0;          // the table's write time as we last read or wrote it
static int    g_write_pending = 0;           // a write could not be swapped in yet: the next frame tries again
static int    g_drag = -1, g_hover = -1;     // the card being dragged / under the mouse (index into g_cards)
static float  g_drag_dx, g_drag_dy;          // where on the card it was picked up
static DWORD  g_hover_since = 0;

static ULONGLONG ft_q(FILETIME t) { return ((ULONGLONG)t.dwHighDateTime << 32) | t.dwLowDateTime; }

static void board_paths(void)
{
    char exe[MAX_PATH], dir[MAX_PATH], *sl;
    GetModuleFileNameA(NULL, exe, MAX_PATH);
    if (!GetFullPathNameA(exe, MAX_PATH, dir, NULL)) lstrcpynA(dir, exe, MAX_PATH);
    sl = strrchr(dir, '\\'); if (sl) *sl = 0;
    _snprintf(g_table_path, MAX_PATH, "%s\\fpr_table0.txt", dir);
    _snprintf(g_table_tmp, MAX_PATH, "%s\\fpr_table0.txt.board", dir);
    // fpr_panel.py's saved formation lives beside the table, in the game's own folder: the real seat 1 keeps the real
    // one, a test (fakegame in its own folder) keeps its own - no path to configure, nothing a test can reach by mistake
    _snprintf(g_state_path, MAX_PATH, "%s\\fpr_panel_state.json", dir);
    _snprintf(g_skin_path, MAX_PATH, "%s\\skin.tex", g_dlldir);
    _snprintf(g_cat_path, MAX_PATH, "%s\\catalogue.tsv", g_dlldir);
    {
        WCHAR wd[MAX_PATH];
        if (!MultiByteToWideChar(CP_ACP, 0, g_dlldir, -1, wd, MAX_PATH)) wd[0] = 0;
        _snwprintf(g_cards_dirw, MAX_PATH, L"%s\\cards", wd);
        g_cards_dirw[MAX_PATH - 1] = 0;
    }
    logline("board: table %s ; fpr_panel state %s ; our files in %s", g_table_path, g_state_path, g_dlldir);
}

// the table file -> out[] (FPR_Emu's own rules: # comments, commas or spaces, slot 1..20); -1 = could not read
static int parse_table(struct Card *out, int max, ULONGLONG *stamp)
{
    WIN32_FILE_ATTRIBUTE_DATA a; FILE *f; char line[256]; int n = 0;
    if (!GetFileAttributesExA(g_table_path, GetFileExInfoStandard, &a)) return -1;
    f = fopen(g_table_path, "rb");
    if (!f) return -1;                               // being swapped: try again next time
    while (fgets(line, sizeof line, f) && n < max) {
        int slot, no; float x, y; char *p = strchr(line, '#');
        if (p) *p = 0;
        for (p = line; *p; p++) if (*p == ',') *p = ' ';
        if (sscanf(line, "%d %d %f %f", &slot, &no, &x, &y) == 4 && slot >= 1 && slot <= 20 && no >= 1) {
            memset(&out[n], 0, sizeof out[n]);
            out[n].slot = slot; out[n].no = no; out[n].x = x; out[n].y = y;
            n++;
        }
    }
    fclose(f);
    *stamp = ft_q(a.ftLastWriteTime);
    return n;
}

// Rewrite the table whole (temp file, then one swap: FPR_Emu never sees half a file).  Called with g_board_cs held.
// The temp file gets a write time strictly after the last one: FPR_Emu re-reads only when the write time changes,
// and two moves inside one clock tick would look like one - the last place of a fast drag could be lost.
static int write_table_locked(void)
{
    char text[2048]; int n, k; DWORD put = 0; BOOL ok; FILETIME now, ft; ULONGLONG q; HANDLE f;
    n = _snprintf(text, sizeof text, "# written by the in-game card board (wccfpanel.dll) - read by FPR_Emu.exe (table 0)\n");
    for (k = 0; k < g_ncards && n < (int)sizeof text - 64; k++)
        n += _snprintf(text + n, sizeof text - n, "%d %d %.3f %.3f\n", g_cards[k].slot, g_cards[k].no, g_cards[k].x, g_cards[k].y);
    f = CreateFileA(g_table_tmp, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (f == INVALID_HANDLE_VALUE) { g_write_pending = 1; return 0; }
    ok = WriteFile(f, text, (DWORD)n, &put, NULL) && put == (DWORD)n;
    GetSystemTimeAsFileTime(&now);
    q = ft_q(now);
    if (q <= g_table_stamp) q = g_table_stamp + 10000;          // +1 ms past the last one
    ft.dwLowDateTime = (DWORD)q; ft.dwHighDateTime = (DWORD)(q >> 32);
    SetFileTime(f, NULL, NULL, &ft);
    CloseHandle(f);
    if (!ok) { g_write_pending = 1; return 0; }
    for (k = 0; k < 4; k++) {            // FPR_Emu may be reading it this instant: a moment, then leave it to the next frame
        if (MoveFileExA(g_table_tmp, g_table_path, MOVEFILE_REPLACE_EXISTING)) {
            g_table_stamp = q; g_write_pending = 0; return 1;
        }
        Sleep(1);
    }
    g_write_pending = 1;
    return 0;
}

// fpr_panel.py writes ITS saved table into the game's table when it opens: keep that copy equal to the game's, or
// opening the panel would put the old places back.  Its "mirror" choice is kept as it is.  g_board_cs held.
static void write_panel_state_locked(void)
{
    char old[8192], text[4096], tmp[MAX_PATH], *m; int n = 0, i, k, mirror = 0; size_t got = 0; FILE *f;
    f = fopen(g_state_path, "rb");
    if (f) { got = fread(old, 1, sizeof old - 1, f); fclose(f); }
    old[got] = 0;
    m = strstr(old, "\"mirror\"");
    if (m && (m = strchr(m, ':')) != NULL) {
        for (m++; *m == ' ' || *m == '\t' || *m == '\r' || *m == '\n'; m++) {}
        mirror = (*m == 't');
    }
    n += _snprintf(text + n, sizeof text - n, "{\n \"placed\": [");
    for (i = 0; i < g_ncards; i++) {
        float x = g_cards[i].x;
        if (mirror && x <= 1.16f) x = -x;            // the table holds the mirrored x; the panel keeps it unmirrored
        n += _snprintf(text + n, sizeof text - n, "%s\n  {\"slot\": %d, \"no\": %d, \"x\": %.3f, \"y\": %.3f}",
                       i ? "," : "", g_cards[i].slot, g_cards[i].no, x, g_cards[i].y);
    }
    n += _snprintf(text + n, sizeof text - n, "\n ],\n \"mirror\": %s\n}\n", mirror ? "true" : "false");
    _snprintf(tmp, MAX_PATH, "%s.board", g_state_path);
    f = fopen(tmp, "wb");
    if (!f) return;
    fwrite(text, 1, (size_t)n, f);
    fclose(f);
    for (k = 0; k < 20 && !MoveFileExA(tmp, g_state_path, MOVEFILE_REPLACE_EXISTING); k++) Sleep(2);
}

// ---------------------------------------------------------------- the buttons (styled like the real cabinet deck)
// shape: 0 = rounded rect, 1 = round arcade button.  vk 0 = visual only (no key injected yet).
// color is the face colour; rects are computed each frame in layout().
enum { SHAPE_RECT = 0, SHAPE_ROUND = 1 };
struct Btn { const char *label; int vk; int shape; DWORD color; RECT px; };
#define COL_GREEN  D3DCOLOR_ARGB(255,  60, 175,  75)
#define COL_RED    D3DCOLOR_ARGB(255, 210,  50,  45)
#define COL_BLUE   D3DCOLOR_ARGB(255,  45, 115, 225)
#define COL_YELLOW D3DCOLOR_ARGB(255, 235, 200,  45)
#define COL_GREY   D3DCOLOR_ARGB(255,  78,  84,  96)
// indices are referenced by name in layout()/draw; keep this order
enum { B_UP, B_DOWN, B_LEFT, B_RIGHT, B_PRESS, B_DATA, B_SHOOT, B_KEEP, B_KEYPL, B_START, B_BACK, B_CARD, B_COIN };
static struct Btn g_btn[] = {
    // tactics d-pad (left) - names from the manual; all four are the arrow keys
    { "CENTRAL", VK_UP,    SHAPE_RECT,  COL_GREEN,  {0} },   // 中央突破
    { "COUNTER", VK_DOWN,  SHAPE_RECT,  COL_GREEN,  {0} },   // カウンター
    { "L-SIDE",  VK_LEFT,  SHAPE_RECT,  COL_GREEN,  {0} },   // 左サイド攻撃
    { "R-SIDE",  VK_RIGHT, SHAPE_RECT,  COL_GREEN,  {0} },   // 右サイド攻撃
    { "PRESS",   0x58,     SHAPE_ROUND, COL_RED,    {0} },   // プレス = X (the player: X actually does PRESS) [V]
    { "DATA",    0x53,     SHAPE_RECT,  COL_GREY,   {0} },   // DATA = S (the player: blue/S actually does DATA) [V]
    // right action cluster - colours as the real cabinet
    { "SHOOT",   0x43,     SHAPE_ROUND, COL_RED,    {0} },   // シュート, red (C)
    { "KEEPER",  0x42,     SHAPE_ROUND, COL_BLUE,   {0} },   // キーパー/goalie = B (the player: BACK/B actually does GOALIE) [V]
    { "KEYPLYR", 0x44,     SHAPE_ROUND, COL_YELLOW, {0} },   // キープレイヤー, yellow = D (guess - verify)
    { "START",   0x0D,     SHAPE_ROUND, COL_GREEN,  {0} },   // スタート, green (Enter)
    { "BACK",    0,        SHAPE_RECT,  COL_GREY,   {0} },   // unknown - no key fired until verified
    { "CARD",    0x49,     SHAPE_RECT,  COL_GREY,   {0} },   // I = card in/out
    { "COIN",    0x35,     SHAPE_RECT,  COL_GREY,   {0} },   // 5
};
#define NBTN ((int)(sizeof g_btn / sizeof g_btn[0]))

static RECT g_pitch;                 // the formation pitch rectangle (screen px)
static UINT g_bw = 0, g_bh = 0;      // current back-buffer size

// held-key state (one at a time - a single mouse)
static int   g_held_vk = 0;
static int   g_mouse_down = 0;
static DWORD g_down_tick = 0;
static int   g_held_btn = -1;        // which button is lit

static int g_dry = -1;               // WCCFPANEL_DRYKEYS=1: log instead of pressing (read once)

static void send_key(int vk, int up)
{
    if (!vk) return;                 // a button with no key yet (BACK) presses nothing
    if (g_dry < 0) { char e[8]; g_dry = GetEnvironmentVariableA("WCCFPANEL_DRYKEYS", e, sizeof e) > 0 && e[0] == '1'; }
    if (g_dry) { logline("key 0x%02X %s (dry run - not pressed)", vk, up ? "up" : "down"); return; }
    INPUT in; ZeroMemory(&in, sizeof in);
    in.type = INPUT_KEYBOARD;
    in.ki.wVk = (WORD)vk;
    in.ki.dwFlags = up ? KEYEVENTF_KEYUP : 0;
    SendInput(1, &in, sizeof(INPUT));
}

// ---------------------------------------------------------------- 2D drawing (raw D3D9)
struct VTX { float x, y, z, rhw; DWORD color; };
#define FVF_2D (D3DFVF_XYZRHW | D3DFVF_DIFFUSE)

static void fill_rect(IDirect3DDevice9 *d, float x, float y, float w, float h, DWORD argb)
{
    struct VTX v[4] = {
        { x,     y,     0.0f, 1.0f, argb }, { x + w, y,     0.0f, 1.0f, argb },
        { x,     y + h, 0.0f, 1.0f, argb }, { x + w, y + h, 0.0f, 1.0f, argb },
    };
    IDirect3DDevice9_DrawPrimitiveUP(d, D3DPT_TRIANGLESTRIP, 2, v, sizeof(struct VTX));
}

static void fill_vgrad(IDirect3DDevice9 *d, float x, float y, float w, float h, DWORD top, DWORD bottom)
{
    struct VTX v[4] = {
        { x,     y,     0.0f, 1.0f, top    }, { x + w, y,     0.0f, 1.0f, top    },
        { x,     y + h, 0.0f, 1.0f, bottom }, { x + w, y + h, 0.0f, 1.0f, bottom },
    };
    IDirect3DDevice9_DrawPrimitiveUP(d, D3DPT_TRIANGLESTRIP, 2, v, sizeof(struct VTX));
}

static void outline(IDirect3DDevice9 *d, float x, float y, float w, float h, float t, DWORD c)
{
    fill_rect(d, x, y, w, t, c); fill_rect(d, x, y + h - t, w, t, c);
    fill_rect(d, x, y, t, h, c); fill_rect(d, x + w - t, y, t, h, c);
}

static DWORD pos_color(const char *pos)
{
    if (pos[0] == 'G') return D3DCOLOR_ARGB(255, 240, 200, 40);    // GK yellow
    if (pos[0] == 'D') return D3DCOLOR_ARGB(255, 70, 130, 230);    // DF blue
    if (pos[0] == 'M') return D3DCOLOR_ARGB(255, 70, 190, 90);     // MF green
    if (pos[0] == 'F') return D3DCOLOR_ARGB(255, 225, 70, 70);     // FW red
    return D3DCOLOR_ARGB(255, 180, 180, 180);
}

static DWORD lighten(DWORD c, int add)
{
    int a = (c >> 24) & 0xFF, r = (c >> 16) & 0xFF, g = (c >> 8) & 0xFF, b = c & 0xFF;
    r = r + add > 255 ? 255 : r + add; g = g + add > 255 ? 255 : g + add; b = b + add > 255 ? 255 : b + add;
    return D3DCOLOR_ARGB(a, r, g, b);
}

static void fill_circle(IDirect3DDevice9 *d, float cx, float cy, float r, DWORD c)
{
    enum { SEG = 32 };
    struct VTX v[SEG + 2];
    v[0].x = cx; v[0].y = cy; v[0].z = 0; v[0].rhw = 1; v[0].color = c;
    for (int i = 0; i <= SEG; i++) {
        float a = (float)i / SEG * 6.2831853f;
        v[i + 1].x = cx + r * (float)cos(a); v[i + 1].y = cy + r * (float)sin(a);
        v[i + 1].z = 0; v[i + 1].rhw = 1; v[i + 1].color = c;
    }
    IDirect3DDevice9_DrawPrimitiveUP(d, D3DPT_TRIANGLEFAN, SEG, v, sizeof(struct VTX));
}

// a cabinet-style button: dark base, coloured face, a soft top highlight, brighter when pressed
static void draw_button(IDirect3DDevice9 *d, struct Btn *b, int lit)
{
    float x = (float)b->px.left, y = (float)b->px.top;
    float w = (float)(b->px.right - b->px.left), h = (float)(b->px.bottom - b->px.top);
    DWORD face = lit ? lighten(b->color, 70) : b->color;
    if (b->shape == SHAPE_ROUND) {
        float cx = x + w / 2, cy = y + h / 2, rad = (w < h ? w : h) / 2;
        fill_circle(d, cx, cy, rad, D3DCOLOR_ARGB(255, 10, 10, 12));
        fill_circle(d, cx, cy, rad - 2.5f, face);
        fill_circle(d, cx - rad * 0.22f, cy - rad * 0.30f, rad * 0.48f, lighten(face, 40));
    } else {
        fill_rect(d, x, y, w, h, D3DCOLOR_ARGB(255, 10, 10, 12));
        fill_rect(d, x + 2, y + 2, w - 4, h - 4, face);
        fill_rect(d, x + 2, y + 2, w - 4, (h - 4) * 0.45f, lighten(face, 28));
    }
}

static RECT RC(float l, float t, float r, float b)
{
    RECT x; x.left = (LONG)l; x.top = (LONG)t; x.right = (LONG)r; x.bottom = (LONG)b; return x;
}

#define ORANGE  D3DCOLOR_ARGB(255, 240, 130, 20)
#define PANELBG D3DCOLOR_ARGB(212, 14, 14, 17)
static float g_playW = 0, g_benchX = 0;        // pitch playing-area width, and where the bench column starts

// ---- the canvas: the picture the window finally shows (1920x1080 fullscreen, 1440x900 in the old window)
// The panels are designed on a 1440x900 sheet (skin.html): left strip x 0..190, right strip x 1060..1440, the
// middle left clear.  On a canvas of any size the strips are scaled by s = min(H/900, W/1440) and pinned to the
// left and right edges; the middle column between them gets the game, scaled to fit with its shape kept.
// 1440x900 gives s = 1 and exactly the old picture; 1920x1080 gives s = 1.2 and a wider middle.
#define DES_W 1440.0f
#define DES_H 900.0f
#define DES_L 190.0f                     // the left strip ends here on the sheet
#define DES_R 1060.0f                    // the right strip starts here
static float g_cw = DES_W, g_ch = DES_H; // canvas size (what layout() last ran for)
static float g_s = 1.0f, g_py = 0.0f;    // strip scale, strip top
static float g_mx0 = DES_L, g_mx1 = DES_R;  // the middle column on the canvas
static UINT  g_gw = 0, g_gh = 0;         // the game's own frame size (its back-buffer)
// COMPACT (2026-10-06; a player: "a layout without visible buttons? I don't think anyone clicks them with the mouse -
// though the KEYS button is very useful. So that the field is on the right and the game is larger on the left"; the player:
// "make it a toggleable thing in the settings"): no left strip, none of the 13 cabinet buttons (keys and controllers
// press them) - the game takes the left; the right strip keeps the field, CATALOGUE and KEYS, with SETTINGS and
// CLUB CARD moved under them (compact_strip).  SETTINGS > VIEW > LAYOUT switches it at once; data\panel.txt keeps it.
static int   g_compact = 0;

static RECT strip_rect(float x0, float y0, float x1, float y1)    // sheet px in the right strip -> canvas (pinned right)
{
    RECT r;
    r.left = (LONG)(g_cw - (DES_W - x0) * g_s); r.top = (LONG)(g_py + y0 * g_s);
    r.right = (LONG)(g_cw - (DES_W - x1) * g_s); r.bottom = (LONG)(g_py + y1 * g_s);
    return r;
}

// Button hit-boxes as fractions of the 1440x900 design sheet, SAME order as the enum (B_UP..B_COIN).
// These must match the positions baked into skin.html / skin.tex.
static const float BTNF[NBTN][4] = {
    {  72/1440.f, 430/900.f, 118/1440.f, 476/900.f },  // UP
    {  72/1440.f, 534/900.f, 118/1440.f, 580/900.f },  // DOWN
    {  20/1440.f, 482/900.f,  66/1440.f, 528/900.f },  // LEFT
    { 124/1440.f, 482/900.f, 170/1440.f, 528/900.f },  // RIGHT
    {  72/1440.f, 482/900.f, 118/1440.f, 528/900.f },  // PRESS (centre)
    {  14/1440.f,  46/900.f,  92/1440.f,  80/900.f },  // DATA
    {1104/1440.f, 700/900.f,1190/1440.f, 786/900.f },  // SHOOT
    {1312/1440.f, 700/900.f,1398/1440.f, 786/900.f },  // KEEPER
    {1208/1440.f, 594/900.f,1294/1440.f, 680/900.f },  // KEY PLAYER
    {1220/1440.f, 520/900.f,1282/1440.f, 582/900.f },  // START
    {  98/1440.f,  46/900.f, 176/1440.f,  80/900.f },  // BACK
    {  14/1440.f,  88/900.f,  92/1440.f, 122/900.f },  // CARD
    {  98/1440.f,  88/900.f, 176/1440.f, 122/900.f },  // COIN
};

// A button answers on its whole picture (2026-10-06, the player: "when i click on the button as a whole it takes for the
// whole asset"): the click areas above were the buttons' boxes in skin.html, but the pictures' 3D lower edge and drop
// shadow reach past them (fstest\click_areas.png, _probe_click_areas.py).  Each area grows by these sheet px - left,
// top, right, bottom - and no two meet (checked there): the d-pad's buttons are 6 px apart, so they share the gap.
static const float GROW_DPAD[4] = { 2.0f, 2.0f, 3.0f, 3.0f };      // UP DOWN LEFT RIGHT PRESS
static const float GROW_LEFT[4] = { 3.0f, 3.0f, 2.0f, 4.0f };      // DATA BACK CARD COIN SETTINGS CLUB CARD
static const float GROW_RIGHT[4] = { 3.0f, 3.0f, 5.0f, 7.0f };     // START KEY PL SHOOT KEEPER CATALOGUE KEYS
static const float *const BTN_GROW[NBTN] = { GROW_DPAD, GROW_DPAD, GROW_DPAD, GROW_DPAD, GROW_DPAD, GROW_LEFT,
                                             GROW_RIGHT, GROW_RIGHT, GROW_RIGHT, GROW_RIGHT, GROW_LEFT, GROW_LEFT,
                                             GROW_LEFT };     // the enum's order: B_UP .. B_COIN

static RECT grown(RECT r, const float m[4])
{
    r.left -= (LONG)(m[0] * g_s + 0.5f); r.top -= (LONG)(m[1] * g_s + 0.5f);
    r.right += (LONG)(m[2] * g_s + 0.5f); r.bottom += (LONG)(m[3] * g_s + 0.5f);
    return r;
}

static void layout(UINT W, UINT H)
{
    g_cw = (float)W; g_ch = (float)H;
    float sh = g_ch / DES_H, sw = g_cw / DES_W;
    g_s = sh < sw ? sh : sw;
    g_py = (g_ch - DES_H * g_s) * 0.5f;
    g_mx0 = g_compact ? 0.0f : DES_L * g_s;               // COMPACT: no left strip, the game takes the left
    g_mx1 = g_cw - (DES_W - DES_R) * g_s;
    for (int i = 0; i < NBTN; i++) {                       // every button sits wholly in one strip
        float l = BTNF[i][0] * DES_W, t = BTNF[i][1] * DES_H, r = BTNF[i][2] * DES_W, b = BTNF[i][3] * DES_H;
        int right = l >= DES_R;
        float x0 = right ? g_cw - (DES_W - l) * g_s : l * g_s;
        float x1 = right ? g_cw - (DES_W - r) * g_s : r * g_s;
        g_btn[i].px = g_compact ? RC(0.0f, 0.0f, 0.0f, 0.0f)      // COMPACT: not there, nothing to click
                                : grown(RC(x0, g_py + t * g_s, x1, g_py + b * g_s), BTN_GROW[i]);
    }
}

static void draw_overlay(IDirect3DDevice9 *dev, UINT W, UINT H)
{
    layout(W, H);
    float fw = (float)W, fh = (float)H;
    float lw = fw * 0.13f, rw = fw * 0.25f, rx = fw - rw;

    // panels, with the 2010-11 cabinet's orange/black trim
    fill_rect(dev, 0, 0, lw, fh, PANELBG);
    fill_rect(dev, rx, 0, rw, fh, PANELBG);
    fill_rect(dev, 0, 0, lw, 5, ORANGE);          fill_rect(dev, rx, 0, rw, 5, ORANGE);
    fill_rect(dev, lw - 5, 0, 5, fh, ORANGE);     fill_rect(dev, rx, 0, 5, fh, ORANGE);

    // ---- pitch: mown stripes, markings, bench column 1-5, GK box
    float pL = (float)g_pitch.left, pT = (float)g_pitch.top;
    float pW = (float)(g_pitch.right - g_pitch.left), pH = (float)(g_pitch.bottom - g_pitch.top);
    int stripes = 9;
    for (int i = 0; i < stripes; i++)
        fill_rect(dev, pL, pT + i * (pH / stripes), pW, pH / stripes + 1,
                  (i & 1) ? D3DCOLOR_ARGB(235, 40, 122, 64) : D3DCOLOR_ARGB(235, 33, 104, 54));
    DWORD line = D3DCOLOR_ARGB(215, 238, 238, 238);
    float plW = g_playW;                                   // play area excludes the bench column
    outline(dev, pL, pT, plW, pH, 2.0f, line);
    fill_rect(dev, pL, pT + pH/2 - 1, plW, 2.0f, line);    // halfway line
    fill_circle(dev, pL + plW/2, pT + pH/2, 4.0f, line);   // centre spot
    outline(dev, pL + plW*0.28f, pT, plW*0.44f, pH*0.14f, 2.0f, line);               // far box
    outline(dev, pL + plW*0.28f, pT + pH*0.86f, plW*0.44f, pH*0.14f, 2.0f, line);    // own box (bottom)
    // bench column
    fill_rect(dev, g_benchX, pT, (float)g_pitch.right - g_benchX, pH, D3DCOLOR_ARGB(220, 26, 28, 32));
    float slotH = pH / 5.0f;
    for (int i = 0; i < 5; i++)
        outline(dev, g_benchX, pT + i*slotH, (float)g_pitch.right - g_benchX, slotH, 1.5f, D3DCOLOR_ARGB(160,200,200,200));

    // ---- cards
    float cw = plW * 0.17f, ch = pH * 0.09f;
    int benchn = 0;
    for (int i = 0; i < g_ncards; i++) {
        float sx, sy;
        if (g_cards[i].x > 1.16f) {                        // bench slot
            sx = g_benchX + ((float)g_pitch.right - g_benchX - cw) / 2;
            sy = pT + benchn * slotH + (slotH - ch) / 2; benchn++;
        } else {
            sx = pL + (g_cards[i].x + 1.0f) * 0.5f * plW - cw / 2;
            sy = pT + (g_cards[i].y + 1.0f) * 0.5f * pH - ch / 2;      // y=+1 -> own goal (bottom)
            if (sx < pL) sx = pL; if (sx + cw > pL + plW) sx = pL + plW - cw;
            if (sy < pT) sy = pT; if (sy + ch > pT + pH) sy = pT + pH - ch;
        }
        fill_rect(dev, sx, sy, cw, ch, pos_color(g_cards[i].pos));
        outline(dev, sx, sy, cw, ch, 1.5f, D3DCOLOR_ARGB(255, 10, 10, 10));
        fill_rect(dev, sx, sy + ch*0.58f, cw, ch*0.42f, D3DCOLOR_ARGB(170, 0, 0, 0));  // name strip for contrast
        g_cards[i].px = RC(sx, sy + ch*0.58f, sx + cw, sy + ch);
    }

    // ---- buttons
    for (int i = 0; i < NBTN; i++)
        draw_button(dev, &g_btn[i], i == g_held_btn);
}

// ---------------------------------------------------------------- text (a font atlas drawn with D3D9)
// GDI GetDC needs a lockable back-buffer, which games don't give; so we bake an ASCII font into a MANAGED texture
// once (survives device Reset) and draw each glyph as a textured quad - works on any device.
struct VTXT { float x, y, z, rhw; DWORD color; float u, v; };
#define FVF_TEXT (D3DFVF_XYZRHW | D3DFVF_DIFFUSE | D3DFVF_TEX1)
static IDirect3DTexture9 *g_font_tex = NULL;
static int g_cellw = 0, g_cellh = 0, g_atlasw = 0, g_atlash = 0;
static int g_advw = 0;                   // how far one letter moves the pen (the font's normal width; cells are wider)

static void build_font(IDirect3DDevice9 *dev)
{
    HDC dc = CreateCompatibleDC(NULL);
    HFONT fnt = CreateFontA(-26, 0, 0, 0, FW_SEMIBOLD, 0, 0, 0, DEFAULT_CHARSET, OUT_TT_PRECIS,
                            CLIP_DEFAULT_PRECIS, ANTIALIASED_QUALITY, FIXED_PITCH | FF_MODERN, "Consolas");
    HGDIOBJ of = SelectObject(dc, fnt);
    TEXTMETRICA tm; GetTextMetricsA(dc, &tm);
    g_cellw = tm.tmMaxCharWidth + 2; g_cellh = tm.tmHeight + 2;
    g_advw = tm.tmAveCharWidth > 0 ? tm.tmAveCharWidth : g_cellw;   // Consolas: every letter is this wide
    g_atlasw = g_cellw * 16; g_atlash = g_cellh * 6;            // 96 cells for ASCII 32..127

    BITMAPINFO bi; ZeroMemory(&bi, sizeof bi);
    bi.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
    bi.bmiHeader.biWidth = g_atlasw; bi.bmiHeader.biHeight = -g_atlash;   // top-down
    bi.bmiHeader.biPlanes = 1; bi.bmiHeader.biBitCount = 32; bi.bmiHeader.biCompression = BI_RGB;
    void *bits = NULL;
    HBITMAP dib = CreateDIBSection(dc, &bi, DIB_RGB_COLORS, &bits, NULL, 0);
    HGDIOBJ ob = SelectObject(dc, dib);
    RECT all = { 0, 0, g_atlasw, g_atlash };
    FillRect(dc, &all, (HBRUSH)GetStockObject(BLACK_BRUSH));
    SetBkMode(dc, TRANSPARENT); SetTextColor(dc, RGB(255, 255, 255));
    for (int i = 0; i < 96; i++) {
        char ch = (char)(32 + i);
        TextOutA(dc, (i % 16) * g_cellw + 1, (i / 16) * g_cellh + 1, &ch, 1);
    }
    GdiFlush();

    if (SUCCEEDED(IDirect3DDevice9_CreateTexture(dev, g_atlasw, g_atlash, 1, 0, D3DFMT_A8R8G8B8,
                                                 D3DPOOL_MANAGED, &g_font_tex, NULL))) {
        D3DLOCKED_RECT lr;
        if (SUCCEEDED(IDirect3DTexture9_LockRect(g_font_tex, 0, &lr, NULL, 0))) {
            for (int y = 0; y < g_atlash; y++) {
                DWORD *d = (DWORD *)((BYTE *)lr.pBits + y * lr.Pitch);
                DWORD *s = (DWORD *)bits + (size_t)y * g_atlasw;
                for (int x = 0; x < g_atlasw; x++) {
                    DWORD a = s[x] & 0xFF;                      // white glyph on black -> luminance = alpha
                    d[x] = (a << 24) | 0x00FFFFFF;             // white, so a diffuse tint colours the text
                }
            }
            IDirect3DTexture9_UnlockRect(g_font_tex, 0);
        }
    }
    // diagnostic: write the atlas's BLUE channel (what becomes the glyph alpha) as a grayscale BMP
    {
        char p2[MAX_PATH], dr[MAX_PATH], *sl; GetModuleFileNameA(NULL, dr, MAX_PATH);
        sl = strrchr(dr, '\\'); if (sl) *sl = 0; _snprintf(p2, MAX_PATH, "%s\\wccfpanel_atlas.bmp", dr);
        FILE *af = fopen(p2, "wb");
        if (af) {
            int W = g_atlasw, H = g_atlash; UINT rowsz = (W * 3 + 3) & ~3u; DWORD imgsz = rowsz * H;
            BITMAPFILEHEADER fh; ZeroMemory(&fh, sizeof fh); BITMAPINFOHEADER ih; ZeroMemory(&ih, sizeof ih);
            fh.bfType = 0x4D42; fh.bfOffBits = sizeof(fh) + sizeof(ih); fh.bfSize = fh.bfOffBits + imgsz;
            ih.biSize = sizeof ih; ih.biWidth = W; ih.biHeight = H; ih.biPlanes = 1; ih.biBitCount = 24; ih.biCompression = BI_RGB;
            fwrite(&fh, sizeof fh, 1, af); fwrite(&ih, sizeof ih, 1, af);
            BYTE *row = (BYTE *)malloc(rowsz);
            for (int y = H - 1; y >= 0; y--) {
                DWORD *s = (DWORD *)bits + (size_t)y * W; ZeroMemory(row, rowsz);
                for (int x = 0; x < W; x++) { BYTE g = (BYTE)(s[x] & 0xFF); row[x*3]=g; row[x*3+1]=g; row[x*3+2]=g; }
                fwrite(row, rowsz, 1, af);
            }
            free(row); fclose(af);
        }
    }
    SelectObject(dc, ob); DeleteObject(dib);
    SelectObject(dc, of); DeleteObject(fnt); DeleteDC(dc);
    logline("font atlas %dx%d cell %dx%d tex=%p", g_atlasw, g_atlash, g_cellw, g_cellh, (void *)g_font_tex);
}

static float str_w(const char *s, float scale) { int n = 0; while (s[n]) n++; return n * g_advw * scale; }

static void put_str(IDirect3DDevice9 *dev, float x, float y, float scale, DWORD col, const char *s)
{
    static struct VTXT v[120 * 6]; int n = 0;   // up to 120 letters per call
    float cw = g_cellw * scale, ch = g_cellh * scale;
    float uw = (float)g_cellw / g_atlasw, vh = (float)g_cellh / g_atlash;
    for (const char *p = s; *p && n < 120 * 6; p++) {
        int c = (unsigned char)*p; if (c < 32 || c > 127) c = '?';
        int idx = c - 32, cc = idx % 16, rr = idx / 16;
        float u0 = cc * uw, v0 = rr * vh, u1 = u0 + uw, v1 = v0 + vh;
        float x0 = x, y0 = y, x1 = x + cw, y1 = y + ch;
        struct VTXT a = { x0, y0, 0, 1, col, u0, v0 }, b = { x1, y0, 0, 1, col, u1, v0 };
        struct VTXT e = { x0, y1, 0, 1, col, u0, v1 }, f = { x1, y1, 0, 1, col, u1, v1 };
        v[n++] = a; v[n++] = b; v[n++] = e; v[n++] = e; v[n++] = b; v[n++] = f;
        x += g_advw * scale;                     // the cell is drawn whole (its spare width is clear), the pen moves less
    }
    if (n) IDirect3DDevice9_DrawPrimitiveUP(dev, D3DPT_TRIANGLELIST, n / 3, v, sizeof(struct VTXT));
}

static void put_in_rect(IDirect3DDevice9 *dev, RECT r, float scale, DWORD col, const char *s)
{
    float w = str_w(s, scale), rw = (float)(r.right - r.left);
    if (w > rw * 0.96f && w > 0) scale *= (rw * 0.96f) / w;      // shrink to fit the box
    w = str_w(s, scale);
    float x = r.left + (rw - w) / 2.0f;
    float y = r.top + ((r.bottom - r.top) - g_cellh * scale) / 2.0f;
    put_str(dev, x, y, scale, col, s);
}

static void draw_text(IDirect3DDevice9 *dev)
{
    if (!g_font_tex) { build_font(dev); if (!g_font_tex) return; }
    IDirect3DDevice9_SetFVF(dev, FVF_TEXT);
    IDirect3DDevice9_SetTexture(dev, 0, (IDirect3DBaseTexture9 *)g_font_tex);
    IDirect3DDevice9_SetSamplerState(dev, 0, D3DSAMP_MINFILTER, D3DTEXF_LINEAR);
    IDirect3DDevice9_SetSamplerState(dev, 0, D3DSAMP_MAGFILTER, D3DTEXF_LINEAR);
    IDirect3DDevice9_SetTextureStageState(dev, 0, D3DTSS_COLOROP, D3DTOP_MODULATE);
    IDirect3DDevice9_SetTextureStageState(dev, 0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
    IDirect3DDevice9_SetTextureStageState(dev, 0, D3DTSS_COLORARG2, D3DTA_DIFFUSE);
    IDirect3DDevice9_SetTextureStageState(dev, 0, D3DTSS_ALPHAOP, D3DTOP_MODULATE);
    IDirect3DDevice9_SetTextureStageState(dev, 0, D3DTSS_ALPHAARG1, D3DTA_TEXTURE);
    IDirect3DDevice9_SetTextureStageState(dev, 0, D3DTSS_ALPHAARG2, D3DTA_DIFFUSE);

    DWORD orange = D3DCOLOR_ARGB(255, 245, 140, 30), white = D3DCOLOR_ARGB(255, 245, 245, 248);
    RECT tl = { 0, (LONG)(g_bh * 0.02f), (LONG)(g_bw * 0.13f), (LONG)(g_bh * 0.02f + g_cellh) };
    put_in_rect(dev, tl, 0.85f, orange, "TACTICS");
    RECT tr = { (LONG)(g_bw * 0.75f), (LONG)(g_bh * 0.006f), (LONG)g_bw, (LONG)(g_bh * 0.006f + g_cellh) };
    put_in_rect(dev, tr, 0.9f, orange, "FORMATION");

    for (int i = 0; i < NBTN; i++)
        put_in_rect(dev, g_btn[i].px, 0.62f, white, g_btn[i].label);

    for (int i = 0; i < g_ncards; i++) {                 // name sits in the dark strip on each chip (set in draw_overlay)
        if (!g_cards[i].px.right) continue;
        char buf[48];
        if (g_cards[i].name[0]) _snprintf(buf, sizeof buf, "%s", g_cards[i].name);
        else _snprintf(buf, sizeof buf, "#%d", g_cards[i].no);
        put_in_rect(dev, g_cards[i].px, 0.46f, white, buf);
    }
}

// ---------------------------------------------------------------- frame dump (proof of what the window shows)
// Writes the picture to wccfpanel_frame.bmp beside the game's exe: once per canvas size, after that size has held
// for 10 frames - so the dump comes after a fullscreen switch has settled, and F11 back to the window dumps again.
static void dump_surface(IDirect3DDevice9 *dev, IDirect3DSurface9 *src)
{
    IDirect3DSurface9 *sys = NULL;
    D3DSURFACE_DESC d; D3DLOCKED_RECT lr;
    char path[MAX_PATH], dir[MAX_PATH], *slash;
    IDirect3DSurface9_GetDesc(src, &d);
    if (d.Format != D3DFMT_X8R8G8B8 && d.Format != D3DFMT_A8R8G8B8) {
        logline("surface format 0x%X not 32-bit; skip dump", d.Format); return;
    }
    HRESULT ho = IDirect3DDevice9_CreateOffscreenPlainSurface(dev, d.Width, d.Height, d.Format, D3DPOOL_SYSTEMMEM, &sys, NULL);
    HRESULT hg = (SUCCEEDED(ho) && sys) ? IDirect3DDevice9_GetRenderTargetData(dev, src, sys) : ho;
    HRESULT hl = SUCCEEDED(hg) ? IDirect3DSurface9_LockRect(sys, &lr, NULL, D3DLOCK_READONLY) : hg;
    if (FAILED(hl)) logline("frame dump failed hr=0x%08lX", (unsigned long)hl);
    if (SUCCEEDED(hl)) {
        GetModuleFileNameA(NULL, dir, MAX_PATH); slash = strrchr(dir, '\\'); if (slash) *slash = 0;
        _snprintf(path, MAX_PATH, "%s\\wccfpanel_frame.bmp", dir);
        FILE *f = fopen(path, "wb");
        if (f) {
            UINT W = d.Width, H = d.Height, rowsz = (W * 3 + 3) & ~3u; DWORD imgsz = rowsz * H;
            BITMAPFILEHEADER fh; ZeroMemory(&fh, sizeof fh);
            BITMAPINFOHEADER ih; ZeroMemory(&ih, sizeof ih);
            fh.bfType = 0x4D42; fh.bfOffBits = sizeof(fh) + sizeof(ih); fh.bfSize = fh.bfOffBits + imgsz;
            ih.biSize = sizeof ih; ih.biWidth = (LONG)W; ih.biHeight = (LONG)H; ih.biPlanes = 1;
            ih.biBitCount = 24; ih.biCompression = BI_RGB; ih.biSizeImage = imgsz;
            fwrite(&fh, sizeof fh, 1, f); fwrite(&ih, sizeof ih, 1, f);
            BYTE *row = (BYTE *)malloc(rowsz);
            if (row) {
                for (int y = (int)H - 1; y >= 0; y--) {
                    BYTE *s = (BYTE *)lr.pBits + (size_t)y * lr.Pitch; ZeroMemory(row, rowsz);
                    for (UINT x = 0; x < W; x++) { BYTE *p = s + x * 4; row[x*3] = p[0]; row[x*3+1] = p[1]; row[x*3+2] = p[2]; }
                    fwrite(row, rowsz, 1, f);
                }
                free(row);
            }
            fclose(f); logline("wrote wccfpanel_frame.bmp (%ux%u)", W, H);
        }
        IDirect3DSurface9_UnlockRect(sys);
    }
    if (sys) IDirect3DSurface9_Release(sys);
}

static UINT g_dump_w = 0, g_dump_h = 0, g_hold_w = 0, g_hold_h = 0;
static int  g_hold_n = 0;

static void maybe_dump(IDirect3DDevice9 *dev, IDirect3DSurface9 *src, UINT w, UINT h)
{
    if (w == g_hold_w && h == g_hold_h) g_hold_n++; else { g_hold_w = w; g_hold_h = h; g_hold_n = 0; }
    if (g_frames >= 30 && g_hold_n >= 10 && (w != g_dump_w || h != g_dump_h)) {
        g_dump_w = w; g_dump_h = h;
        dump_surface(dev, src);
    }
}

// ---------------------------------------------------------------- the baked skin (designed in HTML -> texture)
static IDirect3DTexture9 *g_skin = NULL;
static int g_skin_w = 0, g_skin_h = 0;

static void load_skin(IDirect3DDevice9 *dev)
{
    FILE *f = fopen(g_skin_path, "rb");
    if (!f) { logline("skin.tex not found: %s", g_skin_path); return; }
    unsigned int wh[2];
    if (fread(wh, 8, 1, f) != 1) { fclose(f); return; }
    int w = (int)wh[0], h = (int)wh[1];
    if (FAILED(IDirect3DDevice9_CreateTexture(dev, w, h, 1, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &g_skin, NULL)) || !g_skin) {
        logline("skin CreateTexture failed %dx%d", w, h); fclose(f); return;
    }
    D3DLOCKED_RECT lr;
    if (SUCCEEDED(IDirect3DTexture9_LockRect(g_skin, 0, &lr, NULL, 0))) {
        unsigned char *row = (unsigned char *)malloc((size_t)w * 4);
        if (row) {
            for (int y = 0; y < h; y++) {
                if (fread(row, (size_t)w * 4, 1, f) != 1) break;
                memcpy((unsigned char *)lr.pBits + (size_t)y * lr.Pitch, row, (size_t)w * 4);
            }
            free(row);
        }
        IDirect3DTexture9_UnlockRect(g_skin, 0);
    }
    fclose(f); g_skin_w = w; g_skin_h = h;
    logline("skin loaded %dx%d", w, h);
}

// one textured rectangle; the half-pixel shift is D3D9's texel-to-pixel rule, so a 1:1 draw is crisp, not smeared
static void tex_quad(IDirect3DDevice9 *dev, float x0, float y0, float x1, float y1, float u0, float v0, float u1, float v1)
{
    DWORD c = 0xFFFFFFFF;
    x0 -= 0.5f; y0 -= 0.5f; x1 -= 0.5f; y1 -= 0.5f;
    struct VTXT v[4] = {
        { x0, y0, 0,1, c, u0,v0 }, { x1, y0, 0,1, c, u1,v0 },
        { x0, y1, 0,1, c, u0,v1 }, { x1, y1, 0,1, c, u1,v1 },
    };
    IDirect3DDevice9_DrawPrimitiveUP(dev, D3DPT_TRIANGLESTRIP, 2, v, sizeof(struct VTXT));
}

// the two panel strips of the skin, each pinned to its edge of the canvas (layout() sets the sizes)
static void compact_strip(IDirect3DDevice9 *dev);    // the COMPACT layout's right strip (beside the CLUB CARD button)

static void skin_states(IDirect3DDevice9 *dev)       // drawing from skin.tex, as it is
{
    IDirect3DDevice9_SetFVF(dev, FVF_TEXT);
    IDirect3DDevice9_SetTexture(dev, 0, (IDirect3DBaseTexture9 *)g_skin);
    IDirect3DDevice9_SetSamplerState(dev, 0, D3DSAMP_MINFILTER, D3DTEXF_LINEAR);
    IDirect3DDevice9_SetSamplerState(dev, 0, D3DSAMP_MAGFILTER, D3DTEXF_LINEAR);
    IDirect3DDevice9_SetTextureStageState(dev, 0, D3DTSS_COLOROP, D3DTOP_MODULATE);
    IDirect3DDevice9_SetTextureStageState(dev, 0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
    IDirect3DDevice9_SetTextureStageState(dev, 0, D3DTSS_COLORARG2, D3DTA_DIFFUSE);
    IDirect3DDevice9_SetTextureStageState(dev, 0, D3DTSS_ALPHAOP, D3DTOP_MODULATE);
    IDirect3DDevice9_SetTextureStageState(dev, 0, D3DTSS_ALPHAARG1, D3DTA_TEXTURE);
    IDirect3DDevice9_SetTextureStageState(dev, 0, D3DTSS_ALPHAARG2, D3DTA_DIFFUSE);
}

static void draw_skin(IDirect3DDevice9 *dev)
{
    float y0 = g_py, y1 = g_py + DES_H * g_s;
    if (!g_skin) return;
    skin_states(dev);
    if (!g_compact) tex_quad(dev, 0.0f, y0, g_mx0, y1, 0.0f, 0.0f, DES_L / DES_W, 1.0f);    // left strip
    tex_quad(dev, g_mx1, y0, g_cw, y1, DES_R / DES_W, 0.0f, 1.0f, 1.0f);                     // right strip
    if (g_compact) compact_strip(dev);
}

// ---- letterbox: copy the game's own frame and shrink it into the centre column so the panels never cover it
typedef HRESULT (WINAPI *ResetFn)(IDirect3DDevice9 *, D3DPRESENT_PARAMETERS *);
static ResetFn g_orig_reset = NULL;
static IDirect3DTexture9 *g_gametex = NULL;      // a copy of the game's frame (DEFAULT pool -> released on reset)
static IDirect3DSurface9 *g_gamesurf = NULL;

static void free_gametex(void)
{
    if (g_gamesurf) { IDirect3DSurface9_Release(g_gamesurf); g_gamesurf = NULL; }
    if (g_gametex)  { IDirect3DTexture9_Release(g_gametex);  g_gametex  = NULL; }
}

static int ensure_gametex(IDirect3DDevice9 *dev, UINT w, UINT h)
{
    if (g_gametex) return 1;
    if (FAILED(IDirect3DDevice9_CreateTexture(dev, w, h, 1, D3DUSAGE_RENDERTARGET, D3DFMT_X8R8G8B8,
                                              D3DPOOL_DEFAULT, &g_gametex, NULL)) || !g_gametex) { g_gametex = NULL; return 0; }
    if (FAILED(IDirect3DTexture9_GetSurfaceLevel(g_gametex, 0, &g_gamesurf))) { free_gametex(); return 0; }
    return 1;
}

// the game's frame in the middle column: as big as fits, its own shape kept, centred
static void draw_game_scaled(IDirect3DDevice9 *dev)
{
    if (!g_gametex || !g_gw || !g_gh) return;
    float midW = g_mx1 - g_mx0, a = (float)g_gw / (float)g_gh;
    float gw = midW, gh = midW / a;
    if (gh > g_ch) { gh = g_ch; gw = gh * a; }
    float gx0 = g_mx0 + (midW - gw) * 0.5f, gy0 = (g_ch - gh) * 0.5f;
    IDirect3DDevice9_SetFVF(dev, FVF_TEXT);
    IDirect3DDevice9_SetTexture(dev, 0, (IDirect3DBaseTexture9 *)g_gametex);
    IDirect3DDevice9_SetSamplerState(dev, 0, D3DSAMP_MINFILTER, D3DTEXF_LINEAR);
    IDirect3DDevice9_SetSamplerState(dev, 0, D3DSAMP_MAGFILTER, D3DTEXF_LINEAR);
    IDirect3DDevice9_SetTextureStageState(dev, 0, D3DTSS_COLOROP, D3DTOP_SELECTARG1);
    IDirect3DDevice9_SetTextureStageState(dev, 0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
    IDirect3DDevice9_SetTextureStageState(dev, 0, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
    IDirect3DDevice9_SetTextureStageState(dev, 0, D3DTSS_ALPHAARG1, D3DTA_DIFFUSE);   // opaque (X8 texture has no alpha)
    tex_quad(dev, gx0, gy0, gx0 + gw, gy0 + gh, 0.0f, 0.0f, 1.0f, 1.0f);
}

// ---- our own swap chain: the picture at the window's own size (see the top of the file)
static IDirect3DSwapChain9 *g_sc = NULL;         // DEFAULT pool too: released on reset, remade on the next frame
static UINT g_scw = 0, g_sch = 0;
static HWND g_scwnd = NULL, g_devwnd = NULL;
static int  g_sc_fail = 0;                       // could not be made: old path, window stays windowed
static long g_sc_frames = 0;                     // frames shown through it
static int  g_in_present = 0;                    // re-entry guard (logged if it ever fires)

static void free_sc(void)
{
    if (g_sc) { IDirect3DSwapChain9_Release(g_sc); g_sc = NULL; }
    g_scw = g_sch = 0; g_scwnd = NULL;
}

static int ensure_sc(IDirect3DDevice9 *dev, HWND wnd, UINT w, UINT h)
{
    if (g_sc && g_scw == w && g_sch == h && g_scwnd == wnd) return 1;
    free_sc();
    IDirect3DSwapChain9 *imp = NULL; D3DPRESENT_PARAMETERS ip;
    if (FAILED(IDirect3DDevice9_GetSwapChain(dev, 0, &imp)) || !imp) {
        g_sc_fail = 1; logline("GetSwapChain(0) failed - staying on the old path"); return 0;
    }
    HRESULT hr = IDirect3DSwapChain9_GetPresentParameters(imp, &ip);
    IDirect3DSwapChain9_Release(imp);
    if (FAILED(hr) || !ip.Windowed) {
        g_sc_fail = 1; logline("game device not windowed (hr=0x%08lX) - staying on the old path", (unsigned long)hr); return 0;
    }
    D3DPRESENT_PARAMETERS pp; ZeroMemory(&pp, sizeof pp);
    pp.BackBufferWidth = w; pp.BackBufferHeight = h;
    pp.BackBufferFormat = D3DFMT_X8R8G8B8;
    pp.BackBufferCount = 1;
    pp.SwapEffect = D3DSWAPEFFECT_DISCARD;
    pp.hDeviceWindow = wnd;
    pp.Windowed = TRUE;
    pp.PresentationInterval = ip.PresentationInterval;     // the game's own pacing
    hr = IDirect3DDevice9_CreateAdditionalSwapChain(dev, &pp, &g_sc);
    if (FAILED(hr) || !g_sc) {
        g_sc = NULL; g_sc_fail = 1;
        logline("CreateAdditionalSwapChain %ux%u failed hr=0x%08lX - staying on the old path", w, h, (unsigned long)hr);
        return 0;
    }
    g_scw = w; g_sch = h; g_scwnd = wnd;
    logline("own swap chain %ux%u on window %p (game: %ux%u fmt %d swap %d interval 0x%lX msaa %d)", w, h, (void *)wnd,
            ip.BackBufferWidth, ip.BackBufferHeight, (int)ip.BackBufferFormat, (int)ip.SwapEffect,
            (unsigned long)ip.PresentationInterval, (int)ip.MultiSampleType);
    return 1;
}

static HRESULT WINAPI hook_reset(IDirect3DDevice9 *dev, D3DPRESENT_PARAMETERS *pp)
{
    free_gametex();                 // DEFAULT-pool resources must be gone before a device reset
    free_sc();                      // and our extra swap chain
    g_sc_fail = 0;                  // a reset is a fresh start: try the swap chain again
    if (pp) logline("device reset (game back-buffer %ux%u)", pp->BackBufferWidth, pp->BackBufferHeight);
    return g_orig_reset(dev, pp);
}

// (the white highlight once drawn over a pressed button is gone - the player, 2026-10-05: "this weird white highlight")

// ---------------------------------------------------------------- the card board: the player's cards on the pitch, draggable
// The skin's formation pitch is pitch.png (400x512) drawn at x 1074, y 49, 360 wide on the design sheet
// (measure_skin.js).  Its lines, in the picture's own pixels (measure_pitch.py): touchlines x 12 and 309, goal lines
// y 12 and 451 (the halfway line, 231.5, sits exactly between), five bench boxes x 328..379.  Table units (the
// game's, fpr_table.md 2.6) -> picture: x -1..+1 = touchline to touchline, y -1..+1 = far goal line to OWN goal line.
#define PITCH_X 1074.0f
#define PITCH_Y 49.0f
#define PITCH_SX (360.0f / 400.0f)
#define PITCH_SY (460.8f / 512.0f)
#define FIELD_L 12.0f
#define FIELD_R 309.0f
#define FIELD_T 12.0f
#define FIELD_B 451.0f
#define BENCH_L 328.0f
#define BENCH_R 379.0f
static const float BENCH_BOX[5][2] = { { 46, 115 }, { 130, 199 }, { 214, 282 }, { 298, 367 }, { 382, 451 } };
static const float BENCH_Y[5] = { -0.68f, -0.34f, 0.0f, 0.34f, 0.68f };   // the game's band spots (DAT_00b022b4)
#define BENCH_X 1.24f                    // on the bench strip (x > 1.16), as fpr_panel.py writes it
#define CARD_PW 46.0f                    // a card on the picture: fits a bench box (51 x 69), the face's shape 88:128
#define CARD_PH 67.0f
#define FACE_U (87.5f / 128.0f)          // the face = the left 88 columns of a card picture (measure_cards.py)

static int bench_band(float y)          // the band whose spot is nearest
{
    int b = 0;
    for (int i = 1; i < 5; i++) if (fabsf(BENCH_Y[i] - y) < fabsf(BENCH_Y[b] - y)) b = i;
    return b;
}

// table units -> canvas pixels (the card's centre)
static void table_to_canvas(float x, float y, float *cx, float *cy)
{
    float sx, sy, dx, dy;
    if (x > 1.16f) {                                     // the bench strip: its band's box
        int b = bench_band(y);
        sx = (BENCH_L + BENCH_R) * 0.5f; sy = (BENCH_BOX[b][0] + BENCH_BOX[b][1]) * 0.5f;
    } else {
        sx = FIELD_L + (x + 1.0f) * 0.5f * (FIELD_R - FIELD_L);
        sy = FIELD_T + (y + 1.0f) * 0.5f * (FIELD_B - FIELD_T);
    }
    dx = PITCH_X + sx * PITCH_SX; dy = PITCH_Y + sy * PITCH_SY;            // the design sheet
    *cx = g_cw - (DES_W - dx) * g_s; *cy = g_py + dy * g_s;                 // the right strip, pinned right
}

// canvas pixels -> table units, already where the game takes it: past the touchline = the nearest bench box's spot;
// on the pitch = inside the lines, to 3 decimals (the file's precision)
static void canvas_to_table(float cx, float cy, float *x, float *y)
{
    float dx = DES_W - (g_cw - cx) / g_s, dy = (cy - g_py) / g_s;
    float sx = (dx - PITCH_X) / PITCH_SX, sy = (dy - PITCH_Y) / PITCH_SY, tx, ty;
    if (sx > (FIELD_R + BENCH_L) * 0.5f) {
        int b = 0; float best = 1e9f;
        for (int i = 0; i < 5; i++) {
            float d = fabsf((BENCH_BOX[i][0] + BENCH_BOX[i][1]) * 0.5f - sy);
            if (d < best) { best = d; b = i; }
        }
        *x = BENCH_X; *y = BENCH_Y[b];
        return;
    }
    tx = (sx - FIELD_L) / (FIELD_R - FIELD_L) * 2.0f - 1.0f;
    ty = (sy - FIELD_T) / (FIELD_B - FIELD_T) * 2.0f - 1.0f;
    if (tx < -1.0f) tx = -1.0f;
    if (tx > 1.0f) tx = 1.0f;
    if (ty < -1.0f) ty = -1.0f;
    if (ty > 1.0f) ty = 1.0f;
    *x = floorf(tx * 1000.0f + 0.5f) / 1000.0f;
    *y = floorf(ty * 1000.0f + 0.5f) / 1000.0f;
}

// ---- the card pictures: decoded by the board thread (WIC, on its own COM), made textures on the render thread
#define MAXPICS 160                      // the table's 16 + a couple of pages of the card browser
enum { PIC_WANTED, PIC_DECODING, PIC_DECODED, PIC_READY, PIC_NONE };
struct CardPic { int no, state; UINT w, h; unsigned char *bgra; IDirect3DTexture9 *tex; DWORD used; };
static struct CardPic g_pics[MAXPICS];
static int g_npics = 0;

// the picture entry for a card number, asked for if new (render thread, g_board_cs held)
static struct CardPic *pic_for(int no)
{
    int i, k, old = -1;
    for (i = 0; i < g_npics; i++) if (g_pics[i].no == no) { g_pics[i].used = GetTickCount(); return &g_pics[i]; }
    if (g_npics == MAXPICS) {                // full: forget the longest-unseen one that is not on the table
        for (i = 0; i < g_npics; i++) {
            int on = 0;
            for (k = 0; k < g_ncards; k++) if (g_cards[k].no == g_pics[i].no) on = 1;
            if (!on && g_pics[i].state != PIC_DECODING &&
                (old < 0 || (LONG)(g_pics[i].used - g_pics[old].used) < 0)) old = i;
        }
        if (old < 0) return NULL;
        if (g_pics[old].tex) IDirect3DTexture9_Release(g_pics[old].tex);
        free(g_pics[old].bgra);
        g_pics[old] = g_pics[--g_npics];
    }
    memset(&g_pics[g_npics], 0, sizeof g_pics[0]);
    g_pics[g_npics].no = no;
    g_pics[g_npics].state = PIC_WANTED;
    g_pics[g_npics].used = GetTickCount();
    return &g_pics[g_npics++];
}

// decoded pictures -> MANAGED textures (they survive a device reset); render thread, g_board_cs held
static void board_upload(IDirect3DDevice9 *dev)
{
    for (int i = 0; i < g_npics; i++) {
        struct CardPic *p = &g_pics[i];
        IDirect3DTexture9 *t = NULL; D3DLOCKED_RECT lr;
        if (p->state != PIC_DECODED) continue;
        if (SUCCEEDED(IDirect3DDevice9_CreateTexture(dev, p->w, p->h, 1, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &t, NULL)) && t) {
            if (SUCCEEDED(IDirect3DTexture9_LockRect(t, 0, &lr, NULL, 0))) {
                for (UINT y = 0; y < p->h; y++)
                    memcpy((BYTE *)lr.pBits + (size_t)y * lr.Pitch, p->bgra + (size_t)y * p->w * 4, (size_t)p->w * 4);
                IDirect3DTexture9_UnlockRect(t, 0);
            }
            p->tex = t; p->state = PIC_READY;
        } else p->state = PIC_NONE;
        free(p->bgra); p->bgra = NULL;
    }
}

static unsigned char *decode_png(IWICImagingFactory *wic, int no, UINT *w, UINT *h)
{
    WCHAR path[MAX_PATH]; unsigned char *buf = NULL;
    IWICBitmapDecoder *dec = NULL; IWICBitmapFrameDecode *fr = NULL; IWICFormatConverter *cv = NULL;
    _snwprintf(path, MAX_PATH, L"%s\\%d.png", g_cards_dirw, no);
    path[MAX_PATH - 1] = 0;
    if (SUCCEEDED(IWICImagingFactory_CreateDecoderFromFilename(wic, path, NULL, GENERIC_READ, WICDecodeMetadataCacheOnDemand, &dec)) &&
        SUCCEEDED(IWICBitmapDecoder_GetFrame(dec, 0, &fr)) &&
        SUCCEEDED(IWICImagingFactory_CreateFormatConverter(wic, &cv)) &&
        SUCCEEDED(IWICFormatConverter_Initialize(cv, (IWICBitmapSource *)fr, &GUID_WICPixelFormat32bppBGRA,
                                                 WICBitmapDitherTypeNone, NULL, 0.0, WICBitmapPaletteTypeCustom)) &&
        SUCCEEDED(IWICFormatConverter_GetSize(cv, w, h)) && *w > 0 && *h > 0 && *w <= 512 && *h <= 512) {
        buf = (unsigned char *)malloc((size_t)*w * *h * 4);
        if (buf && FAILED(IWICFormatConverter_CopyPixels(cv, NULL, *w * 4, *w * *h * 4, buf))) { free(buf); buf = NULL; }
    }
    if (cv) IWICFormatConverter_Release(cv);
    if (fr) IWICBitmapFrameDecode_Release(fr);
    if (dec) IWICBitmapDecoder_Release(dec);
    return buf;
}

// the table file changed and it was not us (fpr_panel.py, by hand): take it - never in the middle of a drag
static void board_reread(void)
{
    WIN32_FILE_ATTRIBUTE_DATA a; struct Card fresh[MAXCARDS]; ULONGLONG st; int n, same;
    if (!GetFileAttributesExA(g_table_path, GetFileExInfoStandard, &a)) return;
    EnterCriticalSection(&g_board_cs);
    same = (ft_q(a.ftLastWriteTime) == g_table_stamp) || g_drag >= 0 || g_write_pending;
    LeaveCriticalSection(&g_board_cs);
    if (same) return;
    n = parse_table(fresh, MAXCARDS, &st);
    if (n < 0) return;
    EnterCriticalSection(&g_board_cs);
    if (g_drag < 0 && !g_write_pending) {
        memcpy(g_cards, fresh, sizeof(struct Card) * (size_t)n);
        g_ncards = n; g_table_stamp = st;
        if (g_hover >= n) g_hover = -1;
    }
    LeaveCriticalSection(&g_board_cs);
    logline("board: table read - %d card(s)", n);
}

static void load_catalogue(void);         // the card browser's catalogue (below), loaded by this thread

static DWORD WINAPI board_thread(LPVOID arg)
{
    IWICImagingFactory *wic = NULL;
    (void)arg;
    if (SUCCEEDED(CoInitializeEx(NULL, COINIT_MULTITHREADED)))
        CoCreateInstance(&CLSID_WICImagingFactory, NULL, CLSCTX_INPROC_SERVER, &IID_IWICImagingFactory, (void **)&wic);
    if (!wic) logline("board: no picture decoder (WIC) - cards show as plain numbered tiles");
    load_catalogue();
    for (;;) {
        int no = 0, i, fast;
        board_reread();
        set_tick();                                            // the SETTINGS panel's status, while it is open
        club_tick();                                           // the CLUB CARD panel's view, while it is open
        fast = pad_tick();                                     // the KEYS panel's controllers, while it is open
        EnterCriticalSection(&g_board_cs);                    // one wanted picture at a time, decoded unlocked
        for (i = 0; i < g_npics; i++)
            if (g_pics[i].state == PIC_WANTED) { g_pics[i].state = PIC_DECODING; no = g_pics[i].no; break; }
        LeaveCriticalSection(&g_board_cs);
        if (!no) { Sleep(fast ? 15 : 120); continue; }        // a button press lasts 50 ms or more: read every 15
        UINT w = 0, h = 0;
        unsigned char *bgra = wic ? decode_png(wic, no, &w, &h) : NULL;
        if (!bgra) logline("board: no picture for card %d", no);
        EnterCriticalSection(&g_board_cs);
        for (i = 0; i < g_npics; i++)
            if (g_pics[i].no == no && g_pics[i].state == PIC_DECODING) {
                if (bgra) { g_pics[i].bgra = bgra; g_pics[i].w = w; g_pics[i].h = h; g_pics[i].state = PIC_DECODED; bgra = NULL; }
                else g_pics[i].state = PIC_NONE;
            }
        LeaveCriticalSection(&g_board_cs);
        free(bgra);                                            // only if its entry went away meanwhile
    }
}

static void set_flat(IDirect3DDevice9 *dev)                    // plain coloured shapes
{
    IDirect3DDevice9_SetTexture(dev, 0, NULL);
    IDirect3DDevice9_SetFVF(dev, FVF_2D);
    IDirect3DDevice9_SetTextureStageState(dev, 0, D3DTSS_COLOROP, D3DTOP_SELECTARG1);
    IDirect3DDevice9_SetTextureStageState(dev, 0, D3DTSS_COLORARG1, D3DTA_DIFFUSE);
    IDirect3DDevice9_SetTextureStageState(dev, 0, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
    IDirect3DDevice9_SetTextureStageState(dev, 0, D3DTSS_ALPHAARG1, D3DTA_DIFFUSE);
}

static void set_picture(IDirect3DDevice9 *dev, IDirect3DTexture9 *t, int modulate)   // a texture: as it is, or tinted
{
    IDirect3DDevice9_SetTexture(dev, 0, (IDirect3DBaseTexture9 *)t);
    IDirect3DDevice9_SetFVF(dev, FVF_TEXT);
    IDirect3DDevice9_SetSamplerState(dev, 0, D3DSAMP_MINFILTER, D3DTEXF_LINEAR);
    IDirect3DDevice9_SetSamplerState(dev, 0, D3DSAMP_MAGFILTER, D3DTEXF_LINEAR);
    IDirect3DDevice9_SetTextureStageState(dev, 0, D3DTSS_COLOROP, modulate ? D3DTOP_MODULATE : D3DTOP_SELECTARG1);
    IDirect3DDevice9_SetTextureStageState(dev, 0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
    IDirect3DDevice9_SetTextureStageState(dev, 0, D3DTSS_COLORARG2, D3DTA_DIFFUSE);
    IDirect3DDevice9_SetTextureStageState(dev, 0, D3DTSS_ALPHAOP, modulate ? D3DTOP_MODULATE : D3DTOP_SELECTARG1);
    IDirect3DDevice9_SetTextureStageState(dev, 0, D3DTSS_ALPHAARG1, D3DTA_TEXTURE);
    IDirect3DDevice9_SetTextureStageState(dev, 0, D3DTSS_ALPHAARG2, D3DTA_DIFFUSE);
}

// one card: shadow, dark edge, its real face (or a numbered tile until the picture is in); grow > 1 = lifted/preview.
// Where it was drawn.
static RECT draw_card(IDirect3DDevice9 *dev, int i, float grow, int lifted)
{
    struct Card *c = &g_cards[i];
    struct CardPic *p = pic_for(c->no);
    float cx, cy, w, h, x0, y0, e = g_s > 1.0f ? g_s : 1.0f;
    table_to_canvas(c->x, c->y, &cx, &cy);
    w = CARD_PW * PITCH_SX * g_s * grow; h = CARD_PH * PITCH_SY * g_s * grow;
    x0 = cx - w * 0.5f; y0 = cy - h * 0.5f;
    if (grow > 1.01f) {                                        // a big card stays on the canvas
        if (x0 + w > g_cw - 2.0f) x0 = g_cw - 2.0f - w;
        if (x0 < 2.0f) x0 = 2.0f;
        if (y0 + h > g_ch - 2.0f) y0 = g_ch - 2.0f - h;
        if (y0 < 2.0f) y0 = 2.0f;
    }
    set_flat(dev);
    fill_rect(dev, x0 + 2.0f * e, y0 + 3.0f * e, w, h, D3DCOLOR_ARGB(lifted ? 150 : 95, 0, 0, 0));      // shadow
    fill_rect(dev, x0 - e, y0 - e, w + 2.0f * e, h + 2.0f * e, D3DCOLOR_ARGB(255, 8, 8, 10));            // edge
    if (p && p->state == PIC_READY && p->tex) {
        set_picture(dev, p->tex, 0);
        tex_quad(dev, x0, y0, x0 + w, y0 + h, 0.0f, 0.0f, FACE_U, 1.0f);
    } else {
        char num[16];
        fill_rect(dev, x0, y0, w, h, D3DCOLOR_ARGB(255, 64, 70, 84));
        if (!g_font_tex) build_font(dev);
        if (g_font_tex) {
            set_picture(dev, g_font_tex, 1);
            _snprintf(num, sizeof num, "%d", c->no);
            put_in_rect(dev, RC(x0, y0, x0 + w, y0 + h), 0.5f * g_s, D3DCOLOR_ARGB(255, 240, 240, 245), num);
        }
    }
    return RC(x0, y0, x0 + w, y0 + h);
}

static void board_caption(IDirect3DDevice9 *dev, RECT card, int no);    // with the catalogue (below)
static DWORD line_colour(const char *pos);

// ---- moving cards: drag = move; drop ONTO another card = the two swap places (a bench card onto a pitch card is a
// substitution); right-click = take the card off the table (fpr_panel.py's rule)
static int   g_drop_on = -1;                 // while dragging: the card the dragged one would swap with
static float g_from_x, g_from_y;             // where the dragged card was picked up (table units)

static int card_at_locked(int x, int y, int skip)            // topmost card under a canvas point (not `skip`), -1 = none
{
    for (int i = g_ncards - 1; i >= 0; i--) {
        RECT r = g_cards[i].px;
        if (i != skip && x >= r.left && x < r.right && y >= r.top && y < r.bottom) return i;
    }
    return -1;
}

// all cards: where the mouse can grab them (normal size), then drawn - the lifted one last, on top
static void board_draw(IDirect3DDevice9 *dev)
{
    float w = CARD_PW * PITCH_SX * g_s, h = CARD_PH * PITCH_SY * g_s, cx, cy, e = g_s > 1.0f ? g_s : 1.0f;
    EnterCriticalSection(&g_board_cs);
    board_upload(dev);
    for (int i = 0; i < g_ncards; i++) {
        table_to_canvas(g_cards[i].x, g_cards[i].y, &cx, &cy);
        g_cards[i].px = RC(cx - w * 0.5f, cy - h * 0.5f, cx + w * 0.5f, cy + h * 0.5f);
    }
    for (int i = 0; i < g_ncards; i++) if (i != g_drag) draw_card(dev, i, 1.0f, 0);
    if (g_drag >= 0 && g_drop_on >= 0 && g_drop_on < g_ncards) {   // the card it would swap with: a yellow frame
        RECT r = g_cards[g_drop_on].px;
        set_flat(dev);
        outline(dev, (float)r.left - 3.0f * e, (float)r.top - 3.0f * e, (float)(r.right - r.left) + 6.0f * e,
                (float)(r.bottom - r.top) + 6.0f * e, 3.0f * e, D3DCOLOR_ARGB(255, 255, 214, 40));
    }
    if (g_drag >= 0 && g_drag < g_ncards) draw_card(dev, g_drag, 1.12f, 1);
    else if (g_hover >= 0 && g_hover < g_ncards && GetTickCount() - g_hover_since >= 8000)
        board_caption(dev, draw_card(dev, g_hover, 2.4f, 1), g_cards[g_hover].no);   // resting on a card 8 s: shown big
                                               // enough to read (the player: 350 ms was too eager), with who it is
    LeaveCriticalSection(&g_board_cs);
}

// a press on a card picks it up (window thread); returns the card number, 0 = no card there
static int board_press(HWND h, int x, int y)
{
    int i, no = 0; float cx, cy;
    EnterCriticalSection(&g_board_cs);
    i = card_at_locked(x, y, -1);
    if (i >= 0) {
        table_to_canvas(g_cards[i].x, g_cards[i].y, &cx, &cy);
        g_drag = i; g_drag_dx = cx - (float)x; g_drag_dy = cy - (float)y; g_hover = -1; g_drop_on = -1;
        g_from_x = g_cards[i].x; g_from_y = g_cards[i].y;
        no = g_cards[i].no;
    }
    LeaveCriticalSection(&g_board_cs);
    if (no) SetCapture(h);
    return no;
}

// the card follows the mouse, and the game's table follows the card - at once, no delay (FORMATION_SYNC.md 4.2)
static void board_move(int x, int y)
{
    float tx, ty, cx, cy;
    EnterCriticalSection(&g_board_cs);
    if (g_drag >= 0 && g_drag < g_ncards) {
        struct Card *c = &g_cards[g_drag];
        canvas_to_table((float)x + g_drag_dx, (float)y + g_drag_dy, &tx, &ty);
        if (tx != c->x || ty != c->y) { c->x = tx; c->y = ty; write_table_locked(); }
        table_to_canvas(c->x, c->y, &cx, &cy);                 // its centre over another card = a swap on drop
        g_drop_on = card_at_locked((int)cx, (int)cy, g_drag);
    }
    LeaveCriticalSection(&g_board_cs);
}

// put down: a swap if it is over another card; then one more write of the table (always) and fpr_panel.py's copy
static void board_drop(void)
{
    int i, j;
    EnterCriticalSection(&g_board_cs);
    i = g_drag; j = g_drop_on; g_drag = -1; g_drop_on = -1;
    if (i >= 0 && i < g_ncards) {
        struct Card *c = &g_cards[i];
        if (j >= 0 && j < g_ncards && j != i) {
            struct Card *o = &g_cards[j];
            c->x = o->x; c->y = o->y;                          // it takes the other's place ...
            o->x = g_from_x; o->y = g_from_y;                  // ... and the other goes where it came from
            logline("board: card %d and card %d swapped places", c->no, o->no);
        }
        write_table_locked();
        write_panel_state_locked();
        logline("board: card %d put at %.3f %.3f (%s)%s", c->no, c->x, c->y, c->x > 1.16f ? "bench" :
                (c->y > 0.8f && c->x > -0.2f && c->x < 0.2f) ? "keeper box" : "pitch", g_write_pending ? " - write pending" : "");
    }
    LeaveCriticalSection(&g_board_cs);
}

// right-click on a card: off the table (like lifting it off the real one); returns the card number, 0 = none
static int board_remove(int x, int y)
{
    int i, no = 0;
    EnterCriticalSection(&g_board_cs);
    i = g_drag < 0 ? card_at_locked(x, y, -1) : -1;
    if (i >= 0) {
        no = g_cards[i].no;
        memmove(&g_cards[i], &g_cards[i + 1], sizeof(struct Card) * (size_t)(g_ncards - i - 1));
        g_ncards--; g_hover = -1;
        write_table_locked();
        write_panel_state_locked();
    }
    LeaveCriticalSection(&g_board_cs);
    if (no) logline("board: card %d taken off the table", no);
    return no;
}

static void board_hover(HWND h, int x, int y)
{
    int i;
    EnterCriticalSection(&g_board_cs);
    i = card_at_locked(x, y, -1);
    if (i != g_hover) { g_hover = i; g_hover_since = GetTickCount(); }
    LeaveCriticalSection(&g_board_cs);
    if (i >= 0) {                                              // hear when the mouse leaves the window
        TRACKMOUSEEVENT t; t.cbSize = sizeof t; t.dwFlags = TME_LEAVE; t.hwndTrack = h; t.dwHoverTime = 0;
        TrackMouseEvent(&t);
    }
}

// ---------------------------------------------------------------- the card browser: search the catalogue, add a card
// "+ CARD" (in the skin, left of START) opens it over the middle: a search line (a name or a card number) and a grid
// of real card faces.  A click puts that card on the table where fpr_panel.py would (its line's free 4-4-2 spot, else
// any free one, else the bench), at most 16 (11 on the pitch + 5 on the bench).  While it is open the game window
// carries the property WCCF_TYPING, which _keys_seat1.py honours: letters typed into the search press no buttons.
#define ADD_X0 1084.0f                   // the "+ CARD" button on the design sheet (measure_skin.js)
#define ADD_Y0 529.0f
#define ADD_X1 1196.0f
#define ADD_Y1 569.0f
struct CatCard { int no; char full[48]; char shown[24]; char pos[4]; char club[28]; char nat[28]; char season[16];
                 char rar[16]; unsigned char st[6]; unsigned char total;   // st: offence defence technique power speed stamina
                 unsigned char role[16]; };                     // 1..10 per role (ROLE_NAME), all 0 = not known
// The roles a card suits - what the back of the real card shows on its pitch (the community, 2026-10-08: "a
// back-of-card preview (to check field positions)").  The game keeps them as the first 16 of the player record's
// hidden values (2010-11 catalogue column hidden_params = record +0x237; 2017-18 hidden_4df_523 = record +0x4DF, the
// same field), 1..10.  It names none of them: the names are INFERRED from the players rated 10 in each: CF Drogba
// Ronaldo, TM Ibrahimovic Toni Klose, WG Robben Ribery, SS Del Piero Totti Eto'o, OMF Rui Costa Riquelme Ozil, OH Xavi
// Iniesta Nedved, CMF Lampard Fabregas Alonso, DMF Makelele, SMF Giggs Beckham, WB Cafu Sorin, SB A.Cole Maxwell, CB
// Terry Ferdinand Puyol, STP Cannavaro, CVR Nesta Carvalho Samuel, SW Matthaus Koeman Passarella, GK (only goalkeepers).
// No side: Robben and Ribery rate alike.  2017-18's own new cards (2015-16 on) hold 0 there: no ROLES for them.
static const char *ROLE_NAME[16] = { "CF", "TM", "WG", "SS", "OMF", "OH", "CMF", "DMF", "SMF", "WB", "SB", "CB",
                                     "STP", "CVR", "SW", "GK" };
#define ROLE_GOOD 8                      // a role search word ("dmf") lists cards rated at least this in it
static struct CatCard *g_cat = NULL;     // the catalogue, placeholders left out, sorted by the shown name
static int   g_ncat = 0;
static int   g_browse = 0;               // the browser is open
static char  g_query[28];
static int   g_res[16384], g_nres = 0;   // indices into g_cat that match the query and the filters, in sort order
static int   g_scroll = 0;               // first row shown
static int   g_bhover = -1;              // the result under the mouse (index into g_res)
static int   g_bdetail = -1;             // the card in the stats pane (index into g_cat): the last one pointed at
// filters and sort (the player, 2026-10-05: "add stats ... and have filtering or sorting"); stats are 1..20, total 60..100
static int   g_fpos = 0, g_frar = 0, g_sort = 0;
static const char *POS_CHIP[5]  = { "ALL", "GK", "DF", "MF", "FW" };
static const char *RAR_NAME[6]  = { "", "ALL TIME LEGEND", "LEGEND", "RARE", "SPECIAL", "REGULAR" };   // as in the catalogue
static const char *RAR_CHIP[6]  = { "ANY", "ALL-TIME", "LEGEND", "RARE", "SPECIAL", "REGULAR" };
static const char *SORT_CHIP[8] = { "NAME", "TOTAL", "OFF", "DEF", "TEC", "POW", "SPD", "STA" };
// a range slider per stat (the player: "per stat filtering ... like sliders ... min max"): two handles, low and high
static const char *SL_NAME[7] = { "OFF", "DEF", "TEC", "POW", "SPD", "STA", "TOTAL" };
static const int  SL_MIN[7]  = { 1, 1, 1, 1, 1, 1, 60 }, SL_MAX[7] = { 20, 20, 20, 20, 20, 20, 100 };
static int   g_rlo[7] = { 1, 1, 1, 1, 1, 1, 60 }, g_rhi[7] = { 20, 20, 20, 20, 20, 20, 100 };
static int   g_sdrag = -1;                                // the handle being dragged: slider*2 + (0 low, 1 high); -1 = none
// COUNTRY and CLUB (the player, 2026-10-09: "add countries and club filtering to the catalogue"): a chip each in the
// title line opens a list over the grid - every country (or club) A to Z with its number of cards; typing narrows it,
// a click picks one, ANY clears.  On the card under the mouse, SAME CLUB and SAME COUNTRY pick that card's own (a
// second click clears).  Same nationality raises a pair's link grade and the same club starts a new link higher
// (.work\research\AFFINITY-2010-11.md), so "his countrymen" is how a team that links quickly is found.
struct Pick { char name[28]; int n; };
static struct Pick g_pnat[128], g_pclub[128];             // A to Z, with their numbers of cards (made with the catalogue)
static int   g_npnat = 0, g_npclub = 0;
static char  g_fnat[28], g_fclub[28];                     // the chosen country and club ("" = any)
static int   g_pick = 0;                                  // the list open over the grid: 0 none, 1 country, 2 club
static char  g_pq[28];                                    // what is typed while the list is open
static int   g_pscroll = 0;                               // the list's first row

static void ranges_reset(void)
{
    for (int k = 0; k < 7; k++) { g_rlo[k] = SL_MIN[k]; g_rhi[k] = SL_MAX[k]; }
}
static char  g_bmsg[96];                 // a short note ("KAKA added (12/16)") shown until g_bmsg_until
static DWORD g_bmsg_until = 0, g_bmsg_col = 0;

// UTF-8 name -> plain ASCII for the font and the search: "KAKÀ" -> "KAKA", "IBRAHIMOVIĆ" -> "IBRAHIMOVIC"
static void fold_name(const char *in, char *out, int cap)
{
    WCHAR w[128], d[256]; int k = 0;
    if (!MultiByteToWideChar(CP_UTF8, 0, in, -1, w, 128)) w[0] = 0;
    if (FoldStringW(MAP_COMPOSITE, w, -1, d, 256) <= 0) lstrcpynW(d, w, 256);   // accents become separate marks
    for (WCHAR *p = d; *p && k < cap - 1; p++) {
        const char *sub = NULL;
        if (*p < 128) { out[k++] = (char)*p; continue; }
        switch (*p) {                                          // letters with no accent to drop
            case 0x00D8: sub = "O"; break;  case 0x00F8: sub = "o"; break;
            case 0x00DF: sub = "ss"; break; case 0x0131: sub = "i"; break;
            case 0x0141: sub = "L"; break;  case 0x0142: sub = "l"; break;
            case 0x0110: case 0x00D0: sub = "D"; break;  case 0x0111: case 0x00F0: sub = "d"; break;
            case 0x00C6: sub = "AE"; break; case 0x00E6: sub = "ae"; break;
            case 0x0152: sub = "OE"; break; case 0x0153: sub = "oe"; break;
            default: break;                                    // the accent marks themselves: dropped
        }
        for (; sub && *sub && k < cap - 1; sub++) out[k++] = *sub;
    }
    out[k] = 0;
}

static int cat_cmp(const void *a, const void *b)
{
    const struct CatCard *x = (const struct CatCard *)a, *y = (const struct CatCard *)b;
    int c = lstrcmpiA(x->shown, y->shown);
    return c ? c : x->no - y->no;
}

static int has_text(const char *hay, const char *needle)         // case-insensitive "contains"
{
    size_t n = strlen(needle);
    if (!n) return 1;
    for (; *hay; hay++) if (_strnicmp(hay, needle, n) == 0) return 1;
    return 0;
}

static int res_cmp(const void *a, const void *b)   // the chosen stat, best first; ties by total, then by name
{
    const struct CatCard *x = &g_cat[*(const int *)a], *y = &g_cat[*(const int *)b];
    int vx = g_sort == 1 ? x->total : x->st[g_sort - 2], vy = g_sort == 1 ? y->total : y->st[g_sort - 2];
    if (vx != vy) return vy - vx;
    if (x->total != y->total) return y->total - x->total;
    return *(const int *)a - *(const int *)b;     // g_cat is in name order
}

// One search word against one card (2026-10-08): a name, a club or a country containing it ("milan", "brazil"), a
// season ("2004-05", "2004"), the line exactly ("fw"), or a role exactly ("dmf": rated ROLE_GOOD or more); digits also
// match the card number's start.
static int word_matches(const struct CatCard *c, const char *w)
{
    int k, digits = 1; char num[16];
    for (const char *p = w; *p; p++) if (*p < '0' || *p > '9') digits = 0;
    if (digits) { _snprintf(num, sizeof num, "%d", c->no); if (strncmp(num, w, strlen(w)) == 0) return 1; }
    if (has_text(c->full, w) || has_text(c->shown, w) || has_text(c->club, w) || has_text(c->nat, w) ||
        has_text(c->season, w) || _stricmp(c->pos, w) == 0) return 1;
    for (k = 0; k < 16; k++) if (c->role[k] >= ROLE_GOOD && _stricmp(ROLE_NAME[k], w) == 0) return 1;
    return 0;
}

// g_query + the filters -> g_res, then the sort.  Only digits = card numbers starting so (as before); otherwise every
// word must match (word_matches): "milan 2004-05", "brazil fw", "italy cb", "kaka".
static void run_search_locked(void)
{
    int digits = g_query[0] != 0, nw = 0; size_t ql = strlen(g_query); char num[16], words[sizeof g_query], *w[8], *t;
    for (const char *p = g_query; *p; p++) if (*p < '0' || *p > '9') digits = 0;
    lstrcpynA(words, g_query, sizeof words);
    for (t = strtok(words, " "); t && nw < 8; t = strtok(NULL, " ")) w[nw++] = t;
    g_nres = 0;
    for (int i = 0; i < g_ncat && g_nres < (int)(sizeof g_res / sizeof g_res[0]); i++) {
        const struct CatCard *c = &g_cat[i];
        if (g_fpos && strcmp(c->pos, POS_CHIP[g_fpos]) != 0) continue;
        if (g_frar && strcmp(c->rar, RAR_NAME[g_frar]) != 0) continue;
        if ((g_fnat[0] && strcmp(c->nat, g_fnat) != 0) || (g_fclub[0] && strcmp(c->club, g_fclub) != 0)) continue;
        {
            int k, out = 0;
            for (k = 0; k < 6; k++) if (c->st[k] < g_rlo[k] || c->st[k] > g_rhi[k]) out = 1;
            if (out || c->total < g_rlo[6] || c->total > g_rhi[6]) continue;
        }
        if (digits) { _snprintf(num, sizeof num, "%d", c->no); if (strncmp(num, g_query, ql) != 0) continue; }
        else { int k, ok = 1; for (k = 0; k < nw && ok; k++) ok = word_matches(c, w[k]); if (!ok) continue; }
        g_res[g_nres++] = i;
    }
    if (g_sort && g_nres > 1) qsort(g_res, (size_t)g_nres, sizeof g_res[0], res_cmp);
    g_scroll = 0; g_bhover = -1;
}

static void picks_add(struct Pick *p, int *n, int cap, const char *name)   // one more card of this country / club
{
    if (!name[0]) return;                                  // no club (25 cards), no country (1): only under ANY
    for (int i = 0; i < *n; i++) if (strcmp(p[i].name, name) == 0) { p[i].n++; return; }
    if (*n < cap) { lstrcpynA(p[*n].name, name, sizeof p[0].name); p[*n].n = 1; (*n)++; }
}

static int pick_cmp(const void *a, const void *b)
{
    return lstrcmpiA(((const struct Pick *)a)->name, ((const struct Pick *)b)->name);
}

// .work\playercards1011\catalogue.tsv (one card per line, tab-separated, UTF-8): 0 card_no, 5 season, 7 rarity_name,
// 9 is_placeholder, 10 name_full_latin, 11 name_short_latin, 15 position_name, 17 club_name, 19 nationality_name,
// 24-29 the six stats (offence defence technique power speed stamina, 1..20), 30 stats_total, 40 hidden_params (its
// first 16: the roles; 2017-18 calls it hidden_4df_523 at 45 - nationality and roles are found by the header's names).
// Board thread, once.
static void load_catalogue(void)
{
    static struct Pick pn[128], pc[128];                   // the lists, made here and copied in under the lock
    int col_nat = 19, col_role = -1;
    char line[8192]; int n = 0, cap = 16384, k, npn = 0, npc = 0; struct CatCard *a; FILE *f = fopen(g_cat_path, "rb");
    if (!f) { logline("browser: no catalogue at %s", g_cat_path); return; }
    a = (struct CatCard *)calloc((size_t)cap, sizeof *a);
    if (!a) { fclose(f); return; }
    while (fgets(line, sizeof line, f) && n < cap) {
        char *fld[64], *p = line; int nf = 1;
        fld[0] = line;
        for (; *p && nf < 64; p++) if (*p == '\t' || *p == '\r' || *p == '\n') { *p = 0; if (nf < 64) fld[nf++] = p + 1; }
        if (strcmp(fld[0], "card_no") == 0) {                          // the header: where this catalogue keeps them
            for (k = 0; k < nf; k++) {
                if (strcmp(fld[k], "nationality_name") == 0) col_nat = k;
                if (strcmp(fld[k], "hidden_params") == 0 || strcmp(fld[k], "hidden_4df_523") == 0) col_role = k;
            }
            continue;
        }
        if (nf < 31 || fld[0][0] < '1' || fld[0][0] > '9' || strcmp(fld[9], "1") == 0) continue;   // placeholders
        a[n].no = atoi(fld[0]);
        fold_name(fld[10], a[n].full, sizeof a[n].full);
        fold_name(fld[11], a[n].shown, sizeof a[n].shown);
        fold_name(fld[17], a[n].club, sizeof a[n].club);
        if (col_nat < nf) fold_name(fld[col_nat], a[n].nat, sizeof a[n].nat);
        lstrcpynA(a[n].pos, fld[15], sizeof a[n].pos);
        lstrcpynA(a[n].season, fld[5], sizeof a[n].season);
        lstrcpynA(a[n].rar, fld[7], sizeof a[n].rar);
        for (k = 0; k < 6; k++) a[n].st[k] = (unsigned char)atoi(fld[24 + k]);
        a[n].total = (unsigned char)atoi(fld[30]);
        if (col_role >= 0 && col_role < nf) {             // "v v v ...": the first 16 are the roles, kept only if all 1..10
            const char *q = fld[col_role]; int ok = 1;
            for (k = 0; k < 16 && ok; k++) {
                char *end; long v = strtol(q, &end, 10);
                ok = end != q && v >= 1 && v <= 10;
                a[n].role[k] = (unsigned char)v;
                q = end;
            }
            if (!ok) memset(a[n].role, 0, sizeof a[n].role);
        }
        if (a[n].no > 0) n++;
    }
    fclose(f);
    qsort(a, (size_t)n, sizeof *a, cat_cmp);
    for (k = 0; k < n; k++) { picks_add(pn, &npn, 128, a[k].nat); picks_add(pc, &npc, 128, a[k].club); }
    qsort(pn, (size_t)npn, sizeof pn[0], pick_cmp);
    qsort(pc, (size_t)npc, sizeof pc[0], pick_cmp);
    EnterCriticalSection(&g_board_cs);
    g_cat = a; g_ncat = n;
    memcpy(g_pnat, pn, sizeof pn[0] * (size_t)npn); g_npnat = npn;
    memcpy(g_pclub, pc, sizeof pc[0] * (size_t)npc); g_npclub = npc;
    if (g_browse) run_search_locked();
    LeaveCriticalSection(&g_board_cs);
    logline("browser: catalogue %d cards, %d countries, %d clubs", n, npn, npc);
}

// "ROLES  DMF 10   CMF 7   CVR 5": a card's best three roles (ROLE_NAME), "" when the catalogue has none
static void role_line(const struct CatCard *c, char *out, size_t cap)
{
    int best[3] = { -1, -1, -1 }, b, k, n = 0;
    for (b = 0; b < 3; b++)
        for (k = 0; k < 16; k++)
            if (c->role[k] && k != best[0] && k != best[1] && (best[b] < 0 || c->role[k] > c->role[best[b]])) best[b] = k;
    out[0] = 0;
    for (b = 0; b < 3 && best[b] >= 0 && n >= 0 && (size_t)n < cap; b++)
        n += _snprintf(out + n, cap - (size_t)n, "%s%s %d", b ? "   " : "ROLES  ", ROLE_NAME[best[b]], c->role[best[b]]);
    out[cap - 1] = 0;
}

// under (or over) the big card on the board - resting on a card 8 s - who it is, its line and total, its best roles
// (the community, 2026-10-08: "many new cards are unfamiliar").  g_board_cs held.
static void board_caption(IDirect3DDevice9 *dev, RECT card, int no)
{
    const struct CatCard *c = NULL; char a[96], b[96]; float s = g_s, w, h = 46.0f * s, x, y; int i;
    for (i = 0; i < g_ncat && !c; i++) if (g_cat[i].no == no) c = &g_cat[i];
    if (!c || !g_font_tex) return;
    _snprintf(a, sizeof a, "%s   %s %d", c->full[0] ? c->full : c->shown, c->pos, c->total); a[sizeof a - 1] = 0;
    role_line(c, b, sizeof b);
    w = (float)(card.right - card.left) + 80.0f * s;
    x = (float)(card.left + card.right) * 0.5f - w * 0.5f;
    if (x + w > g_cw - 2.0f) x = g_cw - 2.0f - w;
    if (x < 2.0f) x = 2.0f;
    y = (float)card.bottom + 6.0f * s;
    if (y + h > g_ch - 2.0f) y = (float)card.top - 6.0f * s - h;
    set_flat(dev);
    fill_rect(dev, x, y, w, h, D3DCOLOR_ARGB(235, 18, 20, 26));
    set_picture(dev, g_font_tex, 1);
    put_in_rect(dev, RC(x, y + 3.0f * s, x + w, y + 23.0f * s), 0.44f * s, line_colour(c->pos), a);
    if (b[0]) put_in_rect(dev, RC(x, y + 23.0f * s, x + w, y + 43.0f * s), 0.40f * s, D3DCOLOR_ARGB(255, 240, 240, 245), b);
}

static void note_locked(DWORD col, const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt); _vsnprintf(g_bmsg, sizeof g_bmsg - 1, fmt, ap); va_end(ap);
    g_bmsg[sizeof g_bmsg - 1] = 0;
    g_bmsg_until = GetTickCount() + 2500; g_bmsg_col = col;
}

static int spot_taken_locked(float x, float y)
{
    for (int i = 0; i < g_ncards; i++) if (fabsf(g_cards[i].x - x) < 0.005f && fabsf(g_cards[i].y - y) < 0.005f) return 1;
    return 0;
}

// on the table where fpr_panel.py would put it (default_spot): its own line's free 4-4-2 spot, else any free one,
// else the first free bench box; the lowest free slot number
static void board_add_locked(const struct CatCard *c)
{
    static const struct { char line[3]; float x, y; } spots[11] = {
        { "GK", 0.0f, 0.9f },
        { "DF", -0.6f, 0.55f }, { "DF", -0.2f, 0.6f }, { "DF", 0.2f, 0.6f }, { "DF", 0.6f, 0.55f },
        { "MF", -0.6f, 0.1f }, { "MF", -0.2f, 0.15f }, { "MF", 0.2f, 0.15f }, { "MF", 0.6f, 0.1f },
        { "FW", -0.25f, -0.45f }, { "FW", 0.25f, -0.45f } };
    const char *order[5] = { c->pos, "DF", "MF", "FW", "GK" };
    int i, l, slot, on_field = 0, found = 0; float x = 0.0f, y = 0.0f;
    for (i = 0; i < g_ncards; i++)
        if (g_cards[i].no == c->no) { note_locked(D3DCOLOR_ARGB(255, 255, 214, 40), "%s is already on the table", c->shown); return; }
    if (g_ncards >= MAXCARDS) {
        note_locked(D3DCOLOR_ARGB(255, 255, 110, 90), "the table is full: 16 cards (right-click one to take it off)"); return;
    }
    for (i = 0; i < g_ncards; i++) if (g_cards[i].x <= 1.16f) on_field++;
    if (on_field < 11)
        for (l = 0; l < 5 && !found; l++)
            for (i = 0; i < 11 && !found; i++)
                if (strcmp(spots[i].line, order[l]) == 0 && !spot_taken_locked(spots[i].x, spots[i].y)) {
                    x = spots[i].x; y = spots[i].y; found = 1;
                }
    for (i = 0; i < 5 && !found; i++)
        if (!spot_taken_locked(BENCH_X, BENCH_Y[i])) { x = BENCH_X; y = BENCH_Y[i]; found = 1; }
    if (!found) { note_locked(D3DCOLOR_ARGB(255, 255, 110, 90), "no free place: right-click a card to take it off"); return; }
    for (slot = 1; slot <= MAXCARDS; slot++) {
        int used = 0;
        for (i = 0; i < g_ncards; i++) if (g_cards[i].slot == slot) used = 1;
        if (!used) break;
    }
    memset(&g_cards[g_ncards], 0, sizeof g_cards[0]);
    g_cards[g_ncards].slot = slot; g_cards[g_ncards].no = c->no; g_cards[g_ncards].x = x; g_cards[g_ncards].y = y;
    g_ncards++;
    write_table_locked();
    write_panel_state_locked();
    note_locked(D3DCOLOR_ARGB(255, 120, 230, 120), "%s added (%d/16)", c->shown, g_ncards);
    logline("browser: card %d (%s) added - slot %d at %.3f %.3f", c->no, c->shown, slot, x, y);
}

// the browser's parts, in canvas pixels (it covers the middle column): title + X, the search line, a row of filter
// chips (POSITION, RARITY), a row of sort chips, then the card grid on the left and the stats pane on the right
// sliders: blocks of four per row (OFF DEF TEC POW / SPD STA TOTAL + RESET); in a block: name, track, values
struct Geo { float x0, x1, gx0, gy0, tw, th, cw, ch, lab_rar; int cols, rows;
             RECT close, box, pos[5], rar[6], sort[8], sl[7], reset, pane; float tx0[7], tx1[7];
             RECT nat, club; float lab_nat, lab_club, px0, pcw, pch, pstep; int pcols, prows; };  // COUNTRY / CLUB + their list

static float chip_row(RECT *out, const char **labels, int n, float x, float y, float s)   // chips left to right
{
    for (int i = 0; i < n; i++) {
        float w = ((float)strlen(labels[i]) * 7.0f + 18.0f) * s;
        out[i] = RC(x, y, x + w, y + 24.0f * s);
        x += w + 6.0f * s;
    }
    return x;
}

static void browse_geo(struct Geo *g)
{
    float s = g_s, x, room;
    g->x0 = g_mx0; g->x1 = g_mx1;
    g->close = RC(g->x1 - 58.0f * s, 12.0f * s, g->x1 - 18.0f * s, 50.0f * s);
    g->club = RC((float)g->close.left - 206.0f * s, 20.0f * s, (float)g->close.left - 16.0f * s, 44.0f * s);   // in the
    g->lab_club = (float)g->club.left - 44.0f * s;                                  // title line: a new row would cost
    g->nat = RC(g->lab_club - 206.0f * s, 20.0f * s, g->lab_club - 16.0f * s, 44.0f * s);   // the grid a row of cards
    g->lab_nat = (float)g->nat.left - 70.0f * s;
    g->box = RC(g->x0 + 24.0f * s, 54.0f * s, g->x1 - 24.0f * s, 90.0f * s);
    x = chip_row(g->pos, POS_CHIP, 5, g->x0 + 108.0f * s, 98.0f * s, s);
    g->lab_rar = x + 14.0f * s;
    chip_row(g->rar, RAR_CHIP, 6, x + 88.0f * s, 98.0f * s, s);
    chip_row(g->sort, SORT_CHIP, 8, g->x0 + 108.0f * s, 128.0f * s, s);
    {                                                // the sliders: two rows of four blocks across the browser
        float bx0 = g->x0 + 24.0f * s, bw = ((g->x1 - 24.0f * s) - bx0 - 3.0f * 16.0f * s) / 4.0f;
        for (int k = 0; k < 8; k++) {
            float bx = bx0 + (float)(k % 4) * (bw + 16.0f * s), by = (k < 4 ? 160.0f : 190.0f) * s;
            if (k < 7) {
                g->sl[k] = RC(bx, by, bx + bw, by + 24.0f * s);
                g->tx0[k] = bx + 50.0f * s; g->tx1[k] = bx + bw - 62.0f * s;
            } else g->reset = RC(bx, by, bx + 70.0f * s, by + 24.0f * s);
        }
    }
    g->pane = RC(g->x1 - 300.0f * s, 222.0f * s, g->x1 - 16.0f * s, g_ch - 16.0f * s);
    g->tw = 84.0f * s; g->th = 122.0f * s;           // a card: the face's shape (88:128)
    g->cw = 104.0f * s; g->ch = 160.0f * s;          // its cell: the card, its name, position + total, a gap
    g->gy0 = 224.0f * s;
    room = (float)g->pane.left - 16.0f * s - (g->x0 + 16.0f * s);
    g->cols = (int)(room / g->cw); if (g->cols < 1) g->cols = 1;
    g->rows = (int)((g_ch - g->gy0 - 8.0f * s) / g->ch); if (g->rows < 1) g->rows = 1;
    g->gx0 = g->x0 + 16.0f * s + (room - g->cols * g->cw) * 0.5f;
    {                                                // the COUNTRY / CLUB list: over the grid and the stats pane
        float avail = (g->x1 - 16.0f * s) - (g->x0 + 16.0f * s);
        g->px0 = g->x0 + 16.0f * s;
        g->pcols = (int)((avail + 8.0f * s) / (208.0f * s)); if (g->pcols < 1) g->pcols = 1;
        g->pcw = (avail - (float)(g->pcols - 1) * 8.0f * s) / (float)g->pcols;
        g->pch = 24.0f * s; g->pstep = 28.0f * s;
        g->prows = (int)((g_ch - g->gy0 - 8.0f * s) / g->pstep); if (g->prows < 1) g->prows = 1;
    }
}

static DWORD line_colour(const char *pos)         // GK yellow, DF blue, MF green, FW red (as the pitch's zones)
{
    return pos[0] == 'G' ? D3DCOLOR_ARGB(255, 245, 205, 60) : pos[0] == 'D' ? D3DCOLOR_ARGB(255, 110, 160, 245) :
           pos[0] == 'M' ? D3DCOLOR_ARGB(255, 110, 210, 120) : D3DCOLOR_ARGB(255, 240, 105, 95);
}

static void draw_chip(IDirect3DDevice9 *dev, RECT r, const char *label, int on, float s)   // one chip; on = orange
{
    float x = (float)r.left, y = (float)r.top, w = (float)(r.right - r.left), h = (float)(r.bottom - r.top);
    set_flat(dev);
    fill_rect(dev, x, y, w, h, on ? D3DCOLOR_ARGB(255, 255, 138, 42) : D3DCOLOR_ARGB(255, 38, 41, 52));
    if (!on) outline(dev, x, y, w, h, 1.0f, D3DCOLOR_ARGB(255, 70, 75, 90));
    if (g_font_tex) {
        set_picture(dev, g_font_tex, 1);
        put_in_rect(dev, r, 0.42f * s, on ? D3DCOLOR_ARGB(255, 25, 18, 8) : D3DCOLOR_ARGB(255, 210, 214, 224), label);
    }
}

static void draw_chips(IDirect3DDevice9 *dev, const RECT *r, const char **labels, int n, int on, float s)
{
    for (int i = 0; i < n; i++) draw_chip(dev, r[i], labels[i], i == on, s);
}

// the stats pane: the card big, its name, line and club, season and rarity, the six stats as bars, the total
static void draw_pane(IDirect3DDevice9 *dev, const struct Geo *g, float s)
{
    static const char *SN[6] = { "OFF", "DEF", "TEC", "POW", "SPD", "STA" };
    DWORD white = D3DCOLOR_ARGB(255, 240, 240, 245), grey = D3DCOLOR_ARGB(255, 150, 156, 170);
    float px = (float)g->pane.left + 16.0f * s, pw = (float)(g->pane.right - g->pane.left) - 32.0f * s, y;
    const struct CatCard *c = (g_bdetail >= 0 && g_bdetail < g_ncat) ? &g_cat[g_bdetail] : NULL;
    char line[96]; int on = 0, k;
    set_flat(dev);
    fill_rect(dev, (float)g->pane.left, (float)g->pane.top, (float)(g->pane.right - g->pane.left),
              (float)(g->pane.bottom - g->pane.top), D3DCOLOR_ARGB(255, 22, 24, 31));
    fill_rect(dev, (float)g->pane.left, (float)g->pane.top, (float)(g->pane.right - g->pane.left), 3.0f * s,
              D3DCOLOR_ARGB(255, 255, 138, 42));
    if (!c) {
        if (g_font_tex) {
            set_picture(dev, g_font_tex, 1);
            put_in_rect(dev, RC(px, (float)g->pane.top + 40.0f * s, px + pw, (float)g->pane.top + 70.0f * s), 0.44f * s, grey,
                        "point at a card to see its stats");
        }
        return;
    }
    for (k = 0; k < g_ncards; k++) if (g_cards[k].no == c->no) on = 1;
    {                                                                   // the card itself, big
        struct CardPic *p = pic_for(c->no);
        float cw = 176.0f * s, ch = 256.0f * s, cx = (float)g->pane.left + ((float)(g->pane.right - g->pane.left) - cw) * 0.5f;
        y = (float)g->pane.top + 16.0f * s;
        fill_rect(dev, cx - 2.0f * s, y - 2.0f * s, cw + 4.0f * s, ch + 4.0f * s, D3DCOLOR_ARGB(255, 6, 6, 8));
        if (p && p->state == PIC_READY && p->tex) {
            set_picture(dev, p->tex, 0);
            tex_quad(dev, cx, y, cx + cw, y + ch, 0.0f, 0.0f, FACE_U, 1.0f);
        } else fill_rect(dev, cx, y, cw, ch, D3DCOLOR_ARGB(255, 52, 57, 70));
        y += ch + 12.0f * s;
    }
    if (!g_font_tex) return;
    set_picture(dev, g_font_tex, 1);
    put_in_rect(dev, RC(px, y, px + pw, y + 26.0f * s), 0.58f * s, white, c->full[0] ? c->full : c->shown);
    y += 28.0f * s;
    _snprintf(line, sizeof line, "%s  -  %s  -  %s", c->pos, c->club[0] ? c->club : "-", c->nat[0] ? c->nat : "-");
    put_in_rect(dev, RC(px, y, px + pw, y + 20.0f * s), 0.42f * s, line_colour(c->pos), line);
    y += 20.0f * s;
    _snprintf(line, sizeof line, "%s  -  %s  -  #%d", c->season, c->rar, c->no);
    put_in_rect(dev, RC(px, y, px + pw, y + 20.0f * s), 0.40f * s, grey, line);
    y += 30.0f * s;
    for (k = 0; k < 6; k++) {                                           // the six stats, 1..20, as bars
        float bx = px + 46.0f * s, bw = pw - 46.0f * s - 34.0f * s, v = (float)c->st[k] / 20.0f;
        DWORD col = c->st[k] >= 17 ? D3DCOLOR_ARGB(255, 95, 205, 105) : c->st[k] >= 13 ? D3DCOLOR_ARGB(255, 232, 196, 60)
                                                                       : D3DCOLOR_ARGB(255, 232, 120, 70);
        set_picture(dev, g_font_tex, 1);
        put_str(dev, px, y, 0.42f * s, grey, SN[k]);
        set_flat(dev);
        fill_rect(dev, bx, y + 3.0f * s, bw, 12.0f * s, D3DCOLOR_ARGB(255, 44, 48, 60));
        fill_rect(dev, bx, y + 3.0f * s, bw * (v > 1.0f ? 1.0f : v), 12.0f * s, col);
        _snprintf(line, sizeof line, "%d", c->st[k]);
        set_picture(dev, g_font_tex, 1);
        put_str(dev, bx + bw + 8.0f * s, y, 0.42f * s, white, line);
        y += 25.0f * s;
    }
    y += 6.0f * s;
    _snprintf(line, sizeof line, "TOTAL  %d", c->total);
    put_in_rect(dev, RC(px, y, px + pw, y + 30.0f * s), 0.66f * s, D3DCOLOR_ARGB(255, 255, 138, 42), line);
    y += 34.0f * s;
    role_line(c, line, sizeof line);                                    // its best three roles (ROLE_NAME)
    if (line[0]) {
        put_in_rect(dev, RC(px, y, px + pw, y + 22.0f * s), 0.46f * s, white, line);
        put_in_rect(dev, RC(px, y + 22.0f * s, px + pw, y + 38.0f * s), 0.34f * s, grey,
                    "out of 10 - role names inferred, not the game's");
        y += 44.0f * s;
    }
    put_in_rect(dev, RC(px, y, px + pw, y + 20.0f * s), 0.40f * s, on ? D3DCOLOR_ARGB(255, 255, 214, 40) : grey,
                on ? "ON THE TABLE" : "click its card to put it on the table");
}

static int browse_hit_locked(const struct Geo *g, int x, int y)  // the result under a canvas point, -1 = none
{
    int col, row, r; float tx, ty;
    if (g_pick || x < g->gx0 || y < g->gy0) return -1;          // the COUNTRY / CLUB list covers the grid
    col = (int)((x - g->gx0) / g->cw); row = (int)((y - g->gy0) / g->ch);
    if (col >= g->cols || row >= g->rows) return -1;
    tx = g->gx0 + col * g->cw + (g->cw - g->tw) * 0.5f; ty = g->gy0 + row * g->ch;
    if (x < tx || x >= tx + g->tw || y < ty || y >= ty + g->th + 38.0f * g_s) return -1;
    r = (g_scroll + row) * g->cols + col;
    return r < g_nres ? r : -1;
}

static RECT add_button(void)               // "+ CARD" on the canvas (it sits in the right strip)
{
    return grown(RC(g_cw - (DES_W - ADD_X0) * g_s, g_py + ADD_Y0 * g_s, g_cw - (DES_W - ADD_X1) * g_s,
                    g_py + ADD_Y1 * g_s), GROW_RIGHT);
}

static void log_filters_locked(void)       // one line for the log (and the tests): what the browser shows now
{
    char rg[160] = ""; int n = 0;
    for (int k = 0; k < 7; k++)
        if (g_rlo[k] != SL_MIN[k] || g_rhi[k] != SL_MAX[k])
            n += _snprintf(rg + n, sizeof rg - n, " %s %d-%d", SL_NAME[k], g_rlo[k], g_rhi[k]);
    logline("browser: %s, %s, country %s, club %s, sorted by %s, ranges%s - %d found%s%s", POS_CHIP[g_fpos],
            RAR_CHIP[g_frar], g_fnat[0] ? g_fnat : "any", g_fclub[0] ? g_fclub : "any", SORT_CHIP[g_sort],
            rg[0] ? rg : " all", g_nres, g_nres ? ", first " : "", g_nres ? g_cat[g_res[0]].shown : "");
}

static int pick_list_locked(int *out, int cap)   // the open list's entries: -1 = ANY (nothing typed), else a table index
{
    const struct Pick *p = g_pick == 1 ? g_pnat : g_pclub;
    int n = g_pick == 1 ? g_npnat : g_npclub, k = 0;
    if (!g_pq[0] && k < cap) out[k++] = -1;
    for (int i = 0; i < n && k < cap; i++) if (has_text(p[i].name, g_pq)) out[k++] = i;
    return k;
}

static int pick_visible(const struct Geo *g, int v)  // entry v of the list is on screen (after its scroll)
{
    int row = v / g->pcols - g_pscroll;
    return row >= 0 && row < g->prows;
}

static RECT pick_rect(const struct Geo *g, int v)    // entry v of the list on the canvas: left to right, then down
{
    int row = v / g->pcols - g_pscroll, col = v % g->pcols;
    float x = g->px0 + (float)col * (g->pcw + 8.0f * g_s), y = g->gy0 + (float)row * g->pstep;
    return RC(x, y, x + g->pcw, y + g->pch);
}

static void pick_scroll_locked(const struct Geo *g, int by)   // the list moves by rows, within its length
{
    int list[160], n = pick_list_locked(list, 160), last = (n + g->pcols - 1) / g->pcols - g->prows;
    g_pscroll += by;
    if (g_pscroll > last) g_pscroll = last;
    if (g_pscroll < 0) g_pscroll = 0;
}

static void pick_choose_locked(int idx)          // entry idx of the open list (-1 = ANY) is the filter now; it closes
{
    char *f = g_pick == 1 ? g_fnat : g_fclub;
    const struct Pick *p = g_pick == 1 ? g_pnat : g_pclub;
    if (idx < 0) f[0] = 0; else lstrcpynA(f, p[idx].name, sizeof g_fnat);
    g_pick = 0; g_pq[0] = 0; g_pscroll = 0;
    run_search_locked();
    log_filters_locked();
}

static void same_toggle_locked(char *f, const char *v)   // SAME CLUB / SAME COUNTRY: the card's own, or off again
{
    if (strcmp(f, v) == 0) f[0] = 0; else lstrcpynA(f, v, sizeof g_fnat);
    run_search_locked();
    log_filters_locked();
}

// the card under the mouse (result r): its SAME CLUB and SAME COUNTRY chips over the bottom of its face; 0 = not shown
static int card_minis(const struct Geo *g, int r, RECT *club, RECT *nat)
{
    int row = r / g->cols - g_scroll, col = r % g->cols; float s = g_s;
    float tx = g->gx0 + col * g->cw + (g->cw - g->tw) * 0.5f, ty = g->gy0 + row * g->ch;
    *club = RC(tx + 3.0f * s, ty + g->th - 46.0f * s, tx + g->tw - 3.0f * s, ty + g->th - 25.0f * s);
    *nat = RC(tx + 3.0f * s, ty + g->th - 23.0f * s, tx + g->tw - 3.0f * s, ty + g->th - 2.0f * s);
    return row >= 0 && row < g->rows;
}

// the COUNTRY / CLUB list over the grid and the stats pane: a chip per entry, the name left and its cards right
static void draw_picker(IDirect3DDevice9 *dev, const struct Geo *g, float s)
{
    static int list[160];
    const struct Pick *p = g_pick == 1 ? g_pnat : g_pclub; const char *cur = g_pick == 1 ? g_fnat : g_fclub;
    int n = pick_list_locked(list, 160); char num[16];
    for (int v = 0; v < n; v++) {
        const char *name = list[v] < 0 ? "ANY" : p[list[v]].name;
        int on = list[v] < 0 ? !cur[0] : strcmp(cur, name) == 0;
        RECT r;
        if (!pick_visible(g, v)) continue;
        r = pick_rect(g, v);
        draw_chip(dev, r, "", on, s);
        if (!g_font_tex) continue;
        set_picture(dev, g_font_tex, 1);
        put_str(dev, (float)r.left + 10.0f * s, (float)r.top + 5.0f * s, 0.42f * s,
                on ? D3DCOLOR_ARGB(255, 25, 18, 8) : D3DCOLOR_ARGB(255, 222, 226, 236), name);
        if (list[v] < 0) continue;
        _snprintf(num, sizeof num, "%d", p[list[v]].n);
        put_str(dev, (float)r.right - 10.0f * s - str_w(num, 0.42f * s), (float)r.top + 5.0f * s, 0.42f * s,
                on ? D3DCOLOR_ARGB(255, 25, 18, 8) : D3DCOLOR_ARGB(255, 150, 156, 170), num);
    }
    if (!n && g_font_tex) {
        set_picture(dev, g_font_tex, 1);
        put_str(dev, g->px0, g->gy0 + 6.0f * s, 0.46f * s, D3DCOLOR_ARGB(255, 150, 156, 170),
                "nothing matches what you typed - Backspace takes a letter off");
    }
}

static void slider_move(int x)             // the dragged handle to the value under x (the list follows at once)
{
    struct Geo g; int k, high, v; float t;
    EnterCriticalSection(&g_board_cs);
    if (g_sdrag >= 0) {
        browse_geo(&g);
        k = g_sdrag / 2; high = g_sdrag & 1;
        t = ((float)x - g.tx0[k]) / (g.tx1[k] - g.tx0[k]);
        v = SL_MIN[k] + (int)floorf(t * (float)(SL_MAX[k] - SL_MIN[k]) + 0.5f);
        if (v < SL_MIN[k]) v = SL_MIN[k];
        if (v > SL_MAX[k]) v = SL_MAX[k];
        if (!high && v > g_rhi[k]) v = g_rhi[k];
        if (high && v < g_rlo[k]) v = g_rlo[k];
        if (high ? v != g_rhi[k] : v != g_rlo[k]) {
            if (high) g_rhi[k] = v; else g_rlo[k] = v;
            run_search_locked();
        }
    }
    LeaveCriticalSection(&g_board_cs);
}

static void slider_end(void)
{
    EnterCriticalSection(&g_board_cs);
    if (g_sdrag >= 0) { g_sdrag = -1; log_filters_locked(); }
    LeaveCriticalSection(&g_board_cs);
}

// the seven range sliders: name, track, the chosen range in orange between two handles, the values (or "any"); RESET
static void draw_sliders(IDirect3DDevice9 *dev, const struct Geo *g, float s)
{
    DWORD orange = D3DCOLOR_ARGB(255, 255, 138, 42), grey = D3DCOLOR_ARGB(255, 150, 156, 170);
    char v[24];
    for (int k = 0; k < 7; k++) {
        float y = (float)g->sl[k].top, cy = y + 12.0f * s, t0 = g->tx0[k], t1 = g->tx1[k];
        float span = (float)(SL_MAX[k] - SL_MIN[k]);
        float xl = t0 + (t1 - t0) * (float)(g_rlo[k] - SL_MIN[k]) / span, xh = t0 + (t1 - t0) * (float)(g_rhi[k] - SL_MIN[k]) / span;
        int full = g_rlo[k] == SL_MIN[k] && g_rhi[k] == SL_MAX[k];
        set_flat(dev);
        fill_rect(dev, t0, cy - 3.0f * s, t1 - t0, 6.0f * s, D3DCOLOR_ARGB(255, 44, 48, 60));
        fill_rect(dev, xl, cy - 3.0f * s, xh - xl, 6.0f * s, full ? D3DCOLOR_ARGB(255, 96, 102, 118) : orange);
        for (int hnd = 0; hnd < 2; hnd++) {
            float hx = hnd ? xh : xl;
            fill_rect(dev, hx - 5.0f * s, cy - 10.0f * s, 10.0f * s, 20.0f * s, D3DCOLOR_ARGB(255, 10, 10, 12));
            fill_rect(dev, hx - 4.0f * s, cy - 9.0f * s, 8.0f * s, 18.0f * s,
                      g_sdrag == k * 2 + hnd ? orange : D3DCOLOR_ARGB(255, 232, 236, 244));
        }
        if (g_font_tex) {
            set_picture(dev, g_font_tex, 1);
            put_str(dev, (float)g->sl[k].left, y + 4.0f * s, 0.42f * s, full ? grey : orange, SL_NAME[k]);
            if (full) _snprintf(v, sizeof v, "any");
            else _snprintf(v, sizeof v, "%d-%d", g_rlo[k], g_rhi[k]);
            put_str(dev, t1 + 12.0f * s, y + 4.0f * s, 0.42f * s, full ? grey : D3DCOLOR_ARGB(255, 240, 240, 245), v);
        }
    }
    draw_chip(dev, g->reset, "RESET", 0, s);
}

static void browse_draw(IDirect3DDevice9 *dev)
{
    struct Geo g; char line[96]; float s = g_s; DWORD now = GetTickCount();
    DWORD white = D3DCOLOR_ARGB(255, 240, 240, 245), grey = D3DCOLOR_ARGB(255, 150, 156, 170);
    DWORD orange = D3DCOLOR_ARGB(255, 255, 138, 42);
    if (!g_browse) return;
    if (!g_font_tex) build_font(dev);
    EnterCriticalSection(&g_board_cs);
    browse_geo(&g);
    set_flat(dev);
    fill_rect(dev, g.x0, 0.0f, g.x1 - g.x0, g_ch, D3DCOLOR_ARGB(242, 13, 14, 19));               // over the game
    fill_rect(dev, g.x0, 0.0f, g.x1 - g.x0, 4.0f * s, orange);
    fill_rect(dev, (float)g.box.left, (float)g.box.top, (float)(g.box.right - g.box.left),
              (float)(g.box.bottom - g.box.top), D3DCOLOR_ARGB(255, 32, 35, 44));
    outline(dev, (float)g.box.left, (float)g.box.top, (float)(g.box.right - g.box.left),
            (float)(g.box.bottom - g.box.top), 2.0f * s, orange);
    fill_rect(dev, (float)g.close.left, (float)g.close.top, (float)(g.close.right - g.close.left),
              (float)(g.close.bottom - g.close.top), D3DCOLOR_ARGB(255, 70, 75, 88));
    draw_chips(dev, g.pos, POS_CHIP, 5, g_fpos, s);
    draw_chips(dev, g.rar, RAR_CHIP, 6, g_frar, s);
    draw_chips(dev, g.sort, SORT_CHIP, 8, g_sort, s);
    draw_chip(dev, g.nat, g_fnat[0] ? g_fnat : "ANY", g_fnat[0] || g_pick == 1, s);
    draw_chip(dev, g.club, g_fclub[0] ? g_fclub : "ANY", g_fclub[0] || g_pick == 2, s);
    draw_sliders(dev, &g, s);
    if (g_pick) draw_picker(dev, &g, s);
    else draw_pane(dev, &g, s);
    for (int row = 0; row < g.rows && !g_pick; row++)
        for (int col = 0; col < g.cols; col++) {
            int r = (g_scroll + row) * g.cols + col, on = 0;
            const struct CatCard *c; struct CardPic *p;
            float tx = g.gx0 + col * g.cw + (g.cw - g.tw) * 0.5f, ty = g.gy0 + row * g.ch;
            if (r >= g_nres) break;
            c = &g_cat[g_res[r]];
            p = pic_for(c->no);
            for (int k = 0; k < g_ncards; k++) if (g_cards[k].no == c->no) on = 1;
            set_flat(dev);
            if (r == g_bhover) fill_rect(dev, tx - 4.0f * s, ty - 4.0f * s, g.tw + 8.0f * s, g.th + 8.0f * s, D3DCOLOR_ARGB(255, 255, 214, 40));
            fill_rect(dev, tx - 1.0f, ty - 1.0f, g.tw + 2.0f, g.th + 2.0f, D3DCOLOR_ARGB(255, 6, 6, 8));
            if (p && p->state == PIC_READY && p->tex) {
                set_picture(dev, p->tex, 0);
                tex_quad(dev, tx, ty, tx + g.tw, ty + g.th, 0.0f, 0.0f, FACE_U, 1.0f);
            } else fill_rect(dev, tx, ty, g.tw, g.th, D3DCOLOR_ARGB(255, 52, 57, 70));
            if (on) { set_flat(dev); fill_rect(dev, tx, ty, g.tw, g.th, D3DCOLOR_ARGB(150, 0, 0, 0)); }  // already on the table
            if (g_font_tex) {
                set_picture(dev, g_font_tex, 1);
                put_in_rect(dev, RC(tx - 8.0f * s, ty + g.th + 3.0f * s, tx + g.tw + 8.0f * s, ty + g.th + 21.0f * s),
                            0.42f * s, on ? grey : white, c->shown);
                if (g_sort >= 2) _snprintf(line, sizeof line, "%s  %s %d", c->pos, SORT_CHIP[g_sort], c->st[g_sort - 2]);
                else _snprintf(line, sizeof line, "%s  %d", c->pos, c->total);      // its line and its total
                put_in_rect(dev, RC(tx - 8.0f * s, ty + g.th + 21.0f * s, tx + g.tw + 8.0f * s, ty + g.th + 38.0f * s),
                            0.40f * s, line_colour(c->pos), line);
                if (on) put_in_rect(dev, RC(tx, ty + g.th * 0.42f, tx + g.tw, ty + g.th * 0.58f), 0.45f * s,
                                    D3DCOLOR_ARGB(255, 255, 214, 40), "ON TABLE");
                else if (!(p && p->state == PIC_READY)) {
                    _snprintf(line, sizeof line, "%d", c->no);
                    put_in_rect(dev, RC(tx, ty, tx + g.tw, ty + g.th), 0.5f * s, white, line);
                }
            }
            if (r == g_bhover) {                     // the card under the mouse: SAME CLUB / SAME COUNTRY on it
                RECT mc, mn;
                card_minis(&g, r, &mc, &mn);
                if (c->club[0]) draw_chip(dev, mc, "SAME CLUB", strcmp(g_fclub, c->club) == 0, s);
                if (c->nat[0]) draw_chip(dev, mn, "SAME COUNTRY", strcmp(g_fnat, c->nat) == 0, s);
            }
        }
    if (g_font_tex) {
        set_picture(dev, g_font_tex, 1);
        put_str(dev, g.x0 + 24.0f * s, 14.0f * s, 0.85f * s, orange, "CATALOGUE");
        {
            const char *typed = g_pick ? g_pq : g_query;      // the open COUNTRY / CLUB list takes the typing
            if (typed[0]) _snprintf(line, sizeof line, "%s%s", typed, (now / 500) & 1 ? "_" : "");
            else _snprintf(line, sizeof line, "%s%s", g_pick == 1 ? "type to find a country" : g_pick == 2 ?
                           "type to find a club" : "name, club, country, season, FW, DMF... or a card number", (now / 500) & 1 ? "_" : "");
            put_str(dev, (float)g.box.left + 10.0f * s, (float)g.box.top + 6.0f * s, 0.72f * s, typed[0] ? white : grey, line);
        }
        put_str(dev, g.lab_nat, 24.0f * s, 0.42f * s, g_fnat[0] ? orange : grey, "COUNTRY");
        put_str(dev, g.lab_club, 24.0f * s, 0.42f * s, g_fclub[0] ? orange : grey, "CLUB");
        put_str(dev, g.x0 + 24.0f * s, 102.0f * s, 0.42f * s, grey, "POSITION");
        put_str(dev, g.lab_rar, 102.0f * s, 0.42f * s, grey, "RARITY");
        put_str(dev, g.x0 + 24.0f * s, 132.0f * s, 0.42f * s, grey, "SORT BY");
        if (g_pick) _snprintf(line, sizeof line, "pick a %s - type to narrow the list - Esc closes it",
                              g_pick == 1 ? "country" : "club");
        else _snprintf(line, sizeof line, "%d found - table %d/16 - click adds - Esc closes", g_nres, g_ncards);
        put_str(dev, (float)g.sort[7].right + 18.0f * s, 132.0f * s, 0.42f * s, grey, line);
        put_in_rect(dev, g.close, 0.8f * s, white, "X");
        if (g_bmsg[0] && (LONG)(g_bmsg_until - now) > 0) {
            RECT nr = RC(g.x0 + (g.x1 - g.x0) * 0.2f, g_ch - 70.0f * s, g.x1 - (g.x1 - g.x0) * 0.2f, g_ch - 22.0f * s);
            set_flat(dev);
            fill_rect(dev, (float)nr.left, (float)nr.top, (float)(nr.right - nr.left), (float)(nr.bottom - nr.top),
                      D3DCOLOR_ARGB(240, 24, 26, 33));
            set_picture(dev, g_font_tex, 1);
            put_in_rect(dev, nr, 0.62f * s, g_bmsg_col, g_bmsg);
        }
    }
    LeaveCriticalSection(&g_board_cs);
}

static void browse_open(HWND h, int open)
{
    EnterCriticalSection(&g_board_cs);
    g_browse = open;
    g_pick = 0; g_pq[0] = 0;                                  // the COUNTRY / CLUB list starts closed (the choices stay)
    if (open) { g_query[0] = 0; g_bmsg[0] = 0; g_bdetail = -1; run_search_locked(); }
    LeaveCriticalSection(&g_board_cs);
    if (open) SetPropA(h, "WCCF_TYPING", (HANDLE)1);         // _keys_seat1.py: these keys are not cabinet buttons
    else RemovePropA(h, "WCCF_TYPING");
    logline("browser %s", open ? "opened" : "closed");
}

static void browse_key(HWND h, WPARAM vk, LPARAM lp)       // a key while the browser is open: always the browser's
{
    BYTE ks[256]; WORD ch = 0; size_t n; struct Geo g;
    EnterCriticalSection(&g_board_cs);
    browse_geo(&g);
    if (g_pick) {                                             // the COUNTRY / CLUB list is open: the keys are its
        int list[160], k = pick_list_locked(list, 160);
        n = strlen(g_pq);
        if (vk == VK_ESCAPE) { g_pick = 0; g_pq[0] = 0; }    // Esc closes the list, not the catalogue
        else if (vk == VK_BACK) { if (n) { g_pq[n - 1] = 0; g_pscroll = 0; } }
        else if (vk == VK_RETURN) { if (k) pick_choose_locked(list[0]); }
        else if (vk == VK_NEXT || vk == VK_DOWN) pick_scroll_locked(&g, vk == VK_NEXT ? g.prows : 1);
        else if (vk == VK_PRIOR || vk == VK_UP) pick_scroll_locked(&g, vk == VK_PRIOR ? -g.prows : -1);
        else if (GetKeyboardState(ks) && ToAscii((UINT)vk, (UINT)((lp >> 16) & 0xFF), ks, &ch, 0) == 1 &&
                 ch >= 32 && ch < 127 && n < sizeof g_pq - 1) { g_pq[n] = (char)ch; g_pq[n + 1] = 0; g_pscroll = 0; }
        LeaveCriticalSection(&g_board_cs);
        return;
    }
    LeaveCriticalSection(&g_board_cs);
    if (vk == VK_ESCAPE) { browse_open(h, 0); return; }
    EnterCriticalSection(&g_board_cs);
    n = strlen(g_query);
    if (vk == VK_BACK) { if (n) { g_query[n - 1] = 0; run_search_locked(); } }
    else if (vk == VK_RETURN) { if (g_nres > 0) board_add_locked(&g_cat[g_res[0]]); }
    else if (vk == VK_NEXT || vk == VK_DOWN) { if ((g_scroll + g.rows) * g.cols < g_nres) g_scroll += vk == VK_NEXT ? g.rows : 1; }
    else if (vk == VK_PRIOR || vk == VK_UP) { g_scroll -= vk == VK_PRIOR ? g.rows : 1; if (g_scroll < 0) g_scroll = 0; }
    else if (GetKeyboardState(ks) && ToAscii((UINT)vk, (UINT)((lp >> 16) & 0xFF), ks, &ch, 0) == 1 &&
             ch >= 32 && ch < 127 && n < sizeof g_query - 1) {
        g_query[n] = (char)ch; g_query[n + 1] = 0;
        run_search_locked();
    }
    LeaveCriticalSection(&g_board_cs);
}

// a press inside the open browser (canvas point already known to be in the middle column)
static int in_rect(const RECT *r, int x, int y) { return x >= r->left && x < r->right && y >= r->top && y < r->bottom; }

static void browse_click(HWND h, int x, int y)
{
    struct Geo g; int r, i, chip = 0;
    EnterCriticalSection(&g_board_cs);
    browse_geo(&g);
    if (in_rect(&g.close, x, y)) { LeaveCriticalSection(&g_board_cs); browse_open(h, 0); return; }
    if (in_rect(&g.nat, x, y) || in_rect(&g.club, x, y)) {    // COUNTRY / CLUB: its list opens (clicked again: closes)
        int want = in_rect(&g.nat, x, y) ? 1 : 2;
        g_pick = g_pick == want ? 0 : want; g_pq[0] = 0; g_pscroll = 0; g_bhover = -1;
        logline("browser: %s list %s", want == 1 ? "country" : "club", g_pick ? "opened" : "closed");
        LeaveCriticalSection(&g_board_cs);
        return;
    }
    if (g_pick) {
        if (y >= g.gy0) {                                     // in the list: the entry under the click is chosen
            int list[160], k = pick_list_locked(list, 160);
            for (i = 0; i < k; i++)
                if (pick_visible(&g, i)) {
                    RECT pr = pick_rect(&g, i);
                    if (in_rect(&pr, x, y)) { pick_choose_locked(list[i]); break; }
                }
            LeaveCriticalSection(&g_board_cs);
            return;
        }
        g_pick = 0; g_pq[0] = 0;                              // a click above the list closes it, and still counts
    }
    for (i = 0; i < 5; i++) if (in_rect(&g.pos[i], x, y))  { g_fpos = i; chip = 1; }
    for (i = 0; i < 6; i++) if (in_rect(&g.rar[i], x, y))  { g_frar = i; chip = 1; }
    for (i = 0; i < 8; i++) if (in_rect(&g.sort[i], x, y)) { g_sort = i; chip = 1; }
    if (in_rect(&g.reset, x, y)) { ranges_reset(); chip = 1; }
    for (i = 0; i < 7 && !chip; i++) {                    // a slider: the nearer handle follows the mouse until release
        if (y >= g.sl[i].top - 4 && y < g.sl[i].bottom + 4 && x >= g.tx0[i] - 10.0f * g_s && x <= g.tx1[i] + 10.0f * g_s) {
            float span = (float)(SL_MAX[i] - SL_MIN[i]), w = g.tx1[i] - g.tx0[i];
            float xl = g.tx0[i] + w * (float)(g_rlo[i] - SL_MIN[i]) / span, xh = g.tx0[i] + w * (float)(g_rhi[i] - SL_MIN[i]) / span;
            int high = fabsf((float)x - xh) < fabsf((float)x - xl) || ((float)x > xh && g_rlo[i] == g_rhi[i]);
            g_sdrag = i * 2 + high;
            LeaveCriticalSection(&g_board_cs);
            SetCapture(h);
            slider_move(x);
            return;
        }
    }
    if (chip) {
        run_search_locked();
        log_filters_locked();
    } else {
        r = browse_hit_locked(&g, x, y);
        if (r >= 0) {
            const struct CatCard *c = &g_cat[g_res[r]]; RECT mc, mn;
            int minis = r == g_bhover && card_minis(&g, r, &mc, &mn);      // drawn only on the card under the mouse
            if (minis && c->club[0] && in_rect(&mc, x, y)) same_toggle_locked(g_fclub, c->club);
            else if (minis && c->nat[0] && in_rect(&mn, x, y)) same_toggle_locked(g_fnat, c->nat);
            else board_add_locked(c);
        }
    }
    LeaveCriticalSection(&g_board_cs);
}

static void browse_wheel(int notches)                    // + = up
{
    struct Geo g;
    EnterCriticalSection(&g_board_cs);
    browse_geo(&g);
    if (g_pick) { pick_scroll_locked(&g, -notches); LeaveCriticalSection(&g_board_cs); return; }   // the list scrolls
    g_scroll -= notches;
    if ((g_scroll + g.rows) * g.cols >= g_nres + g.cols) g_scroll = (g_nres + g.cols - 1) / g.cols - g.rows;
    if (g_scroll < 0) g_scroll = 0;
    LeaveCriticalSection(&g_board_cs);
}

// ---------------------------------------------------------------- KEYS: which key does what (the player, 2026-10-05)
// "KEYS" (in the skin, right of START) opens a panel over the middle, styled like the catalogue: every cabinet action
// with its key.  Click an action, press its new key; a key another action has swaps over, so no key is ever used
// twice.  The keys live in keys.txt, which the key driver (_keys_seat1.py) reads again whenever it changes - a change
// works at once - and the on-screen buttons take their keys from it too.  The actions, names, defaults and allowed
// keys are the same as _keys_seat1.py's ACTIONS / ALLOWED_VKS: keep the two equal.  keys.txt: WCCF_KEYS if set (the
// tests), else the kit's data\keys.txt (beside overlay\), else beside this DLL.  While the panel is open the game
// window carries WCCF_TYPING, so the key pressed for an action presses nothing in the game.  Since 2026-10-06 every
// action also has a CONTROLLER box (a game controller's button or stick - see "KEYS: game controllers" below).
#define KEY_X0 1312.0f                   // the KEYS button on the design sheet (measure_skin.js)
#define KEY_Y0 529.0f
#define KEY_X1 1424.0f
#define KEY_Y1 569.0f
struct KAct { const char *id, *label, *hint; int def, vk, btn; DWORD col; int pad; };   // pad: its controller control
#define COL_GOLD   D3DCOLOR_ARGB(255, 226, 170,  34)
#define COL_ORANGE D3DCOLOR_ARGB(255, 239, 127,  36)
static struct KAct g_kact[] = {          // left column 0-7 (BUTTONS, CARD + COIN), right column 8-15 (TACTICS, OPERATOR)
    { "START",     "START",      "",                 0x0D, 0x0D, B_START, COL_GREEN  },
    { "PRESS",     "PRESS",      "decide",           0x58, 0x58, B_PRESS, COL_RED    },
    { "SHOOT",     "SHOOT",      "",                 0x43, 0x43, B_SHOOT, COL_RED    },
    { "KEEPER",    "KEEPER",     "goalie",           0x42, 0x42, B_KEEP,  COL_BLUE   },
    { "DATA",      "DATA",       "",                 0x53, 0x53, B_DATA,  COL_BLUE   },
    { "KEYPLAYER", "KEY PLAYER", "a guess",          0x44, 0x44, B_KEYPL, COL_YELLOW },
    { "CARD",      "CARD",       "club card in/out", 0x49, 0x49, B_CARD,  COL_GOLD   },
    { "COIN",      "COIN",       "",                 0x35, 0x35, B_COIN,  COL_ORANGE },
    { "UP",        "CENTRAL",    "tactic, up",       0x26, 0x26, B_UP,    COL_GREEN  },
    { "DOWN",      "COUNTER",    "tactic, down",     0x28, 0x28, B_DOWN,  COL_GREEN  },
    { "LEFT",      "L-SIDE",     "tactic, left",     0x25, 0x25, B_LEFT,  COL_GREEN  },
    { "RIGHT",     "R-SIDE",     "tactic, right",    0x27, 0x27, B_RIGHT, COL_GREEN  },
    { "TEST",      "TEST",       "operator menu",    0x70, 0x70, -1,      COL_GREY   },
    { "SERVICE",   "SERVICE",    "",                 0x71, 0x71, -1,      COL_GREY   },
    // ids stay SENSOR2/3 (keys.txt and _keys_seat1.py use them); the bits are Sega's service switches SW1/SW2, not
    // card sensors (2026-10-06, docs\research\CARD-DISPENSER-2010-11.md): on Sega's club-card recovery screen SW1
    // answers "Write the backup data over the Club Card? [SW1] Yes (overwrite)".
    { "SENSOR2",   "SW1",        "can overwrite card", 0x38, 0x38, -1,    COL_GREY   },
    { "SENSOR3",   "SW2",        "service: back",    0x39, 0x39, -1,      COL_GREY   },
};
#define NKACT ((int)(sizeof g_kact / sizeof g_kact[0]))
static const char *KHEAD[4] = { "BUTTONS", "CARD + COIN", "TACTICS", "OPERATOR" };
static char  g_keys_path[MAX_PATH], g_keys_tmp[MAX_PATH];
static int   g_keys = 0;                 // the KEYS panel is open
static int   g_kcap = -1;                // the action waiting for its new key (-1 = none)
static int   g_khover = -1;              // the action under the mouse

static int key_allowed(int vk)           // = _keys_seat1.py ALLOWED_VKS
{
    if (vk == 0x08 || vk == 0x09 || vk == 0x0D || vk == 0x10 || vk == 0x11 || vk == 0x13 || vk == 0x20 ||
        vk == 0x2D || vk == 0x2E || vk == 0xE2) return 1;
    return (vk >= 0x21 && vk <= 0x28) || (vk >= 0x30 && vk <= 0x39) || (vk >= 0x41 && vk <= 0x5A) ||
           (vk >= 0x60 && vk <= 0x78) || (vk >= 0x7B && vk <= 0x87) || (vk >= 0xBA && vk <= 0xC0) ||
           (vk >= 0xDB && vk <= 0xDF);
}

static const char *vk_name(int vk)       // a key's name for the panel (ASCII: the font has nothing else)
{
    static char b[8];
    if ((vk >= 0x30 && vk <= 0x39) || (vk >= 0x41 && vk <= 0x5A)) { b[0] = (char)vk; b[1] = 0; return b; }
    if (vk >= 0x70 && vk <= 0x87) { _snprintf(b, sizeof b, "F%d", vk - 0x6F); return b; }
    if (vk >= 0x60 && vk <= 0x69) { _snprintf(b, sizeof b, "Num %d", vk - 0x60); return b; }
    switch (vk) {
        case 0: return "-";             case 0x08: return "Backspace";  case 0x09: return "Tab";
        case 0x0D: return "Enter";      case 0x10: return "Shift";      case 0x11: return "Ctrl";
        case 0x12: return "Alt";        case 0x13: return "Pause";      case 0x14: return "Caps Lock";
        case 0x1B: return "Esc";        case 0x20: return "Space";      case 0x21: return "Page Up";
        case 0x22: return "Page Down";  case 0x23: return "End";        case 0x24: return "Home";
        case 0x25: return "Left";       case 0x26: return "Up";         case 0x27: return "Right";
        case 0x28: return "Down";       case 0x2C: return "Print Scr";  case 0x2D: return "Insert";
        case 0x2E: return "Delete";     case 0x5B: case 0x5C: return "Windows";  case 0x5D: return "Menu";
        case 0x6A: return "Num *";      case 0x6B: return "Num +";      case 0x6C: return "Num Sep";
        case 0x6D: return "Num -";      case 0x6E: return "Num .";      case 0x6F: return "Num /";
        case 0x90: return "Num Lock";   case 0x91: return "Scroll Lock";
        case 0xBA: return ";";  case 0xBB: return "=";  case 0xBC: return ",";  case 0xBD: return "-";
        case 0xBE: return ".";  case 0xBF: return "/";  case 0xC0: return "`";  case 0xDB: return "[";
        case 0xDC: return "\\"; case 0xDD: return "]";  case 0xDE: return "'";  case 0xDF: return "OEM 8";
        case 0xE2: return "<>";
        default: _snprintf(b, sizeof b, "0x%02X", vk); return b;
    }
}

static char *trim(char *s)
{
    char *e;
    while (*s == ' ' || *s == '\t' || *s == '\r' || *s == '\n') s++;
    e = s + strlen(s);
    while (e > s && (e[-1] == ' ' || e[-1] == '\t' || e[-1] == '\r' || e[-1] == '\n')) *--e = 0;
    return s;
}

// ---------------------------------------------------------------- KEYS: game controllers (2026-10-06)
// the player: "lets make it so that in the key mapping, users can map their joystick without an issue" - a player's group
// runs real cabinet button panels on a USB encoder.  Every action also gets a CONTROLLER box: click it, then press a
// button or move the stick.  Read with Windows' standard joystick calls (winmm joyGetPosEx), as the key driver reads
// them (_keys_seat1.py CONTROLLERS / PadDevice / Pads - keep the numbers, the words and the rest rule equal).  All
// controllers count as one.  A control is a number above every key code: 0x100 + n button n (1-32), 0x200 + 2 * axis
// + (1 for +) a stick or axis direction (X Y Z R U V; the stick is X and Y, up is Y-), 0x300 + n the hat - a pad's
// d-pad (up right down left).  keys.txt: "PAD START=B3".  The REST RULE: an axis direction a controller rests on when
// first seen (a trigger at one end) is never a press while it stays plugged in; a button or hat direction held then
// counts once let go.  Asked only on the board thread and only while the KEYS panel is open: an empty slot answered in
// 0.01 ms here (2026-10-06) but is known to be slow on some PCs.  winmm is loaded from the system folder by its full
// path - seat 1's own winmm.dll is the hook.  Test switch WCCFPANEL_FAKEPAD=file: the controllers come from that file
// (fstest_keys.py), one line each: "SLOT BUTTONS AXES CAPS X Y Z R U V POV NAME" (axes 0-65535, as winmm's).
#define PAD_BUTTON 0x100
#define PAD_AXIS   0x200
#define PAD_HAT    0x300
#define PAD_ON     0.5f                  // an axis direction is pressed past half way ...
#define PAD_OFF    0.3f                  // ... and let go back inside 0.3 (no flicker)
#define NPADS      16
static const char  AXW[] = "XYZRUV";
static const char *HATW[4] = { "UP", "RIGHT", "DOWN", "LEFT" };
struct PadDev {                          // one controller, from when it was found
    int on; char name[48]; JOYCAPSA caps;
    int rest[6];                         // the side each axis rested on when first seen (-1, 0, +1)
    DWORD held0; int hat0;               // buttons / hat directions held when first seen: no press until let go
    ULONGLONG act;                       // pressed at the last read: bits 0-31 buttons, 32-43 axis directions, 44-47 hat
};
static struct PadDev g_pad[NPADS];       // written by the board thread under g_board_cs (the drawing reads on, name)
static ULONGLONG g_pad_now = 0, g_pad_prev = 0;   // every controller's presses now / at the read before (g_board_cs)
static int   g_kpadcap = -1;             // the action waiting for its controller control (-1 = none)
static int   g_pad_api = 0;              // winmm's joystick calls: 0 not looked for yet, 1 there, -1 not to be had
static DWORD g_pad_scan_at = 0;          // the board thread's next look for controllers
static volatile LONG g_pad_rescan = 1;   // look now (WM_DEVICECHANGE: something was plugged in or out)
static volatile LONG g_pad_reset = 0;    // the panel opened: forget the controllers found, learn their rest again
typedef MMRESULT (WINAPI *JoyPosFn)(UINT, LPJOYINFOEX);
typedef MMRESULT (WINAPI *JoyCapsFn)(UINT_PTR, LPJOYCAPSA, UINT);
typedef MMRESULT (WINAPI *JoyChangedFn)(DWORD);
static JoyPosFn     g_joy_pos = NULL;
static JoyCapsFn    g_joy_caps = NULL;
static JoyChangedFn g_joy_changed = NULL;

static int pad_bit_code(int bit)         // a bit of g_pad_now -> its control
{
    return bit < 32 ? PAD_BUTTON + bit + 1 : bit < 44 ? PAD_AXIS + bit - 32 : PAD_HAT + bit - 44;
}

static const char *pad_word(int code, char *b, int n)    // a control's word in keys.txt ("B3", "X+", "HAT UP")
{
    if (code > PAD_BUTTON && code <= PAD_BUTTON + 32) _snprintf(b, n, "B%d", code - PAD_BUTTON);
    else if (code >= PAD_AXIS && code < PAD_AXIS + 12)
        _snprintf(b, n, "%c%c", AXW[(code - PAD_AXIS) / 2], (code - PAD_AXIS) % 2 ? '+' : '-');
    else if (code >= PAD_HAT && code < PAD_HAT + 4) _snprintf(b, n, "HAT %s", HATW[code - PAD_HAT]);
    else lstrcpynA(b, "-", n);
    b[n - 1] = 0;
    return b;
}

static const char *pad_label(int code, char *b, int n)   // a control's name on screen ("Button 3", "Stick Up")
{
    static const char *stick[2][2] = { { "Left", "Right" }, { "Up", "Down" } };
    static const char *hat[4] = { "Up", "Right", "Down", "Left" };
    if (!code) lstrcpynA(b, "-", n);
    else if (code > PAD_BUTTON && code <= PAD_BUTTON + 32) _snprintf(b, n, "Button %d", code - PAD_BUTTON);
    else if (code >= PAD_AXIS && code < PAD_AXIS + 12) {
        int axis = (code - PAD_AXIS) / 2, plus = (code - PAD_AXIS) % 2;
        if (axis < 2) _snprintf(b, n, "Stick %s", stick[axis][plus]);
        else _snprintf(b, n, "Axis %c%c", AXW[axis], plus ? '+' : '-');
    } else if (code >= PAD_HAT && code < PAD_HAT + 4) _snprintf(b, n, "D-pad %s", hat[code - PAD_HAT]);
    else _snprintf(b, n, "0x%X", code);
    b[n - 1] = 0;
    return b;
}

static int pad_code(const char *s)       // keys.txt's word -> the control, 0 = none (= _keys_seat1.py pad_code)
{
    char t[24]; int n = 0, i, v;
    for (; *s && n < (int)sizeof t - 1; s++)
        if (*s != ' ' && *s != '\t' && *s != '\r' && *s != '\n') t[n++] = (char)toupper((unsigned char)*s);
    if (*s) return 0;                    // longer than any word
    t[n] = 0;
    if (!strncmp(t, "HAT", 3)) {
        for (i = 0; i < 4; i++) if (!strcmp(t + 3, HATW[i])) return PAD_HAT + i;
        return 0;
    }
    if (n == 2 && strchr(AXW, t[0]) && (t[1] == '+' || t[1] == '-'))
        return PAD_AXIS + 2 * (int)(strchr(AXW, t[0]) - AXW) + (t[1] == '+');
    if (t[0] == 'B' && n >= 2 && n <= 5) {
        for (v = 0, i = 1; i < n; i++) { if (t[i] < '0' || t[i] > '9') return 0; v = v * 10 + (t[i] - '0'); }
        return v >= 1 && v <= 32 ? PAD_BUTTON + v : 0;
    }
    return 0;
}

// the test's controllers (WCCFPANEL_FAKEPAD), read again at every look - stand-ins for winmm's three calls
static char g_fakepad[MAX_PATH] = "";
struct FakePad { int on; DWORD buttons, pos[6], pov; UINT naxes, caps; char name[40]; };
static struct FakePad g_fake[NPADS];

static void fake_load(void)
{
    char buf[4096], *line, *next; DWORD got = 0; struct FakePad f[NPADS];
    HANDLE h = CreateFileA(g_fakepad, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, NULL,
                           OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
    ZeroMemory(f, sizeof f);
    if (h != INVALID_HANDLE_VALUE) {
        if (!ReadFile(h, buf, sizeof buf - 1, &got, NULL)) got = 0;
        CloseHandle(h);
    }
    buf[got] = 0;
    for (line = buf; line && *line; line = next) {
        unsigned long v[11]; char *p = line, *e; int k;
        next = strchr(line, '\n');
        if (next) *next++ = 0;
        for (k = 0; k < 11; k++) { v[k] = strtoul(p, &e, 0); if (e == p) break; p = e; }
        if (k < 11 || v[0] >= NPADS) continue;
        f[v[0]].on = 1; f[v[0]].buttons = v[1]; f[v[0]].naxes = v[2]; f[v[0]].caps = v[3];
        for (k = 0; k < 6; k++) f[v[0]].pos[k] = v[4 + k];
        f[v[0]].pov = v[10];
        lstrcpynA(f[v[0]].name, trim(p), sizeof f[0].name);
    }
    memcpy(g_fake, f, sizeof f);
}

static MMRESULT WINAPI fake_caps(UINT_PTR id, LPJOYCAPSA c, UINT n)
{
    if (id >= NPADS || !g_fake[id].on || n < sizeof *c) return JOYERR_PARMS;
    ZeroMemory(c, sizeof *c);
    c->wMid = 0xFFFF; c->wPid = (WORD)id; c->wNumButtons = 12;
    c->wNumAxes = g_fake[id].naxes; c->wCaps = g_fake[id].caps;
    c->wXmax = c->wYmax = c->wZmax = c->wRmax = c->wUmax = c->wVmax = 65535;
    return JOYERR_NOERROR;
}

static MMRESULT WINAPI fake_pos(UINT id, LPJOYINFOEX j)
{
    if (id >= NPADS || !g_fake[id].on) return JOYERR_UNPLUGGED;
    j->dwButtons = g_fake[id].buttons; j->dwPOV = g_fake[id].pov;
    j->dwXpos = g_fake[id].pos[0]; j->dwYpos = g_fake[id].pos[1]; j->dwZpos = g_fake[id].pos[2];
    j->dwRpos = g_fake[id].pos[3]; j->dwUpos = g_fake[id].pos[4]; j->dwVpos = g_fake[id].pos[5];
    return JOYERR_NOERROR;
}

static MMRESULT WINAPI fake_changed(DWORD f) { (void)f; return JOYERR_NOERROR; }

static int pad_api(void)                 // the board thread: winmm's joystick calls (or the test's) - 1 = there
{
    char p[MAX_PATH]; UINT n; HMODULE m = NULL;
    if (g_pad_api) return g_pad_api > 0;
    g_pad_api = -1;
    n = GetEnvironmentVariableA("WCCFPANEL_FAKEPAD", g_fakepad, sizeof g_fakepad);
    if (n > 0 && n < sizeof g_fakepad) {
        g_joy_pos = fake_pos; g_joy_caps = fake_caps; g_joy_changed = fake_changed; g_pad_api = 1;
        logline("pads: FAKE controllers from %s (a test)", g_fakepad);
        return 1;
    }
    g_fakepad[0] = 0;
    n = GetSystemDirectoryA(p, MAX_PATH - 12);
    if (n && n < MAX_PATH - 12) { lstrcatA(p, "\\winmm.dll"); m = LoadLibraryA(p); }
    if (m) {
        g_joy_pos = (JoyPosFn)GetProcAddress(m, "joyGetPosEx");
        g_joy_caps = (JoyCapsFn)GetProcAddress(m, "joyGetDevCapsA");
        g_joy_changed = (JoyChangedFn)GetProcAddress(m, "joyConfigChanged");
    }
    if (!g_joy_pos || !g_joy_caps) {
        logline("pads: no joystick calls (%s) - controllers cannot be read here", m ? p : "winmm not loaded");
        return 0;
    }
    g_pad_api = 1;
    logline("pads: %s", p);
    return 1;
}

static float pad_axis(DWORD v, UINT lo, UINT hi)        // an axis reading as -1 .. +1, the middle 0
{
    double f;
    if (hi <= lo) return 0.0f;
    f = 2.0 * ((double)v - (double)lo) / ((double)hi - (double)lo) - 1.0;
    return (float)(f < -1.0 ? -1.0 : f > 1.0 ? 1.0 : f);
}

static int pad_hat_bits(DWORD pov)       // the hat's directions held (bits 0-3: up right down left); a diagonal: both
{
    static const int centre[4] = { 0, 9000, 18000, 27000 };
    int out = 0, i, d;
    if (pov > 35999) return 0;           // centred: 0xFFFF
    for (i = 0; i < 4; i++) {
        d = abs((int)pov - centre[i]) % 36000;
        if (36000 - d < d) d = 36000 - d;
        if (d <= 4500) out |= 1 << i;
    }
    return out;
}

static void pad_values(const JOYCAPSA *c, const JOYINFOEX *j, float v[6], int has[6])   // = pad_reading
{
    UINT lo[6], hi[6]; DWORD val[6]; int i;
    lo[0] = c->wXmin; hi[0] = c->wXmax; val[0] = j->dwXpos;
    lo[1] = c->wYmin; hi[1] = c->wYmax; val[1] = j->dwYpos;
    lo[2] = c->wZmin; hi[2] = c->wZmax; val[2] = j->dwZpos;
    lo[3] = c->wRmin; hi[3] = c->wRmax; val[3] = j->dwRpos;
    lo[4] = c->wUmin; hi[4] = c->wUmax; val[4] = j->dwUpos;
    lo[5] = c->wVmin; hi[5] = c->wVmax; val[5] = j->dwVpos;
    has[0] = c->wNumAxes >= 1; has[1] = c->wNumAxes >= 2;
    has[2] = (c->wCaps & JOYCAPS_HASZ) != 0; has[3] = (c->wCaps & JOYCAPS_HASR) != 0;
    has[4] = (c->wCaps & JOYCAPS_HASU) != 0; has[5] = (c->wCaps & JOYCAPS_HASV) != 0;
    for (i = 0; i < 6; i++) {
        if (has[i] && hi[i] <= lo[i]) has[i] = 0;
        v[i] = has[i] ? pad_axis(val[i], lo[i], hi[i]) : 0.0f;
    }
}

static ULONGLONG pad_read(struct PadDev *p, const JOYINFOEX *j)   // the controls pressed now (= PadDevice.read)
{
    float v[6]; int has[6], i, s, dirs; ULONGLONG now;
    pad_values(&p->caps, j, v, has);
    p->held0 &= j->dwButtons;
    now = (ULONGLONG)(j->dwButtons & ~p->held0);
    for (i = 0; i < 6; i++) {
        if (!has[i]) continue;
        for (s = 0; s < 2; s++) {                               // s 0: the - side, 1: the + side
            int side = s ? 1 : -1, bit = 32 + 2 * i + s;
            float lim = ((p->act >> bit) & 1) ? PAD_OFF : PAD_ON;
            if (side != p->rest[i] && v[i] * (float)side > lim) now |= 1ULL << bit;
        }
    }
    dirs = (p->caps.wCaps & JOYCAPS_HASPOV) ? pad_hat_bits(j->dwPOV) : 0;
    p->hat0 &= dirs;
    now |= (ULONGLONG)(dirs & ~p->hat0) << 44;
    p->act = now;
    return now;
}

static void pad_first(struct PadDev *p, const JOYINFOEX *j)     // first seen: what it rests on (= PadDevice())
{
    float v[6]; int has[6], i;
    pad_values(&p->caps, j, v, has);
    for (i = 0; i < 6; i++) p->rest[i] = !has[i] ? 0 : v[i] < -PAD_ON ? -1 : v[i] > PAD_ON ? 1 : 0;
    p->held0 = j->dwButtons;
    p->hat0 = (p->caps.wCaps & JOYCAPS_HASPOV) ? pad_hat_bits(j->dwPOV) : 0;
    p->act = 0;
    pad_read(p, j);
}

// the controller's own name as Windows keeps it under its USB ids, else the ids (winmm's own name is "Microsoft
// PC-joystick driver" for every one) - = _keys_seat1.py pad_name; ASCII for the font
static void pad_name(const JOYCAPSA *c, char *out, int n)
{
    char key[200], *t; HKEY roots[2] = { HKEY_CURRENT_USER, HKEY_LOCAL_MACHINE }, h; DWORD type, sz; int k;
    out[0] = 0;
    if (g_fakepad[0]) { if (c->wPid < NPADS) lstrcpynA(out, g_fake[c->wPid].name, n); }
    else {
        _snprintf(key, sizeof key, "System\\CurrentControlSet\\Control\\MediaProperties\\PrivateProperties\\Joystick\\"
                  "OEM\\VID_%04X&PID_%04X", c->wMid, c->wPid);
        key[sizeof key - 1] = 0;
        for (k = 0; k < 2 && !out[0]; k++) {
            if (RegOpenKeyExA(roots[k], key, 0, KEY_READ, &h) != ERROR_SUCCESS) continue;
            sz = (DWORD)n - 1;
            if (RegQueryValueExA(h, "OEMName", NULL, &type, (BYTE *)out, &sz) != ERROR_SUCCESS || type != REG_SZ)
                out[0] = 0;
            else out[sz < (DWORD)n ? sz : (DWORD)n - 1] = 0;
            RegCloseKey(h);
        }
    }
    out[n - 1] = 0;
    t = trim(out);
    if (t != out) memmove(out, t, strlen(t) + 1);
    if (!out[0]) _snprintf(out, n, "controller %04X:%04X", c->wMid, c->wPid);
    out[n - 1] = 0;
    for (k = 0; out[k]; k++) if ((unsigned char)out[k] < 32 || (unsigned char)out[k] > 126) out[k] = '?';
}

static void pad_scan(void)               // the board thread: look for controllers not found yet
{
    int i, known = 0;
    for (i = 0; i < NPADS; i++) known += g_pad[i].on;         // g_pad is written by this thread only
    if (!known && g_joy_changed) g_joy_changed(0);            // Windows reads its list again: one plugged in later
    for (i = 0; i < NPADS; i++) {
        struct PadDev d; JOYINFOEX j;
        if (g_pad[i].on) continue;
        ZeroMemory(&d, sizeof d);
        if (g_joy_caps((UINT_PTR)i, &d.caps, sizeof d.caps) != JOYERR_NOERROR) continue;
        ZeroMemory(&j, sizeof j); j.dwSize = sizeof j; j.dwFlags = JOY_RETURNALL | JOY_RETURNPOVCTS;
        if (g_joy_pos((UINT)i, &j) != JOYERR_NOERROR) continue;
        pad_name(&d.caps, d.name, sizeof d.name);
        pad_first(&d, &j);
        d.on = 1;
        EnterCriticalSection(&g_board_cs);
        g_pad[i] = d;
        LeaveCriticalSection(&g_board_cs);
        logline("pads: found %s in slot %d (%u buttons, %u axes, caps 0x%X)", d.name, i, d.caps.wNumButtons,
                d.caps.wNumAxes, d.caps.wCaps);
    }
}

static void pad_poll(void)               // the board thread: every controller found, read now
{
    ULONGLONG all = 0; int i;
    for (i = 0; i < NPADS; i++) {
        struct PadDev d = g_pad[i]; JOYINFOEX j; int ok;
        if (!d.on) continue;
        ZeroMemory(&j, sizeof j); j.dwSize = sizeof j; j.dwFlags = JOY_RETURNALL | JOY_RETURNPOVCTS;
        ok = g_joy_pos((UINT)i, &j) == JOYERR_NOERROR;
        if (ok) all |= pad_read(&d, &j);
        else d.on = 0;
        EnterCriticalSection(&g_board_cs);
        g_pad[i] = d;
        LeaveCriticalSection(&g_board_cs);
        if (!ok) logline("pads: %s gone (slot %d)", d.name, i);
    }
    EnterCriticalSection(&g_board_cs);
    g_pad_prev = g_pad_now; g_pad_now = all;
    LeaveCriticalSection(&g_board_cs);
}

static void keys_init_path(void)
{
    char e[MAX_PATH], data[MAX_PATH], full[MAX_PATH]; DWORD n = GetEnvironmentVariableA("WCCF_KEYS", e, sizeof e), a;
    if (n > 0 && n < sizeof e) lstrcpynA(g_keys_path, e, MAX_PATH);
    else {
        _snprintf(data, MAX_PATH, "%s\\..\\data", g_dlldir); data[MAX_PATH - 1] = 0;
        if (!GetFullPathNameA(data, MAX_PATH, full, NULL)) lstrcpynA(full, data, MAX_PATH);
        a = GetFileAttributesA(full);
        if (a != INVALID_FILE_ATTRIBUTES && (a & FILE_ATTRIBUTE_DIRECTORY)) _snprintf(g_keys_path, MAX_PATH, "%s\\keys.txt", full);
        else _snprintf(g_keys_path, MAX_PATH, "%s\\keys.txt", g_dlldir);
    }
    g_keys_path[MAX_PATH - 1] = 0;
    _snprintf(g_keys_tmp, MAX_PATH, "%s.panel", g_keys_path); g_keys_tmp[MAX_PATH - 1] = 0;
}

// keys.txt -> g_kact[].vk, by _keys_seat1.py load_keys()'s rules: no file = the defaults; a bad, unknown or forbidden
// line is skipped; a key given twice stays with the first action of the file, and the later one goes back to its
// default if that is free, else it has no key.  Then the on-screen buttons take the keys.  The "PAD NAME=WORD" lines
// -> g_kact[].pad, by load_pads()'s: no line = none; "=" or "=-" = none; the same action twice: its last line counts;
// a control given twice stays with the action whose line came first.  g_board_cs held.
static void keys_load_locked(void)
{
    int vk[64], given[64], ng = 0, order[64], no = 0, owner[256], i, j; FILE *f; char line[256];
    int pad[64], pgiven[64], npg = 0;
    for (i = 0; i < NKACT; i++) { vk[i] = g_kact[i].def; pad[i] = 0; }
    f = fopen(g_keys_path, "rb");
    if (f) {
        while (fgets(line, sizeof line, f)) {
            char *p = strchr(line, '#'), *eq, *name, *val, *end; long v; int k;
            if (p) *p = 0;
            eq = strchr(line, '=');
            if (!eq) continue;
            *eq = 0; name = trim(line); val = trim(eq + 1);
            if (!_strnicmp(name, "PAD", 3) && (name[3] == ' ' || name[3] == '\t')) {   // a controller line
                char *act = trim(name + 3); int code = 0;
                if (!*act || strpbrk(act, " \t")) continue;
                for (k = 0; k < NKACT && _stricmp(g_kact[k].id, act) != 0; k++) {}
                if (k == NKACT) continue;
                if (*val && strcmp(val, "-")) { code = pad_code(val); if (!code) continue; }
                pad[k] = code;
                for (j = 0; j < npg && pgiven[j] != k; j++) {}
                if (j == npg) pgiven[npg++] = k;
                continue;
            }
            for (k = 0; k < NKACT && _stricmp(g_kact[k].id, name) != 0; k++) {}
            if (k == NKACT || !*val) continue;
            v = strtol(val, &end, 0);
            if (*trim(end) || !key_allowed((int)v)) continue;
            vk[k] = (int)v;
            for (j = 0; j < ng && given[j] != k; j++) {}
            if (j == ng) given[ng++] = k;
        }
        fclose(f);
    }
    for (i = 0; i < ng; i++) order[no++] = given[i];
    for (i = 0; i < NKACT; i++) { for (j = 0; j < ng && given[j] != i; j++) {} if (j == ng) order[no++] = i; }
    for (i = 0; i < 256; i++) owner[i] = -1;
    for (j = 0; j < no; j++) {
        int a = order[j], v = vk[a];
        if (v && owner[v] >= 0) {
            int d = g_kact[a].def, later = 0, m;
            for (m = j + 1; m < no; m++) if (vk[order[m]] == d) later = 1;
            vk[a] = (owner[d] < 0 && !later) ? d : 0;
        }
        if (vk[a]) owner[vk[a]] = a;
    }
    for (i = 0; i < NKACT; i++) g_kact[i].vk = vk[i];
    for (i = 0; i < NKACT; i++) if (g_kact[i].btn >= 0) g_btn[g_kact[i].btn].vk = g_kact[i].vk;
    for (i = 0; i < NKACT; i++) g_kact[i].pad = 0;
    for (j = 0; j < npg; j++) {
        int a = pgiven[j], m, taken = 0;
        if (!pad[a]) continue;
        for (m = 0; m < NKACT; m++) if (g_kact[m].pad == pad[a]) taken = 1;
        if (!taken) g_kact[a].pad = pad[a];
    }
}

// g_kact -> keys.txt, whole: a temporary file, then one swap - the key driver never reads half of it.  g_board_cs held.
static int keys_save_locked(void)
{
    char text[2048], wb[16]; int n, i, k; FILE *f;
    n = _snprintf(text, sizeof text, "# WCCF 2010-11 kit - which key and which controller control does what. Written "
                  "by the KEYS panel\n# in seat 1's window, read by the key driver (_keys_seat1.py). Delete this file "
                  "to get the default keys back.\n");
    for (i = 0; i < NKACT && n < (int)sizeof text - 48; i++)
        n += g_kact[i].vk ? _snprintf(text + n, sizeof text - n, "%s=0x%02X\n", g_kact[i].id, g_kact[i].vk)
                          : _snprintf(text + n, sizeof text - n, "# %s has no key\n", g_kact[i].id);
    if (n < (int)sizeof text - 240)
        n += _snprintf(text + n, sizeof text - n, "# controllers (any game controller): B1-B32 its buttons, X- X+ Y- Y+ "
                       "the stick (left right up down),\n# Z R U V its other axes (+ or -), HAT UP / RIGHT / DOWN / "
                       "LEFT its d-pad\n");
    for (i = 0; i < NKACT && n < (int)sizeof text - 48; i++)
        if (g_kact[i].pad)
            n += _snprintf(text + n, sizeof text - n, "PAD %s=%s\n", g_kact[i].id, pad_word(g_kact[i].pad, wb, sizeof wb));
    f = fopen(g_keys_tmp, "wb");
    if (!f) { logline("keys: could not write %s", g_keys_tmp); return 0; }
    k = (int)fwrite(text, 1, (size_t)n, f) == n;
    fclose(f);
    if (!k) { logline("keys: could not write %s", g_keys_tmp); return 0; }
    for (k = 0; k < 40; k++) {            // the driver may be reading it this instant: a moment, then again
        if (MoveFileExA(g_keys_tmp, g_keys_path, MOVEFILE_REPLACE_EXISTING)) return 1;
        Sleep(5);
    }
    logline("keys: could not swap %s in (error %lu)", g_keys_path, GetLastError());
    return 0;
}

// the waiting action takes this controller control; an action that had it takes the waiting one's old control (or
// none) - the same swap as keys.  g_board_cs held.
static void pad_assign_locked(int k, int code)
{
    DWORD green = D3DCOLOR_ARGB(255, 120, 230, 120), yellow = D3DCOLOR_ARGB(255, 255, 214, 40);
    DWORD red = D3DCOLOR_ARGB(255, 255, 110, 90);
    char now_n[24], old_n[24], w1[16], w2[16]; int j, old = g_kact[k].pad;
    g_kpadcap = -1;
    pad_label(code, now_n, sizeof now_n);
    pad_label(old, old_n, sizeof old_n);
    if (code == old) {
        note_locked(yellow, "%s keeps %s", g_kact[k].label, now_n);
    } else {
        for (j = 0; j < NKACT && (j == k || g_kact[j].pad != code); j++) {}
        g_kact[k].pad = code;
        if (j < NKACT) g_kact[j].pad = old;
        if (!keys_save_locked()) note_locked(red, "could not save keys.txt - try again");
        else if (j < NKACT) note_locked(green, "%s = %s   (%s gets %s)", g_kact[k].label, now_n, g_kact[j].label,
                                        old ? old_n : "none");
        else note_locked(green, "%s = %s", g_kact[k].label, now_n);
        if (j < NKACT) logline("keys: PAD %s = %s, PAD %s = %s (swapped)", g_kact[k].id, pad_word(code, w1, sizeof w1),
                               g_kact[j].id, pad_word(old, w2, sizeof w2));
        else logline("keys: PAD %s = %s", g_kact[k].id, pad_word(code, w1, sizeof w1));
    }
    logline("keys note: %s", g_bmsg);                            // what the panel says (the tests read it)
}

// the board thread, every pass: while the KEYS panel is open, look for controllers (every 2 s, and at once when
// Windows says something was plugged in or out), read them, and give the first control pressed to the action waiting
// for one.  1 = the panel is open: come back in 15 ms.
static int pad_tick(void)
{
    DWORD now = GetTickCount(), yellow = D3DCOLOR_ARGB(255, 255, 214, 40); ULONGLONG edge; int bit; char nb[24];
    if (!g_keys || !pad_api()) return 0;
    if (InterlockedExchange(&g_pad_reset, 0)) {
        EnterCriticalSection(&g_board_cs);
        ZeroMemory(g_pad, sizeof g_pad);
        g_pad_now = g_pad_prev = 0;
        LeaveCriticalSection(&g_board_cs);
        g_pad_scan_at = now;
    }
    if (g_fakepad[0]) fake_load();
    if (InterlockedExchange(&g_pad_rescan, 0) || (LONG)(now - g_pad_scan_at) >= 0) {
        g_pad_scan_at = now + 2000;
        pad_scan();
    }
    pad_poll();
    EnterCriticalSection(&g_board_cs);
    edge = g_pad_now & ~g_pad_prev;
    if (edge && g_keys) {                // the first control pressed: a button, else the hat, else a stick or axis
        if (edge & 0xFFFFFFFFULL) for (bit = 0; !((edge >> bit) & 1); bit++) {}
        else if (edge >> 44) for (bit = 44; !((edge >> bit) & 1); bit++) {}
        else for (bit = 32; !((edge >> bit) & 1); bit++) {}
        if (g_kpadcap >= 0) pad_assign_locked(g_kpadcap, pad_bit_code(bit));
        else if (g_kcap >= 0) {
            note_locked(yellow, "that was the controller's %s - for it, click the CONTROLLER box",
                        pad_label(pad_bit_code(bit), nb, sizeof nb));
            logline("keys note: %s", g_bmsg);
        }
    }
    LeaveCriticalSection(&g_board_cs);
    return 1;
}

static void keys_init(void)              // the init thread, before the hooks: the buttons start with the saved keys
{
    keys_init_path();
    EnterCriticalSection(&g_board_cs);
    keys_load_locked();
    LeaveCriticalSection(&g_board_cs);
    logline("keys: %s (%s)", g_keys_path, GetFileAttributesA(g_keys_path) != INVALID_FILE_ATTRIBUTES
                                          ? "read" : "no file yet - the default keys");
}

static RECT keys_button(void)            // "KEYS" on the canvas (it sits in the right strip)
{
    return grown(RC(g_cw - (DES_W - KEY_X0) * g_s, g_py + KEY_Y0 * g_s, g_cw - (DES_W - KEY_X1) * g_s,
                    g_py + KEY_Y1 * g_s), GROW_RIGHT);
}

// the panel's parts, in canvas pixels over the middle column: title + two lines of help + X; two columns of rows,
// each with a heading above its two groups; one row = the cabinet colour as an edge, the name (its hint under it),
// the KEY box and the CONTROLLER box (2026-10-06); under them RESET, and the CONTROLLERS line at cy
struct KGeo { float x0, x1, colw, rowh, hx[4], hy[4], cy; RECT close, reset, row[16], cap[16], pcap[16]; };

static void keys_geo(struct KGeo *g)
{
    float s = g_s, gap = 24.0f * s, top = 104.0f * s, hd = 30.0f * s, rowh = 52.0f * s, sp = 10.0f * s;
    g->x0 = g_mx0; g->x1 = g_mx1; g->rowh = rowh;
    g->close = RC(g->x1 - 58.0f * s, 12.0f * s, g->x1 - 18.0f * s, 50.0f * s);
    g->colw = (g->x1 - g->x0 - 3.0f * gap) / 2.0f;
    for (int i = 0; i < NKACT && i < 16; i++) {
        int col = i / 8, r = i % 8, second = col == 0 ? r >= 6 : r >= 4;
        float x = g->x0 + gap + (float)col * (g->colw + gap);
        float y = top + hd * (float)(1 + second) + (float)r * rowh + (second ? sp : 0.0f);
        float pr = x + g->colw - 10.0f * s, pl = pr - 140.0f * s, kr = pl - 8.0f * s, kl = kr - 118.0f * s;
        g->row[i] = RC(x, y, x + g->colw, y + rowh - 8.0f * s);
        g->cap[i] = RC(kl, y + 6.0f * s, kr, y + rowh - 14.0f * s);
        g->pcap[i] = RC(pl, y + 6.0f * s, pr, y + rowh - 14.0f * s);
    }
    g->hx[0] = g->hx[1] = g->x0 + gap;
    g->hx[2] = g->hx[3] = g->x0 + 2.0f * gap + g->colw;
    g->hy[0] = g->hy[2] = top + 4.0f * s;
    g->hy[1] = top + hd + 6.0f * rowh + sp + 4.0f * s;
    g->hy[3] = top + hd + 4.0f * rowh + sp + 4.0f * s;
    {
        float by = top + 2.0f * hd + 8.0f * rowh + sp + 14.0f * s;
        g->reset = RC(g->x0 + gap, by, g->x0 + gap + 200.0f * s, by + 30.0f * s);
        g->cy = by + 46.0f * s;
    }
}

static void put_fit(IDirect3DDevice9 *dev, float x, float y, float scale, DWORD col, const char *s, float maxw);

// a box in a row: side, face, shine - or orange and pulsing while it waits.  The CONTROLLER box has a bluer face, so
// the two columns read apart; an empty box is darker.
static void keys_box(IDirect3DDevice9 *dev, RECT c, int waiting, int set, int pad, float s, DWORD now)
{
    float cx = (float)c.left, cy = (float)c.top, cw = (float)(c.right - c.left), ch = (float)(c.bottom - c.top);
    if (waiting) {
        fill_rect(dev, cx, cy, cw, ch, (now / 400) & 1 ? D3DCOLOR_ARGB(255, 255, 138, 42) : D3DCOLOR_ARGB(255, 222, 110, 24));
        return;
    }
    fill_rect(dev, cx, cy + 3.0f * s, cw, ch - 3.0f * s, D3DCOLOR_ARGB(255, 12, 13, 17));
    fill_rect(dev, cx, cy, cw, ch - 4.0f * s, !set ? D3DCOLOR_ARGB(255, 44, 47, 58) :
              pad ? D3DCOLOR_ARGB(255, 50, 68, 98) : D3DCOLOR_ARGB(255, 62, 67, 82));
    fill_rect(dev, cx + 2.0f * s, cy + 2.0f * s, cw - 4.0f * s, (ch - 4.0f * s) * 0.45f, !set ? D3DCOLOR_ARGB(255, 52, 56, 68) :
              pad ? D3DCOLOR_ARGB(255, 68, 90, 126) : D3DCOLOR_ARGB(255, 82, 88, 106));
}

static void keys_draw(IDirect3DDevice9 *dev)
{
    struct KGeo g; char line[128]; float s = g_s; DWORD now = GetTickCount(); int i;
    DWORD white = D3DCOLOR_ARGB(255, 240, 240, 245), grey = D3DCOLOR_ARGB(255, 150, 156, 170);
    DWORD orange = D3DCOLOR_ARGB(255, 255, 138, 42), ink = D3DCOLOR_ARGB(255, 25, 18, 8);
    if (!g_keys) return;
    if (!g_font_tex) build_font(dev);
    EnterCriticalSection(&g_board_cs);
    keys_geo(&g);
    set_flat(dev);
    fill_rect(dev, g.x0, 0.0f, g.x1 - g.x0, g_ch, D3DCOLOR_ARGB(242, 13, 14, 19));               // over the game
    fill_rect(dev, g.x0, 0.0f, g.x1 - g.x0, 4.0f * s, orange);
    fill_rect(dev, (float)g.close.left, (float)g.close.top, (float)(g.close.right - g.close.left),
              (float)(g.close.bottom - g.close.top), D3DCOLOR_ARGB(255, 70, 75, 88));
    for (i = 0; i < 4; i++)                                                                      // headings' rules
        fill_rect(dev, g.hx[i], g.hy[i] + 22.0f * s, g.colw, 2.0f * s, D3DCOLOR_ARGB(255, 60, 52, 44));
    for (i = 0; i < NKACT && i < 16; i++) {
        RECT r = g.row[i];
        float x = (float)r.left, y = (float)r.top, w = (float)(r.right - r.left), h = (float)(r.bottom - r.top);
        int cap = i == g_kcap || i == g_kpadcap, hov = i == g_khover;
        fill_rect(dev, x, y, w, h, cap || hov ? D3DCOLOR_ARGB(255, 34, 37, 48) : D3DCOLOR_ARGB(255, 24, 26, 34));
        if (cap) outline(dev, x, y, w, h, 2.0f * s, orange);
        else if (hov) outline(dev, x, y, w, h, 1.0f, D3DCOLOR_ARGB(255, 96, 102, 120));
        fill_rect(dev, x, y, 6.0f * s, h, g_kact[i].col);                     // the cabinet button's own colour
        keys_box(dev, g.cap[i], i == g_kcap, g_kact[i].vk != 0, 0, s, now);
        keys_box(dev, g.pcap[i], i == g_kpadcap, g_kact[i].pad != 0, 1, s, now);
    }
    if (g_font_tex) {
        char nb[24], pads[160], pressed[160]; int npads = 0, nnow = 0, bit;
        DWORD green = D3DCOLOR_ARGB(255, 120, 230, 120), red = D3DCOLOR_ARGB(255, 255, 110, 90);
        set_picture(dev, g_font_tex, 1);
        put_str(dev, g.x0 + 24.0f * s, 14.0f * s, 0.85f * s, orange, "KEYS");
        put_str(dev, g.x0 + 24.0f * s, 58.0f * s, 0.42f * s, grey, "click a KEY box and press a key, or a CONTROLLER box "
                "and press a button or move the stick - another action's swaps over");
        put_str(dev, g.x0 + 24.0f * s, 76.0f * s, 0.42f * s, grey, "right-click a CONTROLLER box to clear it - Esc "
                "cancels or closes - never usable: Esc F10 F11 Alt and the Windows keys");   // put_str: 120 letters at most
        for (i = 0; i < 4; i++) put_str(dev, g.hx[i], g.hy[i], 0.46f * s, orange, KHEAD[i]);
        for (i = 0; i < 16 && i < NKACT; i += 8) {                             // over each column's boxes
            float hy = g.hy[i ? 2 : 0];
            put_in_rect(dev, RC((float)g.cap[i].left, hy, (float)g.cap[i].right, hy + 20.0f * s), 0.36f * s, grey, "KEY");
            put_in_rect(dev, RC((float)g.pcap[i].left, hy, (float)g.pcap[i].right, hy + 20.0f * s), 0.36f * s, grey,
                        "CONTROLLER");
        }
        for (i = 0; i < NKACT && i < 16; i++) {
            RECT r = g.row[i], c = g.cap[i], p = g.pcap[i];
            float lx = (float)r.left + 18.0f * s, lw = (float)c.left - lx - 8.0f * s, h = (float)(r.bottom - r.top);
            float lh = (float)g_cellh * 0.52f * s, hh = (float)g_cellh * 0.36f * s;
            if (g_kact[i].hint[0]) {                                            // the name, its hint under it
                float y = (float)r.top + (h - lh - hh) * 0.5f;
                put_fit(dev, lx, y, 0.52f * s, white, g_kact[i].label, lw);
                put_fit(dev, lx, y + lh, 0.36f * s, grey, g_kact[i].hint, lw);
            } else put_fit(dev, lx, (float)r.top + (h - lh) * 0.5f, 0.52f * s, white, g_kact[i].label, lw);
            if (i == g_kcap) put_in_rect(dev, c, 0.44f * s, ink, "PRESS A KEY");
            else put_in_rect(dev, RC((float)c.left, (float)c.top, (float)c.right, (float)c.bottom - 4.0f * s), 0.52f * s,
                             g_kact[i].vk ? white : grey, vk_name(g_kact[i].vk));
            if (i == g_kpadcap) put_in_rect(dev, p, 0.44f * s, ink, "PRESS A BUTTON");
            else put_in_rect(dev, RC((float)p.left, (float)p.top, (float)p.right, (float)p.bottom - 4.0f * s), 0.52f * s,
                             g_kact[i].pad ? white : grey, pad_label(g_kact[i].pad, nb, sizeof nb));
        }
        _snprintf(line, sizeof line, "saved in keys.txt - a change works at once");
        put_str(dev, (float)g.reset.right + 18.0f * s, (float)g.reset.top + 7.0f * s, 0.40f * s, grey, line);
        pads[0] = 0;                                                            // the controllers Windows has
        for (i = 0; i < NPADS; i++)
            if (g_pad[i].on && strlen(pads) + strlen(g_pad[i].name) + 3 < sizeof pads) {
                if (npads++) strcat(pads, ", ");
                strcat(pads, g_pad[i].name);
            }
        lstrcpynA(pressed, "pressed now:", sizeof pressed);                    // ... and what is pressed on them
        for (bit = 0; bit < 48; bit++)
            if ((g_pad_now >> bit) & 1) {
                pad_label(pad_bit_code(bit), nb, sizeof nb);
                if (strlen(pressed) + strlen(nb) + 3 >= sizeof pressed) break;
                strcat(pressed, "  ");
                strcat(pressed, nb);
                nnow++;
            }
        put_str(dev, g.x0 + 24.0f * s, g.cy, 0.46f * s, orange, "CONTROLLERS");
        {
            float tx = g.x0 + 24.0f * s + str_w("CONTROLLERS", 0.46f * s) + 16.0f * s, tw = g.x1 - 24.0f * s - tx;
            if (g_pad_api < 0) put_fit(dev, tx, g.cy + 2.0f * s, 0.42f * s, red,
                                       "cannot be read on this PC - the keys still work", tw);
            else if (!npads) put_fit(dev, tx, g.cy + 2.0f * s, 0.42f * s, grey,
                                     "none found - plug one in (it shows here within a few seconds)", tw);
            else {
                put_fit(dev, tx, g.cy + 2.0f * s, 0.42f * s, white, pads, tw);
                put_fit(dev, tx, g.cy + 24.0f * s, 0.42f * s, nnow ? green : grey, nnow ? pressed : "pressed now: nothing", tw);
            }
        }
        put_in_rect(dev, g.close, 0.8f * s, white, "X");
    }
    draw_chip(dev, g.reset, "RESET TO DEFAULTS", 0, s);
    if (g_font_tex && g_bmsg[0] && (LONG)(g_bmsg_until - now) > 0) {                         // the last change
        RECT nr = RC(g.x0 + (g.x1 - g.x0) * 0.2f, g_ch - 70.0f * s, g.x1 - (g.x1 - g.x0) * 0.2f, g_ch - 22.0f * s);
        set_flat(dev);
        fill_rect(dev, (float)nr.left, (float)nr.top, (float)(nr.right - nr.left), (float)(nr.bottom - nr.top),
                  D3DCOLOR_ARGB(240, 24, 26, 33));
        set_picture(dev, g_font_tex, 1);
        put_in_rect(dev, nr, 0.62f * s, g_bmsg_col, g_bmsg);
    }
    LeaveCriticalSection(&g_board_cs);
}

static void keys_open(HWND h, int open)
{
    EnterCriticalSection(&g_board_cs);
    g_keys = open; g_kcap = -1; g_khover = -1; g_kpadcap = -1;
    if (open) { g_bmsg[0] = 0; keys_load_locked(); }       // keys.txt again: it may have been edited by hand
    LeaveCriticalSection(&g_board_cs);
    if (open) {                                              // the controllers looked for afresh (their rest learned
        InterlockedExchange(&g_pad_reset, 1);                // again) by the board thread
        InterlockedExchange(&g_pad_rescan, 1);
    }
    if (open) SetPropA(h, "WCCF_TYPING", (HANDLE)1);         // _keys_seat1.py: the key pressed for an action is not a button
    else RemovePropA(h, "WCCF_TYPING");
    logline("keys %s", open ? "opened" : "closed");
}

// a key while the panel is open: the waiting action's new key, or Esc.  Never reaches the game.
static void keys_key(HWND h, WPARAM wp, LPARAM lp)
{
    int vk = (int)wp, k, j, old;
    DWORD green = D3DCOLOR_ARGB(255, 120, 230, 120), yellow = D3DCOLOR_ARGB(255, 255, 214, 40), red = D3DCOLOR_ARGB(255, 255, 110, 90);
    if (lp & 0x40000000) return;                                 // a held key repeating
    if (g_kpadcap >= 0) {                                        // waiting for a CONTROLLER control: Esc cancels
        char nb[24];
        EnterCriticalSection(&g_board_cs);
        k = g_kpadcap;
        if (k >= 0) {
            if (vk == VK_ESCAPE) {
                g_kpadcap = -1;
                note_locked(yellow, "%s keeps %s", g_kact[k].label,
                            g_kact[k].pad ? pad_label(g_kact[k].pad, nb, sizeof nb) : "no controller control");
            } else note_locked(yellow, "%s is a key - for keys, click the KEY box (a keyboard-type encoder too)",
                               vk_name(vk));
            logline("keys note: %s", g_bmsg);
        }
        LeaveCriticalSection(&g_board_cs);
        return;
    }
    if (g_kcap < 0) { if (vk == VK_ESCAPE) keys_open(h, 0); return; }
    EnterCriticalSection(&g_board_cs);
    k = g_kcap;
    if (vk == VK_ESCAPE) {
        g_kcap = -1;
        note_locked(yellow, "%s keeps %s", g_kact[k].label, vk_name(g_kact[k].vk));
    } else if ((lp & 0x20000000) || !key_allowed(vk)) {          // Alt held, or a key that must stay free
        note_locked(red, "%s cannot be used - pick another key", (lp & 0x20000000) && vk != VK_MENU ? "Alt" : vk_name(vk));
        logline("keys: %s refused for %s", vk_name(vk), g_kact[k].id);
    } else if (vk == g_kact[k].vk) {
        g_kcap = -1;
        note_locked(yellow, "%s keeps %s", g_kact[k].label, vk_name(vk));
    } else {
        old = g_kact[k].vk;
        for (j = 0; j < NKACT && (j == k || g_kact[j].vk != vk); j++) {}
        g_kact[k].vk = vk;
        if (j < NKACT) g_kact[j].vk = old;                       // that key's action takes this one's old key
        for (int i = 0; i < NKACT; i++) if (g_kact[i].btn >= 0) g_btn[g_kact[i].btn].vk = g_kact[i].vk;
        g_kcap = -1;
        {
            char now_n[16], old_n[16];                           // vk_name() reuses one buffer: copy each name out
            lstrcpynA(now_n, vk_name(vk), sizeof now_n);
            lstrcpynA(old_n, vk_name(old), sizeof old_n);
            if (!keys_save_locked()) note_locked(red, "could not save keys.txt - try again");
            else if (j < NKACT) note_locked(green, "%s = %s   (%s gets %s)", g_kact[k].label, now_n, g_kact[j].label, old_n);
            else note_locked(green, "%s = %s", g_kact[k].label, now_n);
        }
        if (j < NKACT) logline("keys: %s = 0x%02X, %s = 0x%02X (swapped)", g_kact[k].id, vk, g_kact[j].id, old);
        else logline("keys: %s = 0x%02X", g_kact[k].id, vk);
    }
    logline("keys note: %s", g_bmsg);                            // what the panel says (the tests read it)
    LeaveCriticalSection(&g_board_cs);
}

static void keys_click(HWND h, int x, int y)                    // a press inside the open panel (the middle column)
{
    struct KGeo g; int i;
    EnterCriticalSection(&g_board_cs);
    keys_geo(&g);
    if (in_rect(&g.close, x, y)) { LeaveCriticalSection(&g_board_cs); keys_open(h, 0); return; }
    if (in_rect(&g.reset, x, y)) {
        for (i = 0; i < NKACT; i++) { g_kact[i].vk = g_kact[i].def; g_kact[i].pad = 0; }
        for (i = 0; i < NKACT; i++) if (g_kact[i].btn >= 0) g_btn[g_kact[i].btn].vk = g_kact[i].vk;
        g_kcap = -1; g_kpadcap = -1;
        if (keys_save_locked()) note_locked(D3DCOLOR_ARGB(255, 120, 230, 120), "the default keys are back, no controller controls");
        else note_locked(D3DCOLOR_ARGB(255, 255, 110, 90), "could not save keys.txt - try again");
        logline("keys: defaults");
    } else {
        for (i = 0; i < NKACT && !in_rect(&g.row[i], x, y); i++) {}
        if (i < NKACT && in_rect(&g.pcap[i], x, y)) {            // its CONTROLLER box: wait for a control
            int found = 0, j;
            g_kcap = -1;
            g_kpadcap = g_kpadcap != i ? i : -1;                 // a second click on the same box cancels
            if (g_kpadcap >= 0) {
                for (j = 0; j < NPADS; j++) found += g_pad[j].on;
                g_bmsg[0] = 0;
                if (!found) {
                    note_locked(D3DCOLOR_ARGB(255, 255, 214, 40), "no controller found yet - plug one in, then press its button");
                    logline("keys note: %s", g_bmsg);
                }
                logline("keys: waiting for a controller control for %s", g_kact[i].id);
            }
        } else {
            g_kpadcap = -1;
            g_kcap = (i < NKACT && g_kcap != i) ? i : -1;        // a second click on the same action cancels
            if (g_kcap >= 0) { g_bmsg[0] = 0; logline("keys: waiting for a key for %s", g_kact[i].id); }
        }
    }
    LeaveCriticalSection(&g_board_cs);
}

static void keys_rclick(int x, int y)    // a right-click in the open panel: a CONTROLLER box is cleared
{
    struct KGeo g; int i;
    EnterCriticalSection(&g_board_cs);
    keys_geo(&g);
    for (i = 0; i < NKACT && !in_rect(&g.pcap[i], x, y); i++) {}
    if (i < NKACT) {
        g_kpadcap = -1;
        if (!g_kact[i].pad) note_locked(D3DCOLOR_ARGB(255, 255, 214, 40), "%s has no controller control", g_kact[i].label);
        else {
            g_kact[i].pad = 0;
            if (keys_save_locked()) note_locked(D3DCOLOR_ARGB(255, 120, 230, 120), "%s: no controller control", g_kact[i].label);
            else note_locked(D3DCOLOR_ARGB(255, 255, 110, 90), "could not save keys.txt - try again");
            logline("keys: PAD %s cleared", g_kact[i].id);
        }
        logline("keys note: %s", g_bmsg);
    }
    LeaveCriticalSection(&g_board_cs);
}

static void keys_hover(int x, int y)
{
    struct KGeo g; int i;
    EnterCriticalSection(&g_board_cs);
    keys_geo(&g);
    for (i = 0; i < NKACT && !in_rect(&g.row[i], x, y); i++) {}
    g_khover = i < NKACT ? i : -1;
    LeaveCriticalSection(&g_board_cs);
}

// ---------------------------------------------------------------- the SETTINGS panel (2026-10-06)
// The button under CARD and COIN opens it over the middle column, like KEYS.  "NOW": what the hidden windows used to
// tell - the link to the server, the club card's session mark and bad endings, its last save and backup, the game's
// text.  "NEXT START": the two settings the player chose - where a plain PLAY.exe plays (THIS PC / ONLINE + an address) and
// the game's text (ENGLISH / JAPANESE).  They go to data\panel.txt at once; play.py reads it at its next plain start
// (read_panel, apply_english_request).  Nothing here changes the running game.
#define SET_X0 14.0f                     // the SETTINGS button on the design sheet (measure_skin.js)
#define SET_Y0 135.0f
#define SET_X1 176.0f
#define SET_Y1 169.0f
#define CMP_BTN_Y  604.0f                // COMPACT: SETTINGS and CLUB CARD sit in the right strip, under CATALOGUE and
#define CMP_SET_X  1083.0f               // KEYS (sheet px; the pair centred in the strip, edges in line with them)
#define CMP_CLUB_X 1261.0f
#define CONTROL_PORT 20002               // the server's port (play.py CONTROL_PORT)
enum { CS_NONE, CS_UNREADABLE, CS_NEW, CS_OPEN, CS_CUT, CS_CLOSED };
struct SetStatus { int link; char peer[16]; int card, bad, nback, english; ULONGLONG saved, backup; DWORD at; };
static struct SetStatus g_st;            // refreshed by the board thread about once a second while the panel is open
static char g_data_dir[MAX_PATH], g_panel_path[MAX_PATH], g_panel_tmp[MAX_PATH];
static int  g_set = 0;                   // the SETTINGS panel is open
static int  g_on_online = 0;             // play_on: 0 this PC, 1 online
static char g_server[64];                // server= as the file holds it (checked before use)
static char g_addr[16];                  // the address box while typing
static int  g_typing = 0;                // the address box has the keyboard
static int  g_eng_req = -1;              // english=: -1 no request, 0 off (Japanese), 1 on
static char g_card_req[64] = "";         // card=: the CLUB CARD panel's choice for the next start ("" none, "new")
static int  g_fix_req = 0;               // card_fix=bad_endings: CLEAR BAD ENDINGS, done by play.py at the next start
static volatile LONG g_set_dirty = 1;    // the status must be read again now
// RESTART NOW (the player, 2026-10-06: "a button that goes to the next start"): a first click arms it for 8 s, a second
// writes data\restart.request; _kit_helper.py (outside the game - seat 1's debugger would kill a restart the game
// started) opens "PLAY.exe restart".  Not during a card session.  Not taken in 3 s = no helper: removed, and said.
static DWORD g_rs_armed = 0;             // armed until this tick
static DWORD g_rs_sent = 0;              // when the request was written (0 = none waiting)

static int valid_ipv4(const char *s)     // = play.py valid_ipv4: four numbers 0-255 with dots, ASCII digits only
{
    int parts = 0, digits = 0, v = 0;
    if (!*s || strlen(s) > 15) return 0;
    for (;; s++) {
        if (*s >= '0' && *s <= '9') { if (++digits > 3) return 0; v = v * 10 + (*s - '0'); }
        else if (*s == '.' || !*s) {
            if (!digits || v > 255) return 0;
            parts++; digits = 0; v = 0;
            if (!*s) break;
        } else return 0;
    }
    return parts == 4;
}

// data\panel.txt -> the choices, by play.py read_panel()'s rules ("name=value", "#" starts a note).  g_board_cs held.
static void set_load_locked(void)
{
    FILE *f = fopen(g_panel_path, "rb"); char line[256];
    g_on_online = 0; g_server[0] = 0; g_eng_req = -1; g_card_req[0] = 0; g_fix_req = 0; g_compact = 0;
    if (!f) return;
    while (fgets(line, sizeof line, f)) {
        char *p = strchr(line, '#'), *eq, *name, *val;
        if (p) *p = 0;
        eq = strchr(line, '=');
        if (!eq) continue;
        *eq = 0; name = trim(line); val = trim(eq + 1);
        if (!_stricmp(name, "play_on")) g_on_online = !_stricmp(val, "online");
        else if (!_stricmp(name, "server")) lstrcpynA(g_server, val, sizeof g_server);
        else if (!_stricmp(name, "english")) g_eng_req = !_stricmp(val, "on") ? 1 : !_stricmp(val, "off") ? 0 : -1;
        else if (!_stricmp(name, "card")) lstrcpynA(g_card_req, val, sizeof g_card_req);
        else if (!_stricmp(name, "card_fix")) g_fix_req = !_stricmp(val, "bad_endings");
        else if (!_stricmp(name, "layout")) g_compact = !_stricmp(val, "compact");
    }
    fclose(f);
}

// the choices -> data\panel.txt, whole: a temporary file, then one swap (as keys.txt).  g_board_cs held.
static int set_save_locked(void)
{
    char text[640]; int n, k; FILE *f;
    n = _snprintf(text, sizeof text, "# WCCF 2010-11 kit - written by the SETTINGS panel in seat 1's window, read by "
                  "PLAY.exe at its next\n# plain start (play.py). english= is a change asked for that start; PLAY "
                  "takes the line out once it is done.\nplay_on=%s\n", g_on_online ? "online" : "this_pc");
    if (g_server[0]) n += _snprintf(text + n, sizeof text - n, "server=%s\n", g_server);
    if (g_eng_req >= 0) n += _snprintf(text + n, sizeof text - n, "english=%s\n", g_eng_req ? "on" : "off");
    if (g_card_req[0]) n += _snprintf(text + n, sizeof text - n, "card=%s\n", g_card_req);
    if (g_fix_req) n += _snprintf(text + n, sizeof text - n, "card_fix=bad_endings\n");
    if (g_compact) n += _snprintf(text + n, sizeof text - n, "layout=compact\n");     // the VIEW: kept, not a request
    f = fopen(g_panel_tmp, "wb");
    if (!f) { logline("settings: could not write %s", g_panel_tmp); return 0; }
    k = (int)fwrite(text, 1, (size_t)n, f) == n;
    fclose(f);
    if (!k) { logline("settings: could not write %s", g_panel_tmp); return 0; }
    for (k = 0; k < 40; k++) {
        if (MoveFileExA(g_panel_tmp, g_panel_path, MOVEFILE_REPLACE_EXISTING)) {
            logline("settings: saved play_on=%s server=%s english=%s%s%s%s layout=%s", g_on_online ? "online" : "this_pc",
                    g_server[0] ? g_server : "-", g_eng_req < 0 ? "-" : g_eng_req ? "on" : "off",
                    g_card_req[0] ? " card=" : "", g_card_req, g_fix_req ? " card_fix=bad_endings" : "",
                    g_compact ? "compact" : "cabinet");
            return 1;
        }
        Sleep(5);
    }
    logline("settings: could not swap %s in (error %lu)", g_panel_path, GetLastError());
    return 0;
}

static void set_init(void)               // the init thread: where data\ is, and what the file says
{
    char e[MAX_PATH], data[MAX_PATH]; DWORD n = GetEnvironmentVariableA("WCCF_DATA", e, sizeof e);   // tests: a scratch folder
    if (n > 0 && n < sizeof e) lstrcpynA(g_data_dir, e, MAX_PATH);
    else {
        _snprintf(data, MAX_PATH, "%s\\..\\data", g_dlldir); data[MAX_PATH - 1] = 0;
        if (!GetFullPathNameA(data, MAX_PATH, g_data_dir, NULL)) lstrcpynA(g_data_dir, data, MAX_PATH);
    }
    _snprintf(g_panel_path, MAX_PATH, "%s\\panel.txt", g_data_dir); g_panel_path[MAX_PATH - 1] = 0;
    _snprintf(g_panel_tmp, MAX_PATH, "%s.panel", g_panel_path); g_panel_tmp[MAX_PATH - 1] = 0;
    EnterCriticalSection(&g_board_cs);
    set_load_locked();
    g_st.link = -1; g_st.card = CS_NONE; g_st.bad = -1;
    LeaveCriticalSection(&g_board_cs);
    logline("settings: %s (%s)", g_panel_path, GetFileAttributesA(g_panel_path) != INVALID_FILE_ATTRIBUTES
                                               ? "read" : "no file yet - this PC, no request");
    logline("view: layout %s", g_compact ? "compact" : "cabinet");
}

// ---- reading the status (the board thread; no lock held while it reads files)
struct TcpRowPid { DWORD state, laddr, lport, raddr, rport, pid; };
typedef DWORD (WINAPI *GetExtTcpFn)(PVOID, PDWORD, BOOL, ULONG, int, ULONG);

static int server_link(char *peer)        // this process's TCP link to the server: 1 up, 0 none, -1 cannot tell
{
    static GetExtTcpFn get = NULL; static int tried = 0;
    DWORD size = 0, i, n, me = GetCurrentProcessId(); unsigned char *buf; int found = 0;
    if (!tried) { HMODULE m = LoadLibraryA("iphlpapi.dll"); tried = 1; if (m) get = (GetExtTcpFn)GetProcAddress(m, "GetExtendedTcpTable"); }
    if (!get) return -1;
    peer[0] = 0;
    get(NULL, &size, FALSE, 2, 5, 0);                  // 2 = AF_INET, 5 = TCP_TABLE_OWNER_PID_ALL: first, how big
    size += 4096;
    buf = (unsigned char *)malloc(size);
    if (!buf) return -1;
    if (get(buf, &size, FALSE, 2, 5, 0) != NO_ERROR) { free(buf); return -1; }
    n = *(DWORD *)buf;
    for (i = 0; i < n; i++) {
        struct TcpRowPid *r = (struct TcpRowPid *)(buf + 4) + i;
        int port = (int)(((r->rport & 0xFF) << 8) | ((r->rport >> 8) & 0xFF));
        if (r->pid == me && port == CONTROL_PORT && r->state == 5) {   // 5 = ESTABLISHED
            unsigned char *a = (unsigned char *)&r->raddr;
            _snprintf(peer, 16, "%u.%u.%u.%u", a[0], a[1], a[2], a[3]); peer[15] = 0;
            found = 1; break;
        }
    }
    free(buf);
    return found;
}

// the club card's session mark and bad endings, as kit_common.card_session reads them (the same positions and rules;
// _test_card_session.py and fstest_settings.py check both against the research decoder).  since 0 = not known.
static int card_session_c(const char *path, ULONGLONG since, int *bad, ULONGLONG *saved)
{
    static const int COPY[2] = { 16 + 8 * 16, 16 + 8 * 16 + 0x690 };
    unsigned char raw[4112 + 1]; DWORD got = 0; ULONGLONG sum[2]; DWORD stored[2]; int c, i;
    BY_HANDLE_FILE_INFORMATION fi;
    // every share flag: the card reader's save (a replace) must never find this file held (it retries for 1 s anyway)
    HANDLE h = CreateFileA(path, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, NULL,
                           OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
    *bad = -1; *saved = 0;
    ZeroMemory(&fi, sizeof fi);
    if (h == INVALID_HANDLE_VALUE) return CS_NONE;
    if (GetFileInformationByHandle(h, &fi)) *saved = ft_q(fi.ftLastWriteTime);
    if (!ReadFile(h, raw, sizeof raw, &got, NULL)) got = 0;
    CloseHandle(h);
    if (fi.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) return CS_NONE;
    if (got != 4112) return CS_UNREADABLE;
    if ((raw[5] | raw[6] << 8) == 0xFFFF) return CS_NEW;
    for (c = 0; c < 2; c++) {
        sum[c] = 0;
        for (i = 0; i < 0x68C; i += 4) sum[c] += *(DWORD *)(raw + COPY[c] + i);
        sum[c] &= 0xFFFFFFFFULL;
        stored[c] = *(DWORD *)(raw + COPY[c] + 0x68C);
    }
    for (c = 0; c < 2; c++) if (sum[c] == 0 && stored[c] == 0) return CS_UNREADABLE;   // the game refuses (0xA)
    for (c = 0; c < 2; c++) {
        if (stored[c] == (DWORD)sum[c] || stored[c] == (DWORD)(sum[c] + 1)) {
            const unsigned char *p = raw + COPY[c];
            int flag = (p[595 >> 3] >> (7 - (595 & 7))) & 1, v = 0, k;          // USER_INJUSTICE_FLAG
            for (k = 596; k < 603; k++) v = (v << 1) | ((p[k >> 3] >> (7 - (k & 7))) & 1);   // USER_INJUSTICE_NUM
            *bad = v;
            if (!flag) return CS_CLOSED;
            return (!since || *saved > since) ? CS_OPEN : CS_CUT;
        }
    }
    return CS_UNREADABLE;
}

// ---- closing the window quits the game (2026-10-08)
// The player: "remove STOP.exe and have a clean quit every time".  Closing seat 1's window (its X, Alt+F4) is how the
// game is quit: _debug_launch.py ends the game once its window is gone, and PLAY.exe's watcher stops the rest.  During
// a card session that ends the match without its locker-room save - a bad ending on the card - so the first close
// then only warns, over the picture, and a second close within 8 s quits anyway: the question STOP used to ask.
#define CLOSE_AGAIN_MS 8000
static DWORD g_close_until = 0;          // a close warned about until then (0: none)

static int close_allowed(void)           // WM_CLOSE: 1 = let the window close
{
    char p[MAX_PATH]; WIN32_FILE_ATTRIBUTE_DATA fa; ULONGLONG since = 0, saved = 0; int bad = -1, cs;
    if (g_close_until && (LONG)(g_close_until - GetTickCount()) > 0) {
        logline("close: closed again during the card session - the game ends");
        return 1;
    }
    _snprintf(p, MAX_PATH, "%s\\running.json", g_data_dir); p[MAX_PATH - 1] = 0;      // this run's start (play.py)
    if (GetFileAttributesExA(p, GetFileExInfoStandard, &fa)) since = ft_q(fa.ftLastWriteTime);
    _snprintf(p, MAX_PATH, "%s\\save\\seat1_club.bin", g_data_dir); p[MAX_PATH - 1] = 0;
    cs = card_session_c(p, since, &bad, &saved);
    if (cs != CS_OPEN) {
        logline("close: the window closes - the game ends");
        return 1;
    }
    g_close_until = GetTickCount() + CLOSE_AGAIN_MS;
    logline("close: a card session is open - warned, not closed");
    return 0;
}

static void close_draw(IDirect3DDevice9 *dev)  // the warning, over everything, while it holds
{
    float s = g_s, x0 = g_mx0 + 30.0f * s, x1 = g_mx1 - 30.0f * s, y0 = g_ch * 0.5f - 60.0f * s;
    if (!g_close_until || (LONG)(g_close_until - GetTickCount()) <= 0) { g_close_until = 0; return; }
    if (!g_font_tex) build_font(dev);
    set_flat(dev);
    fill_rect(dev, x0, y0, x1 - x0, 120.0f * s, D3DCOLOR_ARGB(245, 24, 14, 14));
    outline(dev, x0, y0, x1 - x0, 120.0f * s, 3.0f * s, D3DCOLOR_ARGB(255, 255, 110, 90));
    if (!g_font_tex) return;
    set_picture(dev, g_font_tex, 1);
    put_in_rect(dev, RC(x0, y0 + 10.0f * s, x1, y0 + 46.0f * s), 0.72f * s, D3DCOLOR_ARGB(255, 255, 110, 90),
                "A MATCH IS ON - THE GAME DID NOT CLOSE");
    put_in_rect(dev, RC(x0, y0 + 50.0f * s, x1, y0 + 78.0f * s), 0.46f * s, D3DCOLOR_ARGB(255, 240, 240, 245),
                "closing now ends it without the locker-room save: your card gets a bad ending");
    put_in_rect(dev, RC(x0, y0 + 80.0f * s, x1, y0 + 108.0f * s), 0.46f * s, D3DCOLOR_ARGB(255, 255, 214, 40),
                "close the window again within 8 seconds to quit anyway");
}

static void set_refresh(void)
{
    struct SetStatus st; char p[MAX_PATH]; WIN32_FILE_ATTRIBUTE_DATA fa; WIN32_FIND_DATAA fd; HANDLE fh;
    ULONGLONG since = 0; static char last[200]; char now[200];
    ZeroMemory(&st, sizeof st);
    st.link = server_link(st.peer);
    _snprintf(p, MAX_PATH, "%s\\running.json", g_data_dir); p[MAX_PATH - 1] = 0;      // this run's start (play.py)
    if (GetFileAttributesExA(p, GetFileExInfoStandard, &fa)) since = ft_q(fa.ftLastWriteTime);
    _snprintf(p, MAX_PATH, "%s\\save\\seat1_club.bin", g_data_dir); p[MAX_PATH - 1] = 0;
    st.card = card_session_c(p, since, &st.bad, &st.saved);
    _snprintf(p, MAX_PATH, "%s\\save\\backup\\seat1_club.bin.*.bak", g_data_dir); p[MAX_PATH - 1] = 0;
    fh = FindFirstFileA(p, &fd);
    if (fh != INVALID_HANDLE_VALUE) {
        do {
            if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) continue;
            st.nback++;
            if (ft_q(fd.ftLastWriteTime) > st.backup) st.backup = ft_q(fd.ftLastWriteTime);
        } while (FindNextFileA(fh, &fd));
        FindClose(fh);
    }
    _snprintf(p, MAX_PATH, "%s\\english_backup\\manifest.json", g_data_dir); p[MAX_PATH - 1] = 0;
    st.english = GetFileAttributesExA(p, GetFileExInfoStandard, &fa) && fa.nFileSizeLow > 2;   // = kit_common.english_on
    st.at = GetTickCount();
    EnterCriticalSection(&g_board_cs);
    g_st = st;
    LeaveCriticalSection(&g_board_cs);
    _snprintf(now, sizeof now, "settings: status link=%d peer=%s card=%d bad=%d backups=%d english=%d", st.link,
              st.peer[0] ? st.peer : "-", st.card, st.bad, st.nback, st.english);
    if (strcmp(now, last)) { lstrcpynA(last, now, sizeof last); logline("%s", now); }   // only when it changes
}

static void restart_path(char *p)        // data\restart.request
{
    _snprintf(p, MAX_PATH, "%s\\restart.request", g_data_dir); p[MAX_PATH - 1] = 0;
}

static int restart_request(void)         // the request, whole (a temporary file, then one swap)
{
    char p[MAX_PATH], tmp[MAX_PATH + 8]; FILE *f; int k;
    restart_path(p);
    _snprintf(tmp, sizeof tmp, "%s.panel", p); tmp[sizeof tmp - 1] = 0;
    f = fopen(tmp, "wb");
    if (!f) return 0;
    k = fprintf(f, "RESTART NOW - asked by the SETTINGS panel in seat 1 (pid %lu)\n", (unsigned long)GetCurrentProcessId()) > 0;
    fclose(f);
    return k && MoveFileExA(tmp, p, MOVEFILE_REPLACE_EXISTING);
}

static void set_tick(void)               // the board thread, every pass: the status while the panel is open
{
    if (g_rs_sent && GetTickCount() - g_rs_sent > 3000) {      // the helper takes it within 0.5 s when it runs
        char p[MAX_PATH];
        restart_path(p);
        EnterCriticalSection(&g_board_cs);
        if (GetFileAttributesA(p) != INVALID_FILE_ATTRIBUTES) {
            DeleteFileA(p);                                     // never left lying for a later run to find
            note_locked(D3DCOLOR_ARGB(255, 255, 110, 90), "the restart helper did not answer - close the game, then PLAY.exe");
            logline("settings: restart request not picked up - removed");
        }
        g_rs_sent = 0;
        LeaveCriticalSection(&g_board_cs);
    }
    if (g_set && (InterlockedExchange(&g_set_dirty, 0) || GetTickCount() - g_st.at > 1000)) set_refresh();
}

// ---- drawing
static void fmt_when(char *out, size_t cap, ULONGLONG t)   // a file time as the panel shows it, with its age
{
    FILETIME ft, lft, nowft; SYSTEMTIME lt; ULONGLONG age;
    if (!t) { lstrcpynA(out, "-", (int)cap); return; }
    GetSystemTimeAsFileTime(&nowft);
    age = ft_q(nowft) > t ? (ft_q(nowft) - t) / 10000000ULL : 0;          // seconds
    ft.dwLowDateTime = (DWORD)t; ft.dwHighDateTime = (DWORD)(t >> 32);
    FileTimeToLocalFileTime(&ft, &lft); FileTimeToSystemTime(&lft, &lt);
    if (age < 60) _snprintf(out, cap, "%02u:%02u (just now)", lt.wHour, lt.wMinute);
    else if (age < 3600) _snprintf(out, cap, "%02u:%02u (%u min ago)", lt.wHour, lt.wMinute, (unsigned)(age / 60));
    else if (age < 86400) _snprintf(out, cap, "%02u:%02u (%u h ago)", lt.wHour, lt.wMinute, (unsigned)(age / 3600));
    else _snprintf(out, cap, "%04u-%02u-%02u %02u:%02u", lt.wYear, lt.wMonth, lt.wDay, lt.wHour, lt.wMinute);
    out[cap - 1] = 0;
}

// the panel's parts, in canvas pixels over the middle column: title + help + X; "NOW" with six rows; "NEXT START"
// with two rows of choices (THIS PC / ONLINE + the address box, ENGLISH / JAPANESE) and RESTART NOW; "VIEW" with the
// LAYOUT (CABINET / COMPACT, 2026-10-06), which changes at once
struct SGeo { float x0, x1, lx, vx, rowh, ynow, ynext, yview; RECT close, pc, online, addr, eng, jap, restart, cab, cmp; };

static void set_geo(struct SGeo *g)
{
    float s = g_s, y;
    g->x0 = g_mx0; g->x1 = g_mx1; g->rowh = 38.0f * s;
    g->lx = g->x0 + 24.0f * s; g->vx = g->x0 + 230.0f * s;
    g->close = RC(g->x1 - 58.0f * s, 12.0f * s, g->x1 - 18.0f * s, 50.0f * s);
    g->ynow = 104.0f * s;
    g->ynext = g->ynow + 32.0f * s + 6.0f * g->rowh + 22.0f * s;
    y = g->ynext + 36.0f * s;
    g->pc = RC(g->vx, y, g->vx + 130.0f * s, y + 36.0f * s);
    g->online = RC(g->vx + 140.0f * s, y, g->vx + 270.0f * s, y + 36.0f * s);
    g->addr = RC(g->vx + 284.0f * s, y, g->vx + 504.0f * s, y + 36.0f * s);
    y += 52.0f * s;
    g->eng = RC(g->vx, y, g->vx + 130.0f * s, y + 36.0f * s);
    g->jap = RC(g->vx + 140.0f * s, y, g->vx + 270.0f * s, y + 36.0f * s);
    y += 66.0f * s;                                        // under the text's note
    g->restart = RC(g->vx, y, g->vx + 270.0f * s, y + 38.0f * s);
    g->yview = y + 38.0f * s + 72.0f * s;                  // under RESTART NOW's note and the "Saved at once" line
    y = g->yview + 36.0f * s;
    g->cab = RC(g->vx, y, g->vx + 130.0f * s, y + 36.0f * s);
    g->cmp = RC(g->vx + 140.0f * s, y, g->vx + 270.0f * s, y + 36.0f * s);
}

static void set_chip(IDirect3DDevice9 *dev, RECT r, const char *label, int on, float s)
{
    float x = (float)r.left, y = (float)r.top, w = (float)(r.right - r.left), h = (float)(r.bottom - r.top);
    set_flat(dev);
    fill_rect(dev, x, y, w, h, on ? D3DCOLOR_ARGB(255, 255, 138, 42) : D3DCOLOR_ARGB(255, 38, 41, 52));
    if (!on) outline(dev, x, y, w, h, 1.0f, D3DCOLOR_ARGB(255, 70, 75, 90));
    if (g_font_tex) {
        set_picture(dev, g_font_tex, 1);
        put_in_rect(dev, r, 0.5f * s, on ? D3DCOLOR_ARGB(255, 25, 18, 8) : D3DCOLOR_ARGB(255, 210, 214, 224), label);
    }
}

static void set_draw(IDirect3DDevice9 *dev)
{
    struct SGeo g; struct SetStatus st; float s = g_s, y; int i; char v[160], w2[64]; DWORD now = GetTickCount(), col;
    DWORD white = D3DCOLOR_ARGB(255, 240, 240, 245), grey = D3DCOLOR_ARGB(255, 150, 156, 170);
    DWORD orange = D3DCOLOR_ARGB(255, 255, 138, 42), green = D3DCOLOR_ARGB(255, 120, 230, 120);
    DWORD yellow = D3DCOLOR_ARGB(255, 255, 214, 40), red = D3DCOLOR_ARGB(255, 255, 110, 90);
    static const char *LABEL[6] = { "SERVER", "CLUB CARD", "BAD ENDINGS", "LAST SAVED", "LATEST BACKUP", "GAME TEXT" };
    if (!g_set) return;
    if (!g_font_tex) build_font(dev);
    EnterCriticalSection(&g_board_cs);
    set_geo(&g); st = g_st;
    set_flat(dev);
    fill_rect(dev, g.x0, 0.0f, g.x1 - g.x0, g_ch, D3DCOLOR_ARGB(242, 13, 14, 19));               // over the game
    fill_rect(dev, g.x0, 0.0f, g.x1 - g.x0, 4.0f * s, orange);
    fill_rect(dev, (float)g.close.left, (float)g.close.top, (float)(g.close.right - g.close.left),
              (float)(g.close.bottom - g.close.top), D3DCOLOR_ARGB(255, 70, 75, 88));
    fill_rect(dev, g.lx, g.ynow + 22.0f * s, g.x1 - g.x0 - 48.0f * s, 2.0f * s, D3DCOLOR_ARGB(255, 60, 52, 44));
    fill_rect(dev, g.lx, g.ynext + 22.0f * s, g.x1 - g.x0 - 48.0f * s, 2.0f * s, D3DCOLOR_ARGB(255, 60, 52, 44));
    fill_rect(dev, g.lx, g.yview + 22.0f * s, g.x1 - g.x0 - 48.0f * s, 2.0f * s, D3DCOLOR_ARGB(255, 60, 52, 44));
    for (i = 0; i < 6; i++)                                                                       // the rows' bands
        fill_rect(dev, g.lx, g.ynow + 32.0f * s + (float)i * g.rowh, g.x1 - g.x0 - 48.0f * s, g.rowh - 6.0f * s,
                  D3DCOLOR_ARGB(255, 24, 26, 34));
    {                                                                                             // the address box
        RECT a = g.addr; float ax = (float)a.left, ay = (float)a.top, aw = (float)(a.right - a.left), ah = (float)(a.bottom - a.top);
        int bad = !g_typing && g_server[0] && !valid_ipv4(g_server);
        fill_rect(dev, ax, ay, aw, ah, D3DCOLOR_ARGB(255, 20, 22, 29));
        outline(dev, ax, ay, aw, ah, g_typing ? 2.0f * s : 1.0f, g_typing ? orange : bad ? red : D3DCOLOR_ARGB(255, 70, 75, 90));
    }
    LeaveCriticalSection(&g_board_cs);
    set_chip(dev, g.pc, "THIS PC", !g_on_online, s);
    set_chip(dev, g.online, "ONLINE", g_on_online, s);
    {
        int want = g_eng_req >= 0 ? g_eng_req : st.english;
        set_chip(dev, g.eng, "ENGLISH", want == 1, s);
        set_chip(dev, g.jap, "JAPANESE", want == 0, s);
    }
    {
        int armed = g_rs_armed && (LONG)(g_rs_armed - now) > 0;
        set_chip(dev, g.restart, g_rs_sent ? "RESTARTING ..." : armed ? "CLICK AGAIN TO RESTART" : "RESTART NOW",
                 armed || g_rs_sent, s);
    }
    set_chip(dev, g.cab, "CABINET", !g_compact, s);
    set_chip(dev, g.cmp, "COMPACT", g_compact, s);
    if (!g_font_tex) return;
    set_picture(dev, g_font_tex, 1);
    put_str(dev, g.x0 + 24.0f * s, 14.0f * s, 0.85f * s, orange, "SETTINGS");
    put_str(dev, g.x0 + 24.0f * s, 58.0f * s, 0.42f * s, grey,
            "NOW: what the game's hidden windows used to tell, read live.  NEXT START: what PLAY.exe does next time.");
    put_str(dev, g.x0 + 24.0f * s, 76.0f * s, 0.42f * s, grey, "Esc closes this.  NEXT START waits for the next start; "
            "VIEW changes at once.  Nothing here changes the game itself");
    put_str(dev, g.lx, g.ynow, 0.46f * s, orange, "NOW");
    put_str(dev, g.lx, g.ynext, 0.46f * s, orange, "NEXT START");
    put_in_rect(dev, g.close, 0.8f * s, white, "X");
    for (i = 0; i < 6; i++) {
        y = g.ynow + 32.0f * s + (float)i * g.rowh + (g.rowh - 6.0f * s - (float)g_cellh * 0.52f * s) * 0.5f;
        put_str(dev, g.lx + 12.0f * s, y + 2.0f * s, 0.44f * s, grey, LABEL[i]);
        col = white; v[0] = 0;
        switch (i) {
        case 0:
            if (st.link == 1 && !strcmp(st.peer, "127.0.0.1")) { _snprintf(v, sizeof v, "THIS PC - connected"); col = green; }
            else if (st.link == 1) { _snprintf(v, sizeof v, "ONLINE %s - connected", st.peer); col = green; }
            else if (st.link == 0) { _snprintf(v, sizeof v, "NOT CONNECTED to the server"); col = red; }
            else { _snprintf(v, sizeof v, "cannot tell"); col = grey; }
            break;
        case 1:
            switch (st.card) {
            case CS_OPEN:   _snprintf(v, sizeof v, "SESSION OPEN - a match is on: do not stop the game"); col = orange; break;
            case CS_CLOSED: _snprintf(v, sizeof v, "closed - safe to close the game"); col = green; break;
            case CS_CUT:    _snprintf(v, sizeof v, "the last session did not end normally"); col = yellow; break;
            case CS_NEW:    _snprintf(v, sizeof v, "a new card - no club made yet"); col = grey; break;
            case CS_UNREADABLE: _snprintf(v, sizeof v, "the card file cannot be read"); col = red; break;
            default:        _snprintf(v, sizeof v, "no club card yet - put one in with the CARD key"); col = grey; break;
            }
            break;
        case 2:
            if (st.bad < 0) { _snprintf(v, sizeof v, "-"); col = grey; }
            else if (st.bad == 0) { _snprintf(v, sizeof v, "0"); col = green; }
            else if (st.bad == 1) { _snprintf(v, sizeof v, "1   (at 2, trade rights are lost)"); col = yellow; }
            else { _snprintf(v, sizeof v, "%d   (trade rights lost; every 5th also costs money)", st.bad); col = red; }
            break;
        case 3:
            fmt_when(w2, sizeof w2, st.saved);
            _snprintf(v, sizeof v, "%s", st.saved ? w2 : "never");
            if (!st.saved) col = grey;
            break;
        case 4:
            fmt_when(w2, sizeof w2, st.backup);
            if (st.nback) _snprintf(v, sizeof v, "%s   (%d kept)", w2, st.nback);
            else { _snprintf(v, sizeof v, "none yet - one is made when a session starts"); col = grey; }
            break;
        case 5:
            _snprintf(v, sizeof v, "%s", st.english ? "English" : "Japanese (Sega's original)");
            break;
        }
        v[sizeof v - 1] = 0;
        put_str(dev, g.vx, y, 0.52f * s, col, v);
    }
    y = (float)g.pc.top + ((float)(g.pc.bottom - g.pc.top) - (float)g_cellh * 0.44f * s) * 0.5f;
    put_str(dev, g.lx + 12.0f * s, y, 0.44f * s, grey, "PLAY ON");
    y = (float)g.eng.top + ((float)(g.eng.bottom - g.eng.top) - (float)g_cellh * 0.44f * s) * 0.5f;
    put_str(dev, g.lx + 12.0f * s, y, 0.44f * s, grey, "GAME TEXT");
    EnterCriticalSection(&g_board_cs);
    if (g_typing) _snprintf(v, sizeof v, "%s%s", g_addr, (now / 450) & 1 ? "_" : "");
    else _snprintf(v, sizeof v, "%s", g_server[0] ? g_server : "server address");
    v[sizeof v - 1] = 0;
    put_in_rect(dev, g.addr, 0.52f * s, g_typing || g_server[0] ? white : grey, v);
    y = (float)g.addr.bottom + 8.0f * s;
    if (g_typing) put_str(dev, (float)g.addr.left, y, 0.40f * s, grey, "digits and dots, Enter keeps it, Esc cancels");
    else if (g_on_online && !valid_ipv4(g_server)) put_str(dev, (float)g.addr.left, y, 0.40f * s, red, "not an address - click to type it");
    {                                    // under the chips: beside them it ran into the right strip in a small window
        int want = g_eng_req >= 0 ? g_eng_req : st.english;
        _snprintf(v, sizeof v, "%s", want != st.english ? "changes at the next start - that start takes a moment longer"
                                                         : "no change");
        put_str(dev, (float)g.eng.left, (float)g.eng.bottom + 8.0f * s, 0.40f * s, want != st.english ? yellow : grey, v);
    }
    y = (float)g.restart.top + ((float)(g.restart.bottom - g.restart.top) - (float)g_cellh * 0.44f * s) * 0.5f;
    put_str(dev, g.lx + 12.0f * s, y, 0.44f * s, grey, "APPLY NOW");
    if (st.card == CS_OPEN)
        put_str(dev, (float)g.restart.left, (float)g.restart.bottom + 8.0f * s, 0.40f * s, red,
                "not during a card session - after the locker-room save");
    else
        put_str(dev, (float)g.restart.left, (float)g.restart.bottom + 8.0f * s, 0.40f * s, grey,
                "the game closes and opens again with these NEXT START settings");
    put_str(dev, g.lx, (float)g.restart.bottom + 42.0f * s, 0.42f * s, grey,
            "Saved at once in data\\panel.txt. A plain PLAY.exe uses it; PLAY.exe local always plays on this PC.");
    put_str(dev, g.lx, g.yview, 0.46f * s, orange, "VIEW");
    y = (float)g.cab.top + ((float)(g.cab.bottom - g.cab.top) - (float)g_cellh * 0.44f * s) * 0.5f;
    put_str(dev, g.lx + 12.0f * s, y, 0.44f * s, grey, "LAYOUT");
    put_str(dev, (float)g.cab.left, (float)g.cab.bottom + 8.0f * s, 0.40f * s, grey, g_compact
            ? "COMPACT: the game larger, no cabinet buttons - your keys and controller press them; changes at once"
            : "CABINET: the cabinet's buttons around the game.  COMPACT: the game larger, without them");
    if (g_bmsg[0] && (LONG)(g_bmsg_until - now) > 0) {                                          // the last change
        RECT nr = RC(g.x0 + (g.x1 - g.x0) * 0.2f, g_ch - 70.0f * s, g.x1 - (g.x1 - g.x0) * 0.2f, g_ch - 22.0f * s);
        set_flat(dev);
        fill_rect(dev, (float)nr.left, (float)nr.top, (float)(nr.right - nr.left), (float)(nr.bottom - nr.top),
                  D3DCOLOR_ARGB(240, 24, 26, 33));
        set_picture(dev, g_font_tex, 1);
        put_in_rect(dev, nr, 0.62f * s, g_bmsg_col, g_bmsg);
    }
    LeaveCriticalSection(&g_board_cs);
}

// ---- input
static RECT set_button(void)             // "SETTINGS" on the canvas (the left strip; COMPACT: under CATALOGUE)
{
    if (g_compact)
        return grown(strip_rect(CMP_SET_X, CMP_BTN_Y, CMP_SET_X + (SET_X1 - SET_X0), CMP_BTN_Y + (SET_Y1 - SET_Y0)),
                     GROW_LEFT);
    return grown(RC(SET_X0 * g_s, g_py + SET_Y0 * g_s, SET_X1 * g_s, g_py + SET_Y1 * g_s), GROW_LEFT);
}

static void set_open(HWND h, int open)
{
    EnterCriticalSection(&g_board_cs);
    g_set = open; g_typing = 0;
    if (open) { g_bmsg[0] = 0; set_load_locked(); }          // the file again: PLAY may have done a request since
    LeaveCriticalSection(&g_board_cs);
    if (open) { InterlockedExchange(&g_set_dirty, 1); SetPropA(h, "WCCF_TYPING", (HANDLE)1); }   // keys are not buttons
    else RemovePropA(h, "WCCF_TYPING");
    logline("settings %s", open ? "opened" : "closed");
}

static void set_commit_locked(void)      // the typed address: kept if it is one (and the next start goes online)
{
    DWORD green = D3DCOLOR_ARGB(255, 120, 230, 120), red = D3DCOLOR_ARGB(255, 255, 110, 90);
    g_typing = 0;
    if (!valid_ipv4(g_addr)) {
        note_locked(red, "\"%s\" is not an address: four numbers 0-255 with dots", g_addr);
        logline("settings: address refused: %s", g_addr);
        return;
    }
    lstrcpynA(g_server, g_addr, sizeof g_server);
    g_on_online = 1;
    if (set_save_locked()) note_locked(green, "next start: online, on the server at %s", g_server);
    else note_locked(red, "could not save data\\panel.txt - try again");
}

static void set_key(HWND h, WPARAM wp, LPARAM lp)
{
    BYTE ks[256]; WORD ch = 0; size_t n; int vk = (int)wp;
    if (!g_typing) { if (vk == VK_ESCAPE) set_open(h, 0); return; }
    EnterCriticalSection(&g_board_cs);
    n = strlen(g_addr);
    if (vk == VK_ESCAPE) {
        g_typing = 0;
        note_locked(D3DCOLOR_ARGB(255, 255, 214, 40), "the address stays %s", g_server[0] ? g_server : "empty");
        logline("settings: typing cancelled");
    } else if (vk == VK_RETURN) set_commit_locked();
    else if (vk == VK_BACK) { if (n) g_addr[n - 1] = 0; }
    else if (GetKeyboardState(ks) && ToAscii((UINT)vk, (UINT)((lp >> 16) & 0xFF), ks, &ch, 0) == 1 &&
             ((ch >= '0' && ch <= '9') || ch == '.') && n < sizeof g_addr - 1) {
        g_addr[n] = (char)ch; g_addr[n + 1] = 0;
    }
    LeaveCriticalSection(&g_board_cs);
}

static void set_click(HWND h, int x, int y)                     // a press inside the open panel (the middle column)
{
    struct SGeo g; DWORD green = D3DCOLOR_ARGB(255, 120, 230, 120), red = D3DCOLOR_ARGB(255, 255, 110, 90);
    EnterCriticalSection(&g_board_cs);
    set_geo(&g);
    if (in_rect(&g.close, x, y)) { LeaveCriticalSection(&g_board_cs); set_open(h, 0); return; }
    if (in_rect(&g.addr, x, y)) {                               // the address box: type a new one
        if (!g_typing) { g_typing = 1; lstrcpynA(g_addr, valid_ipv4(g_server) ? g_server : "", sizeof g_addr); g_bmsg[0] = 0; }
        logline("settings: typing an address");
    } else {
        if (g_typing) set_commit_locked();                      // a click elsewhere keeps a good address
        if (in_rect(&g.pc, x, y)) {
            g_on_online = 0;
            if (set_save_locked()) note_locked(green, "next start: this PC");
            else note_locked(red, "could not save data\\panel.txt - try again");
        } else if (in_rect(&g.online, x, y)) {
            if (valid_ipv4(g_server)) {
                g_on_online = 1;
                if (set_save_locked()) note_locked(green, "next start: online, on the server at %s", g_server);
                else note_locked(red, "could not save data\\panel.txt - try again");
            } else {                                            // no address yet: type it first
                g_typing = 1; g_addr[0] = 0;
                note_locked(D3DCOLOR_ARGB(255, 255, 214, 40), "type the server's address, then Enter");
                logline("settings: typing an address");
            }
        } else if ((in_rect(&g.eng, x, y) || in_rect(&g.jap, x, y)) && !g_st.at) {
            note_locked(D3DCOLOR_ARGB(255, 255, 214, 40), "one moment - reading which text the game has now");
        } else if (in_rect(&g.eng, x, y) || in_rect(&g.jap, x, y)) {
            int want = in_rect(&g.eng, x, y) ? 1 : 0;
            g_eng_req = want == g_st.english ? -1 : want;       // the text it has now: no request
            if (!set_save_locked()) note_locked(red, "could not save data\\panel.txt - try again");
            else if (g_eng_req < 0) note_locked(green, "the game's text stays %s", want ? "English" : "Japanese");
            else note_locked(green, "the game's text becomes %s at the next start", want ? "English" : "Japanese");
        } else if (in_rect(&g.cab, x, y) || in_rect(&g.cmp, x, y)) {     // LAYOUT: at once, and kept
            int want = in_rect(&g.cmp, x, y);
            if (want == g_compact) note_locked(D3DCOLOR_ARGB(255, 255, 214, 40), "the layout is %s already",
                                               want ? "COMPACT" : "CABINET");
            else {
                g_compact = want;
                if (!set_save_locked()) note_locked(red, "could not save data\\panel.txt - the layout changed for now");
                else if (want) note_locked(green, "COMPACT: the game larger - SETTINGS and CLUB CARD are now on the "
                                                  "right, under KEYS");
                else note_locked(green, "CABINET: the cabinet's buttons are back around the game");
                logline("settings: layout %s", want ? "compact" : "cabinet");
            }
        } else if (in_rect(&g.restart, x, y)) {
            DWORD now = GetTickCount(), yellow = D3DCOLOR_ARGB(255, 255, 214, 40);
            if (g_rs_sent) {
                note_locked(yellow, "already asked - the game closes and opens again");
            } else if (g_st.card == CS_OPEN) {                  // the card rule, said here before anything starts
                note_locked(red, "not during a card session - after the locker-room save");
                logline("settings: restart refused - a card session is open");
            } else if (!g_rs_armed || (LONG)(g_rs_armed - now) <= 0) {
                g_rs_armed = now + 8000;             // 4 s ran out between the player's two clicks once (2026-10-06)
                note_locked(yellow, "click RESTART NOW again to restart the game now");
                logline("settings: restart armed");
            } else {
                g_rs_armed = 0;
                if (restart_request()) {
                    g_rs_sent = now;
                    note_locked(green, "restarting - the game closes and opens again (about a minute)");
                    logline("settings: restart requested");
                } else note_locked(red, "could not ask for the restart - close the game, then PLAY.exe");
            }
        }
    }
    LeaveCriticalSection(&g_board_cs);
}

// ---------------------------------------------------------------- the CLUB CARD panel (2026-10-06)
// the player: "a button like we did with the settings, but called club card manager".  Read-only for now.  The overlay
// cannot run Python, so it shows data\club_view.txt, which _kit_helper.py writes with club_view.py and
// decode_club_card.py (the reader the website and server will use) whenever the card changes.  Lines "kind|...":
// state | head | row (label, value, colour w g y r o d) | squad (no, name, position, apps, goals, assists,
// condition, injury) | backup.
#define CLUB_X0 14.0f                    // the CLUB CARD button on the design sheet (measure_skin.js)
#define CLUB_Y0 177.0f
#define CLUB_X1 176.0f
#define CLUB_Y1 211.0f
struct CLine { char kind; char a[32]; char b[128]; char col; };
struct CSq { char f[8][28]; };
static struct CLine g_cl[48];
static struct CSq g_csq[16];
static char g_cbak[8][24], g_cstate[16], g_creason[128];
static int  g_ncl = 0, g_ncsq = 0, g_ncbak = 0, g_club = 0;
// YOUR CARDS (the player, 2026-10-06: "multiple cards ... create a new club card"; switched "with a restart"): the view's
// "wallet|FILE|CLUB|SUMMARY" lines; a choice writes card=FILE (or card=new) into data\panel.txt and asks for
// RESTART NOW; play.py switches the files while nothing runs (club_wallet.py).  Not during a card session.
struct CWal { char file[64], club[40], summary[48]; int dead; };   // dead: transferred, the game will not play it
#define MAXWAL  16                        // other clubs read from the view (2026-10-08: was 8)
#define WAL_NEW 99                        // g_wal_armed / a pick: NEW CLUB CARD (was 8 - a 9th card would have been it)
#define WAL_FIX 98                        // g_wal_armed / a pick: CLEAR BAD ENDINGS
static struct CWal g_wal[MAXWAL];         // (g_cw is the canvas width: these are g_wal)
static int  g_nwal = 0;
static int  g_wal_top = 0;                // the first card shown when they do not all fit (the page buttons move it)
static char g_csession[16] = "";         // the slot's card session, from the view's "session|..." line
// CLEAR BAD ENDINGS (the community, 2026-10-08: "some easy way to remove bad endings from the club card"): shown under
// CARD HEALTH while the view's BAD ENDINGS row is not 0 or the last session was cut; two clicks write card_fix=bad_endings
// into data\panel.txt and ask for RESTART NOW, and play.py sets the card's bad-ending counts back to 0 while nothing
// runs (edit_club_card.clear_bad_endings: the game's own checks, a backup first).  Not during a card session.
static int  g_cbad = 0;                  // the view's BAD ENDINGS
static RECT g_cfix;                      // the button where club_draw last put it (empty: not shown)
static int  g_wal_armed = -1;             // the choice armed by a first click: a card's index, or WAL_NEW (-1 none)
static DWORD g_wal_until = 0;
static ULONGLONG g_cview_at = 0;         // the view file's write time as last read (0 = none read)
static DWORD g_cview_check = 0;
static volatile LONG g_club_dirty = 1;

// data\club_view.txt -> the panel's lines (the board thread).  Opened with every share flag: the helper replaces the
// file in one step, and a reader must never make that replace fail.
static void club_read(void)
{
    char p[MAX_PATH], *buf, *line, *next; HANDLE h; DWORD got = 0, size; BY_HANDLE_FILE_INFORMATION fi;
    struct CLine cl[48]; struct CSq sq[16]; struct CWal cw[MAXWAL]; char bak[8][24], state[16], reason[128], sess[16] = "";
    int ncl = 0, nsq = 0, nbak = 0, ncw = 0, bad = 0;
    _snprintf(p, MAX_PATH, "%s\\club_view.txt", g_data_dir); p[MAX_PATH - 1] = 0;
    h = CreateFileA(p, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, NULL, OPEN_EXISTING,
                    FILE_ATTRIBUTE_NORMAL, NULL);
    if (h == INVALID_HANDLE_VALUE) {
        EnterCriticalSection(&g_board_cs);
        if (g_cview_at || strcmp(g_cstate, "noview")) logline("club: no view yet (%s)", p);
        lstrcpynA(g_cstate, "noview", sizeof g_cstate); g_creason[0] = 0; g_ncl = g_ncsq = g_ncbak = 0; g_cview_at = 0;
        LeaveCriticalSection(&g_board_cs);
        return;
    }
    ZeroMemory(&fi, sizeof fi);
    GetFileInformationByHandle(h, &fi);
    if (ft_q(fi.ftLastWriteTime) == g_cview_at) { CloseHandle(h); return; }    // unchanged since the last read
    size = fi.nFileSizeLow < 65536 ? fi.nFileSizeLow : 65536;
    buf = (char *)malloc(size + 1);
    if (!buf) { CloseHandle(h); return; }
    if (!ReadFile(h, buf, size, &got, NULL)) got = 0;
    CloseHandle(h);
    buf[got] = 0;
    lstrcpynA(state, "unreadable", sizeof state);
    lstrcpynA(reason, "the view file is empty", sizeof reason);
    for (line = buf; line && *line; line = next) {
        char *f[10]; int nf = 0, k;
        next = strchr(line, '\n');
        if (next) *next++ = 0;
        if (*line == '#' || !*line) continue;
        if (line[strlen(line) - 1] == '\r') line[strlen(line) - 1] = 0;
        f[nf++] = line;
        for (char *c = line; *c && nf < 10; c++) if (*c == '|') { *c = 0; f[nf++] = c + 1; }
        if (!strcmp(f[0], "state") && nf >= 2) {
            lstrcpynA(state, f[1], sizeof state);
            lstrcpynA(reason, nf >= 3 ? f[2] : "", sizeof reason);
        } else if (!strcmp(f[0], "head") && nf >= 2 && ncl < 48) {
            cl[ncl].kind = 'h'; lstrcpynA(cl[ncl].a, f[1], sizeof cl[0].a); cl[ncl].b[0] = 0; cl[ncl].col = 'o'; ncl++;
        } else if (!strcmp(f[0], "row") && nf >= 3 && ncl < 48) {
            cl[ncl].kind = 'r'; lstrcpynA(cl[ncl].a, f[1], sizeof cl[0].a); lstrcpynA(cl[ncl].b, f[2], sizeof cl[0].b);
            cl[ncl].col = nf >= 4 ? f[3][0] : 'w'; ncl++;
            if (!strcmp(f[1], "BAD ENDINGS")) bad = atoi(f[2]);
        } else if (!strcmp(f[0], "squad") && nf >= 9 && nsq < 16) {
            for (k = 0; k < 8; k++) lstrcpynA(sq[nsq].f[k], f[k + 1], sizeof sq[0].f[0]);
            nsq++;
        } else if (!strcmp(f[0], "backup") && nf >= 2 && nbak < 8) {
            lstrcpynA(bak[nbak++], f[1], sizeof bak[0]);
        } else if (!strcmp(f[0], "session") && nf >= 2) {
            lstrcpynA(sess, f[1], sizeof sess);
        } else if (!strcmp(f[0], "wallet") && nf >= 4 && ncw < MAXWAL) {
            lstrcpynA(cw[ncw].file, f[1], sizeof cw[0].file); lstrcpynA(cw[ncw].club, f[2], sizeof cw[0].club);
            lstrcpynA(cw[ncw].summary, f[3], sizeof cw[0].summary);
            cw[ncw].dead = nf >= 5 && !strcmp(f[4], "transferred"); ncw++;
        }
    }
    free(buf);
    EnterCriticalSection(&g_board_cs);
    memcpy(g_cl, cl, sizeof cl[0] * (size_t)ncl); g_ncl = ncl;
    memcpy(g_csq, sq, sizeof sq[0] * (size_t)nsq); g_ncsq = nsq;
    memcpy(g_cbak, bak, sizeof bak[0] * (size_t)nbak); g_ncbak = nbak;
    memcpy(g_wal, cw, sizeof cw[0] * (size_t)ncw); g_nwal = ncw;
    if (g_wal_armed >= ncw && g_wal_armed != WAL_NEW && g_wal_armed != WAL_FIX) g_wal_armed = -1;   // the list changed
    g_cbad = bad;
    if (g_wal_top >= ncw) g_wal_top = 0;                                       // fewer cards now: back to the first
    lstrcpynA(g_csession, sess, sizeof g_csession);
    lstrcpynA(g_cstate, state, sizeof g_cstate); lstrcpynA(g_creason, reason, sizeof g_creason);
    g_cview_at = ft_q(fi.ftLastWriteTime);
    LeaveCriticalSection(&g_board_cs);
    logline("club: view read (state %s, %d lines, %d players, %d backups, session %s, %d other cards)", state, ncl,
            nsq, nbak, sess[0] ? sess : "-", ncw);
}

static void club_tick(void)              // the board thread, every pass: the view while the panel is open
{
    if (g_club && (InterlockedExchange(&g_club_dirty, 0) || GetTickCount() - g_cview_check > 1000)) {
        g_cview_check = GetTickCount();
        club_read();
    }
}

static DWORD club_colour(char c)
{
    switch (c) {
    case 'g': return D3DCOLOR_ARGB(255, 120, 230, 120);
    case 'y': return D3DCOLOR_ARGB(255, 255, 214, 40);
    case 'r': return D3DCOLOR_ARGB(255, 255, 110, 90);
    case 'o': return D3DCOLOR_ARGB(255, 255, 138, 42);
    case 'd': return D3DCOLOR_ARGB(255, 150, 156, 170);
    default:  return D3DCOLOR_ARGB(255, 240, 240, 245);
    }
}

// a text cut to fit a width, ending ".." when cut (the view keeps its lines short; this only guards the edge)
static void put_fit(IDirect3DDevice9 *dev, float x, float y, float scale, DWORD col, const char *s, float maxw)
{
    char b[160]; int n = (int)strlen(s), fit = g_advw > 0 ? (int)(maxw / ((float)g_advw * scale)) : n, keep;
    if (n <= fit || fit < 4) { put_str(dev, x, y, scale, col, s); return; }
    keep = fit - 2;                                              // room for ".." and the end, within b
    if (keep > (int)sizeof b - 3) keep = (int)sizeof b - 3;
    lstrcpynA(b, s, keep + 1);
    strcat(b, "..");
    put_str(dev, x, y, scale, col, b);
}

static void club_open(HWND h, int open);

// YOUR CARDS, in the right column: under the SQUAD when a club is in the slot, else from the top.  A heading, one
// two-line row per card that fits (club, summary, PLAY THIS CLUB), then NEW CLUB CARD.  Drawing and clicks share it.
// When they do not all fit (the player, 2026-10-08: "i have other clubs but i cant click on them or choose them" - only the
// first 3 showed, then "+ 2 more"), a page line in that text's place: < PREV, "cards 1-3 of 5", NEXT > - pages of
// what fits, wrapping round; the mouse wheel pages too.
struct CGeo { float x, w, ywal; int first, n, fit, paged; RECT row[MAXWAL], use[MAXWAL], prev, next, newc; };

static void club_geo(struct CGeo *g)     // g_board_cs held
{
    float s = g_s, y; int i, fit;
    g->x = g_mx0 + (g_mx1 - g_mx0) * 0.56f;
    g->w = g_mx1 - 24.0f * s - g->x;
    // club_draw's SQUAD: heading 110 + 32, column names 22, a row 24 each, the injury note 18; then 14 apart
    g->ywal = strcmp(g_cstate, "ok") ? 110.0f * s : (110.0f + 32.0f + 22.0f + 24.0f * (float)g_ncsq + 18.0f + 14.0f) * s;
    fit = (int)((g_ch - 80.0f * s - (g->ywal + 32.0f * s) - 70.0f * s) / (44.0f * s));   // room above the notes
    if (fit < 1) fit = 1;                                            // at least one row: every card stays reachable
    if (fit > MAXWAL) fit = MAXWAL;
    g->fit = fit;
    g->paged = g_nwal > fit;
    if (g_wal_top < 0 || g_wal_top >= g_nwal) g_wal_top = 0;
    g->first = g->paged ? g_wal_top : 0;
    g->n = g_nwal - g->first < fit ? g_nwal - g->first : fit;
    for (i = 0; i < g->n; i++) {
        y = g->ywal + 32.0f * s + (float)i * 44.0f * s;
        g->row[i] = RC(g->x, y, g->x + g->w, y + 40.0f * s);
        g->use[i] = RC(g->x + g->w - 156.0f * s, y + 6.0f * s, g->x + g->w - 6.0f * s, y + 34.0f * s);
    }
    // with pages the page line stays put under a FULL page, so NEXT / PREV never move under the pointer when the last
    // page is shorter (the first build moved them up a row there - fstest_clubcard caught it, 2026-10-08)
    y = g->ywal + 32.0f * s + (float)(g->paged ? g->fit : g->n) * 44.0f * s;
    if (g->paged) {                                                  // in the 24 the "+ N more" text had, a little more
        g->prev = RC(g->x, y + 1.0f * s, g->x + 104.0f * s, y + 25.0f * s);
        g->next = RC(g->x + g->w - 104.0f * s, y + 1.0f * s, g->x + g->w, y + 25.0f * s);
        y += 30.0f * s;
    } else {
        g->prev = g->next = RC(0.0f, 0.0f, 0.0f, 0.0f);
        y += (g_nwal ? 4.0f : 24.0f) * s;
    }
    g->newc = RC(g->x, y, g->x + 250.0f * s, y + 30.0f * s);
}

// the next / previous page of YOUR CARDS, wrapping round (an armed choice on the old page is dropped).  g_board_cs held
static void club_page_locked(const struct CGeo *g, int dir)
{
    int top = g->first + (dir > 0 ? g->fit : -g->fit), last = ((g_nwal - 1) / g->fit) * g->fit;
    if (!g->paged) return;
    if (top >= g_nwal) top = 0;
    else if (top < 0) top = last;
    g_wal_top = top;
    g_wal_armed = -1;
    logline("club: YOUR CARDS page: cards %d-%d of %d", top + 1, g_nwal - top < g->fit ? g_nwal : top + g->fit, g_nwal);
}

static RECT club_button(void)            // "CLUB CARD" on the canvas (the left strip; COMPACT: under KEYS)
{
    if (g_compact)
        return grown(strip_rect(CMP_CLUB_X, CMP_BTN_Y, CMP_CLUB_X + (CLUB_X1 - CLUB_X0), CMP_BTN_Y + (CLUB_Y1 - CLUB_Y0)),
                     GROW_LEFT);
    return grown(RC(CLUB_X0 * g_s, g_py + CLUB_Y0 * g_s, CLUB_X1 * g_s, g_py + CLUB_Y1 * g_s), GROW_LEFT);
}

// The COMPACT layout's right strip, drawn over the skin's own (draw_skin): START, KEY PL, SHOOT and KEEPER painted
// over with the strip's background, then SETTINGS and CLUB CARD, cut from the left strip, under CATALOGUE and KEYS.
// Measured on skin.png (_probe_skin_compact.py, 2026-10-06): the field ends at sheet y 509; START (x 1220-1282) glows
// down to ~597, clear of CATALOGUE (to 1196) and KEYS (from 1312); under the buttons the strip fades from (19,20,25)
// to (16,17,22); its orange edge is x 1060-1065.  The two buttons are cut at their own edges plus their drop shadow
// (6 rows) and nothing more: the left strip's background (23,24,30) is lighter and would show as a box.
static void compact_strip(IDirect3DDevice9 *dev)
{
    RECT st = strip_rect(1206.0f, 524.0f, 1296.0f, 600.0f), low = strip_rect(1066.0f, 586.0f, DES_W, DES_H), a, b;
    set_flat(dev);
    fill_rect(dev, (float)st.left, (float)st.top, (float)(st.right - st.left), (float)(st.bottom - st.top),
              D3DCOLOR_ARGB(255, 18, 19, 24));                                                   // START
    fill_vgrad(dev, (float)low.left, (float)low.top, (float)(low.right - low.left), (float)(low.bottom - low.top),
               D3DCOLOR_ARGB(255, 19, 20, 25), D3DCOLOR_ARGB(255, 16, 17, 22));                  // KEY PL, SHOOT, KEEPER
    skin_states(dev);
    a = strip_rect(CMP_SET_X, CMP_BTN_Y + 1.0f, CMP_SET_X + (SET_X1 - SET_X0), CMP_BTN_Y + 1.0f + 39.0f);
    b = strip_rect(CMP_CLUB_X, CMP_BTN_Y + 1.0f, CMP_CLUB_X + (CLUB_X1 - CLUB_X0), CMP_BTN_Y + 1.0f + 39.0f);
    tex_quad(dev, (float)a.left, (float)a.top, (float)a.right, (float)a.bottom,         // SETTINGS: sheet rows 136-175
             SET_X0 / DES_W, (SET_Y0 + 1.0f) / DES_H, SET_X1 / DES_W, (SET_Y0 + 40.0f) / DES_H);
    tex_quad(dev, (float)b.left, (float)b.top, (float)b.right, (float)b.bottom,         // CLUB CARD: rows 178-217
             CLUB_X0 / DES_W, (CLUB_Y0 + 1.0f) / DES_H, CLUB_X1 / DES_W, (CLUB_Y0 + 40.0f) / DES_H);
}

static RECT club_close(void)
{
    return RC(g_mx1 - 58.0f * g_s, 12.0f * g_s, g_mx1 - 18.0f * g_s, 50.0f * g_s);
}

static void club_draw(IDirect3DDevice9 *dev)
{
    static const char *HEAD[7] = { "NO", "NAME", "POS", "APPS", "GOALS", "AST", "COND" };
    static const float COLX[7] = { 0.0f, 34.0f, 150.0f, 186.0f, 228.0f, 276.0f, 312.0f };
    float s = g_s, x0 = g_mx0, x1 = g_mx1, lx, rx, lw, y; int i, k; RECT cr = club_close();
    DWORD white = D3DCOLOR_ARGB(255, 240, 240, 245), grey = D3DCOLOR_ARGB(255, 150, 156, 170);
    DWORD orange = D3DCOLOR_ARGB(255, 255, 138, 42), rule = D3DCOLOR_ARGB(255, 60, 52, 44);
    if (!g_club) return;
    if (!g_font_tex) build_font(dev);
    lx = x0 + 24.0f * s; rx = x0 + (x1 - x0) * 0.56f; lw = rx - lx - 24.0f * s;
    EnterCriticalSection(&g_board_cs);
    set_flat(dev);
    fill_rect(dev, x0, 0.0f, x1 - x0, g_ch, D3DCOLOR_ARGB(242, 13, 14, 19));                    // over the game
    fill_rect(dev, x0, 0.0f, x1 - x0, 4.0f * s, orange);
    fill_rect(dev, (float)cr.left, (float)cr.top, (float)(cr.right - cr.left), (float)(cr.bottom - cr.top),
              D3DCOLOR_ARGB(255, 70, 75, 88));
    if (g_font_tex) {
        set_picture(dev, g_font_tex, 1);
        put_str(dev, lx, 14.0f * s, 0.85f * s, orange, "CLUB CARD MANAGER");
        put_str(dev, lx, 58.0f * s, 0.42f * s, grey, "the club card in the slot as the game reads it - updated each time the game saves it");
        put_str(dev, lx, 76.0f * s, 0.42f * s, grey, "YOUR CARDS: switch club, or start a new one (the game restarts)    Esc closes this");
        put_in_rect(dev, cr, 0.8f * s, white, "X");
    }
    if (strcmp(g_cstate, "ok")) {                                                            // no club to show
        g_cfix = RC(0.0f, 0.0f, 0.0f, 0.0f);
        const char *msg = !strcmp(g_cstate, "noview") ? "reading the club card - a moment after the start; started with PLAY.exe?" : g_creason;
        if (g_font_tex) put_fit(dev, lx, 130.0f * s, 0.46f * s, !strcmp(g_cstate, "unreadable") ? club_colour('r') : white,
                                msg[0] ? msg : g_cstate, lw);            // the left column: YOUR CARDS is beside it
        y = 180.0f * s;
    } else {
        y = 110.0f * s;
        for (i = 0; i < g_ncl; i++) {                                                        // the left column
            if (g_cl[i].kind == 'h') {
                if (i) y += 12.0f * s;
                set_flat(dev);
                fill_rect(dev, lx, y + 22.0f * s, lw, 2.0f * s, rule);
                if (g_font_tex) { set_picture(dev, g_font_tex, 1); put_str(dev, lx, y, 0.46f * s, orange, g_cl[i].a); }
                y += 32.0f * s;
            } else {
                set_flat(dev);
                fill_rect(dev, lx, y, lw, 28.0f * s, D3DCOLOR_ARGB(255, 24, 26, 34));
                if (g_font_tex) {
                    set_picture(dev, g_font_tex, 1);
                    put_str(dev, lx + 10.0f * s, y + 7.0f * s, 0.40f * s, grey, g_cl[i].a);
                    put_fit(dev, lx + 150.0f * s, y + 5.0f * s, 0.46f * s, club_colour(g_cl[i].col), g_cl[i].b, lw - 158.0f * s);
                }
                y += 32.0f * s;
            }
        }
        if (g_cbad > 0 || !strcmp(g_csession, "cut")) {                // CLEAR BAD ENDINGS, under CARD HEALTH
            int armed = g_wal_armed == WAL_FIX && (LONG)(g_wal_until - GetTickCount()) > 0;
            g_cfix = RC(lx, y + 6.0f * s, lx + 260.0f * s, y + 36.0f * s);
            set_chip(dev, g_cfix, armed ? "CLICK AGAIN TO CLEAR" : "CLEAR BAD ENDINGS", armed, s);
            if (g_font_tex) {
                set_picture(dev, g_font_tex, 1);
                put_fit(dev, lx, y + 44.0f * s, 0.36f * s, grey,
                        "back to 0 at a restart - trade rights the game already took stay lost", lw);
            }
        } else g_cfix = RC(0.0f, 0.0f, 0.0f, 0.0f);
        y = 110.0f * s;                                                                       // the right column
        set_flat(dev);
        fill_rect(dev, rx, y + 22.0f * s, x1 - rx - 24.0f * s, 2.0f * s, rule);
        if (g_font_tex) {
            set_picture(dev, g_font_tex, 1);
            put_str(dev, rx, y, 0.46f * s, orange, "SQUAD");
            y += 32.0f * s;
            for (k = 0; k < 7; k++) put_str(dev, rx + COLX[k] * s, y, 0.36f * s, grey, HEAD[k]);
            y += 22.0f * s;
            for (i = 0; i < g_ncsq; i++) {
                const char *pos = g_csq[i].f[2];
                DWORD pc = pos[0] == 'G' ? D3DCOLOR_ARGB(255, 245, 205, 60) : pos[0] == 'D' ? D3DCOLOR_ARGB(255, 110, 160, 245) :
                           pos[0] == 'M' ? D3DCOLOR_ARGB(255, 110, 210, 120) : D3DCOLOR_ARGB(255, 240, 105, 95);
                put_str(dev, rx + COLX[0] * s, y, 0.42f * s, white, g_csq[i].f[0]);
                put_fit(dev, rx + COLX[1] * s, y, 0.42f * s, strcmp(g_csq[i].f[7], "-") ? club_colour('r') : white,
                        g_csq[i].f[1], (COLX[2] - COLX[1] - 6.0f) * s);
                put_str(dev, rx + COLX[2] * s, y, 0.42f * s, pc, pos);
                for (k = 3; k < 7; k++) put_str(dev, rx + COLX[k] * s, y, 0.42f * s, white, g_csq[i].f[k]);
                y += 24.0f * s;
            }
            put_str(dev, rx, y + 2.0f * s, 0.36f * s, grey, "a name in red: injured");   // the game agrees (Ferdinand)
            y += 18.0f * s;
        }
    }
    if (strcmp(g_cstate, "ok") && g_ncbak && g_font_tex) {             // no club in the slot: the backups, left
        y = 180.0f * s;
        set_flat(dev);
        fill_rect(dev, lx, y + 22.0f * s, lw, 2.0f * s, rule);
        set_picture(dev, g_font_tex, 1);
        put_str(dev, lx, y, 0.46f * s, orange, "BACKUPS");
        y += 32.0f * s;
        for (i = 0; i < g_ncbak; i++) { put_str(dev, lx, y, 0.42f * s, white, g_cbak[i]); y += 22.0f * s; }
        put_str(dev, lx, y + 6.0f * s, 0.38f * s, grey, "in data\\save\\backup - restoring one comes later");
    }
    {                                                                   // YOUR CARDS (right, under the SQUAD)
        struct CGeo g; DWORD now = GetTickCount(); int armed;
        static int said_first = -1, said_n = -1, said_nwal = -1, said_top = -1;
        club_geo(&g);
        armed = g_wal_armed >= 0 && (LONG)(g_wal_until - now) > 0 ? g_wal_armed : -1;
        if (g.first != said_first || g.n != said_n || g_nwal != said_nwal || (int)g.ywal != said_top) {
            said_first = g.first; said_n = g.n; said_nwal = g_nwal; said_top = (int)g.ywal;   // once per change: where
            logline("club: YOUR CARDS shows cards %d-%d of %d%s; play %d,%d step %d", g.n ? g.first + 1 : 0,
                    g.first + g.n, g_nwal, g.paged ? " (pages)" : "", g.n ? (int)(g.use[0].left + g.use[0].right) / 2 : 0,
                    g.n ? (int)(g.use[0].top + g.use[0].bottom) / 2 : 0, (int)(44.0f * s));
            if (g.paged)
                logline("club: page buttons: prev %d,%d next %d,%d", (int)(g.prev.left + g.prev.right) / 2,
                        (int)(g.prev.top + g.prev.bottom) / 2, (int)(g.next.left + g.next.right) / 2,
                        (int)(g.next.top + g.next.bottom) / 2);
        }
        set_flat(dev);
        fill_rect(dev, g.x, g.ywal + 22.0f * s, g.w, 2.0f * s, rule);
        for (i = 0; i < g.n; i++)
            fill_rect(dev, (float)g.row[i].left, (float)g.row[i].top, g.w, (float)(g.row[i].bottom - g.row[i].top),
                      D3DCOLOR_ARGB(255, 24, 26, 34));
        if (g_font_tex) {
            set_picture(dev, g_font_tex, 1);
            put_str(dev, g.x, g.ywal, 0.46f * s, orange, "YOUR CARDS");
            for (i = 0; i < g.n; i++) {
                const struct CWal *c = &g_wal[g.first + i];
                float tw = (float)g.use[i].left - g.x - 18.0f * s;
                put_fit(dev, g.x + 10.0f * s, (float)g.row[i].top + 4.0f * s, 0.46f * s, white, c->club, tw);
                put_fit(dev, g.x + 10.0f * s, (float)g.row[i].top + 22.0f * s, 0.38f * s, grey, c->summary, tw);
            }
            if (!g_nwal)
                put_str(dev, g.x, g.ywal + 34.0f * s, 0.38f * s, grey, "no other cards yet - NEW CLUB CARD keeps this one safe here");
            else if (g.paged) {
                char pg[48];
                _snprintf(pg, sizeof pg, "cards %d-%d of %d", g.first + 1, g.first + g.n, g_nwal); pg[47] = 0;
                put_in_rect(dev, RC((float)g.prev.right, (float)g.prev.top, (float)g.next.left, (float)g.prev.bottom),
                            0.40f * s, grey, pg);
            }
        }
        for (i = 0; i < g.n; i++)
            if (!g_wal[g.first + i].dead)
                set_chip(dev, g.use[i], armed == g.first + i ? "CLICK AGAIN" : "PLAY THIS CLUB", armed == g.first + i, s);
        if (g_font_tex) {                                // a transferred card: a word, not a button
            set_picture(dev, g_font_tex, 1);
            for (i = 0; i < g.n; i++)
                if (g_wal[g.first + i].dead) put_in_rect(dev, g.use[i], 0.40f * s, grey, "TRANSFERRED");
        }
        if (g.paged) {
            set_chip(dev, g.prev, "< PREV", 0, s);
            set_chip(dev, g.next, "NEXT >", 0, s);
        }
        set_chip(dev, g.newc, armed == WAL_NEW ? "CLICK AGAIN FOR A NEW CARD" : "NEW CLUB CARD", armed == WAL_NEW, s);
        if (g_font_tex) {
            set_picture(dev, g_font_tex, 1);
            put_fit(dev, g.x, (float)g.newc.bottom + 8.0f * s, 0.36f * s,
                    !strcmp(g_csession, "open") ? club_colour('r') : grey,
                    !strcmp(g_csession, "open") ? "not during a card session - after the locker-room save"
                                                : "a switch restarts the game; no card is ever deleted", g.w);
        }
    }
    if (g_font_tex && g_bmsg[0] && (LONG)(g_bmsg_until - GetTickCount()) > 0) {             // the last click's note
        RECT nr = RC(x0 + (x1 - x0) * 0.15f, g_ch - 70.0f * s, x1 - (x1 - x0) * 0.15f, g_ch - 22.0f * s);
        set_flat(dev);
        fill_rect(dev, (float)nr.left, (float)nr.top, (float)(nr.right - nr.left), (float)(nr.bottom - nr.top),
                  D3DCOLOR_ARGB(240, 24, 26, 33));
        set_picture(dev, g_font_tex, 1);
        put_in_rect(dev, nr, 0.56f * s, g_bmsg_col, g_bmsg);
    }
    LeaveCriticalSection(&g_board_cs);
}

// a press inside the open panel: X, a card's PLAY THIS CLUB, NEW CLUB CARD - each switch armed by a first click,
// done by a second within 8 s: card=FILE / card=new into data\panel.txt, then RESTART NOW (the helper, outside)
static void club_click(HWND h, int x, int y)
{
    struct CGeo g; int i, pick = -1; DWORD now = GetTickCount();
    DWORD green = D3DCOLOR_ARGB(255, 120, 230, 120), yellow = D3DCOLOR_ARGB(255, 255, 214, 40);
    DWORD red = D3DCOLOR_ARGB(255, 255, 110, 90);
    RECT xr = club_close();
    if (in_rect(&xr, x, y)) { club_open(h, 0); return; }
    EnterCriticalSection(&g_board_cs);
    club_geo(&g);
    if (g.paged && (in_rect(&g.prev, x, y) || in_rect(&g.next, x, y))) {    // a page, not a choice
        club_page_locked(&g, in_rect(&g.next, x, y) ? 1 : -1);
        LeaveCriticalSection(&g_board_cs);
        return;
    }
    for (i = 0; i < g.n; i++) if (in_rect(&g.use[i], x, y) && !g_wal[g.first + i].dead) pick = g.first + i;
    if (in_rect(&g.newc, x, y)) pick = WAL_NEW;
    if (in_rect(&g_cfix, x, y)) pick = WAL_FIX;
    if (pick < 0) { LeaveCriticalSection(&g_board_cs); return; }
    if (g_rs_sent) {
        note_locked(yellow, "already asked - the game closes and opens again");
    } else if (!strcmp(g_csession, "open")) {                       // the card rule, said before anything moves
        note_locked(red, "not during a card session - after the locker-room save");
        logline("club: switch refused - a card session is open");
    } else if (pick == WAL_NEW && !strcmp(g_cstate, "none")) {
        note_locked(yellow, "the slot already holds a blank card - put it in (CARD) and the game makes a club");
    } else if (g_wal_armed != pick || (LONG)(g_wal_until - now) <= 0) {
        g_wal_armed = pick; g_wal_until = now + 8000;                  // 4 s ran out once for the player: 8
        if (pick == WAL_FIX) note_locked(yellow, "click again: the bad endings go back to 0 - the game restarts");
        else if (pick == WAL_NEW) note_locked(yellow, "click again: this club goes to YOUR CARDS, a new card into the slot");
        else note_locked(yellow, "click again to play %s - the game restarts with it", g_wal[pick].club);
        logline("club: %s armed", pick == WAL_FIX ? "clear bad endings" : pick == WAL_NEW ? "new card" : g_wal[pick].file);
    } else {
        g_wal_armed = -1;
        set_load_locked();                                          // the settings file as it is now, plus this
        if (pick == WAL_FIX) g_fix_req = 1;
        else lstrcpynA(g_card_req, pick == WAL_NEW ? "new" : g_wal[pick].file, sizeof g_card_req);
        if (!set_save_locked()) note_locked(red, "could not save data\\panel.txt - try again");
        else if (!restart_request())
            note_locked(red, "could not ask for the restart - close the game, then PLAY.exe does the switch");
        else {
            g_rs_sent = now;
            note_locked(green, pick == WAL_FIX ? "clearing the bad endings - the game closes and opens again"
                                               : "switching - the game closes and opens again (about a minute)");
            if (pick == WAL_FIX) logline("club: clear bad endings requested");
            else logline("club: switch to %s requested", g_card_req);
        }
    }
    LeaveCriticalSection(&g_board_cs);
}

static void club_wheel(int delta)        // the mouse wheel over the open panel: YOUR CARDS a page on (down) or back (up)
{
    struct CGeo g;
    EnterCriticalSection(&g_board_cs);
    club_geo(&g);
    if (g.paged && delta) club_page_locked(&g, delta < 0 ? 1 : -1);
    LeaveCriticalSection(&g_board_cs);
}

static void club_open(HWND h, int open)
{
    g_club = open;
    if (open) { InterlockedExchange(&g_club_dirty, 1); SetPropA(h, "WCCF_TYPING", (HANDLE)1); }   // keys are not buttons
    else RemovePropA(h, "WCCF_TYPING");
    logline("club %s", open ? "opened" : "closed");
}

// ---------------------------------------------------------------- composing the picture
// Everything our drawing needs, set on top of whatever the game left (the caller's state block puts it all back).
static void set_2d_states(IDirect3DDevice9 *dev)
{
    D3DVIEWPORT9 vp = { 0, 0, (DWORD)g_cw, (DWORD)g_ch, 0.0f, 1.0f };   // the whole canvas
    IDirect3DDevice9_SetViewport(dev, &vp);
    IDirect3DDevice9_SetVertexShader(dev, NULL);
    IDirect3DDevice9_SetPixelShader(dev, NULL);
    IDirect3DDevice9_SetFVF(dev, FVF_2D);
    IDirect3DDevice9_SetRenderState(dev, D3DRS_LIGHTING, FALSE);
    IDirect3DDevice9_SetRenderState(dev, D3DRS_ZENABLE, D3DZB_FALSE);
    IDirect3DDevice9_SetRenderState(dev, D3DRS_ZWRITEENABLE, FALSE);
    IDirect3DDevice9_SetRenderState(dev, D3DRS_CULLMODE, D3DCULL_NONE);
    IDirect3DDevice9_SetRenderState(dev, D3DRS_FILLMODE, D3DFILL_SOLID);
    IDirect3DDevice9_SetRenderState(dev, D3DRS_SCISSORTESTENABLE, FALSE);
    IDirect3DDevice9_SetRenderState(dev, D3DRS_FOGENABLE, FALSE);
    IDirect3DDevice9_SetRenderState(dev, D3DRS_STENCILENABLE, FALSE);
    IDirect3DDevice9_SetRenderState(dev, D3DRS_COLORWRITEENABLE, 0x0000000F);
    IDirect3DDevice9_SetRenderState(dev, D3DRS_SRGBWRITEENABLE, FALSE);
    IDirect3DDevice9_SetRenderState(dev, D3DRS_ALPHABLENDENABLE, TRUE);
    IDirect3DDevice9_SetRenderState(dev, D3DRS_SRCBLEND, D3DBLEND_SRCALPHA);
    IDirect3DDevice9_SetRenderState(dev, D3DRS_DESTBLEND, D3DBLEND_INVSRCALPHA);
    IDirect3DDevice9_SetRenderState(dev, D3DRS_BLENDOP, D3DBLENDOP_ADD);
    IDirect3DDevice9_SetRenderState(dev, D3DRS_ALPHATESTENABLE, FALSE);
    IDirect3DDevice9_SetTextureStageState(dev, 0, D3DTSS_TEXCOORDINDEX, 0);
    IDirect3DDevice9_SetTextureStageState(dev, 0, D3DTSS_TEXTURETRANSFORMFLAGS, D3DTTFF_DISABLE);
    IDirect3DDevice9_SetTextureStageState(dev, 1, D3DTSS_COLOROP, D3DTOP_DISABLE);
    IDirect3DDevice9_SetTextureStageState(dev, 1, D3DTSS_ALPHAOP, D3DTOP_DISABLE);
    IDirect3DDevice9_SetSamplerState(dev, 0, D3DSAMP_ADDRESSU, D3DTADDRESS_CLAMP);
    IDirect3DDevice9_SetSamplerState(dev, 0, D3DSAMP_ADDRESSV, D3DTADDRESS_CLAMP);
    IDirect3DDevice9_SetSamplerState(dev, 0, D3DSAMP_MIPFILTER, D3DTEXF_NONE);
    IDirect3DDevice9_SetSamplerState(dev, 0, D3DSAMP_SRGBTEXTURE, 0);
    IDirect3DDevice9_SetTexture(dev, 0, NULL);
}

// ---------------------------------------------------------------- the ping meter (2026-10-07)
// Online (play.py remote sets WCCF_RELAY=ADDRESS:PORT for the cabinet), a thread asks the server's relay (_relay.py,
// UDP 20040) for an echo every 2 s - "WRL1" "P" + a number, answered "WRL1" "Q" + the same number - and the round trip
// is drawn at the top right, above the game's picture: four bars and "80 ms", green under 100 ms, yellow under 200,
// red from 200, grey "--" when nothing has come back for 6 s.  It travels the way a match's packets do (UDP, through the relay), on
// a socket of its own: the game's sockets and the relay hooks are not involved.  Every minute it logs the answers, the
// lost ones and min / average / max - the timing that was missing when a match felt laggy (2026-10-06).
#ifndef SIO_UDP_CONNRESET
#define SIO_UDP_CONNRESET _WSAIOW(IOC_VENDOR, 12)
#endif
#define PING_MAGIC "WRL1"
static volatile LONG g_ping_ms = -1, g_ping_tick = 0, g_ping_on = 0;
static struct sockaddr_in g_ping_to;

static long ping_once(SOCKET s, unsigned seq)     // one echo: the round trip in ms, or -1 (nothing within 1.5 s)
{
    char p[9], r[64]; LARGE_INTEGER f, t0, t1; int n, k;
    QueryPerformanceFrequency(&f);
    memcpy(p, PING_MAGIC, 4); p[4] = 'P'; memcpy(p + 5, &seq, 4);
    QueryPerformanceCounter(&t0);
    if (sendto(s, p, 9, 0, (const struct sockaddr *)&g_ping_to, sizeof g_ping_to) == SOCKET_ERROR) return -1;
    for (k = 0; k < 8; k++) {                     // the answer to THIS echo; a late one to an earlier echo is skipped
        n = recvfrom(s, r, sizeof r, 0, NULL, NULL);
        if (n == SOCKET_ERROR) return -1;         // the 1.5 s wait ran out
        if (n == 9 && !memcmp(r, PING_MAGIC, 4) && r[4] == 'Q' && !memcmp(r + 5, &seq, 4)) {
            QueryPerformanceCounter(&t1);
            return (long)((t1.QuadPart - t0.QuadPart) * 1000 / f.QuadPart);
        }
    }
    return -1;
}

static DWORD WINAPI ping_watch(LPVOID arg)
{
    WSADATA wd; SOCKET s; DWORD tv = 1500, next, t; unsigned seq = 0; long ms, mn = 0, mx = 0, sum = 0;
    int got = 0, lost = 0, said = 0; BOOL no = FALSE; DWORD br = 0;
    (void)arg;
    WSAStartup(MAKEWORD(2, 2), &wd);
    s = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    if (s == INVALID_SOCKET) { logline("ping: off - no socket (error %d)", WSAGetLastError()); return 0; }
    setsockopt(s, SOL_SOCKET, SO_RCVTIMEO, (const char *)&tv, sizeof tv);
    WSAIoctl(s, SIO_UDP_CONNRESET, &no, sizeof no, NULL, 0, &br, NULL, NULL);   // a closed port: no answer, not an error
    InterlockedExchange(&g_ping_on, 1);
    next = GetTickCount() + 60000;
    for (;;) {
        t = GetTickCount();
        ms = ping_once(s, ++seq);
        if (ms >= 0) {
            InterlockedExchange(&g_ping_ms, ms);
            InterlockedExchange(&g_ping_tick, (LONG)GetTickCount());
            if (!said) { said = 1; logline("ping: the server's relay answers - %ld ms", ms); }
            if (!got || ms < mn) mn = ms;
            if (ms > mx) mx = ms;
            sum += ms; got++;
        } else lost++;
        if ((LONG)(GetTickCount() - next) >= 0) {
            if (got) logline("ping: last minute %d answers, %d lost, %ld / %ld / %ld ms (min / average / max)", got, lost,
                             mn, sum / got, mx);
            else logline("ping: last minute no answer from the server's relay (%d asked)", lost);
            got = lost = 0; sum = mn = mx = 0; next = GetTickCount() + 60000;
        }
        t = GetTickCount() - t;
        if (t < 2000) Sleep(2000 - t);
    }
}

static void ping_install(void)                    // a cabinet playing online: play.py set WCCF_RELAY=ADDRESS:PORT
{
    char v[64], *colon; unsigned long ip; int port;
    if (GetEnvironmentVariableA("WCCF_RELAY", v, sizeof v) == 0) return;              // this PC alone: no meter
    colon = strchr(v, ':');
    if (!colon) { logline("ping: off - WCCF_RELAY is not ADDRESS:PORT (%s)", v); return; }
    *colon = 0;
    ip = inet_addr(v); port = atoi(colon + 1);
    if (ip == INADDR_NONE || port < 1 || port > 65535) { logline("ping: off - not an address: %s:%s", v, colon + 1); return; }
    memset(&g_ping_to, 0, sizeof g_ping_to);
    g_ping_to.sin_family = AF_INET; g_ping_to.sin_addr.s_addr = ip; g_ping_to.sin_port = htons((u_short)port);
    CreateThread(NULL, 0, ping_watch, NULL, 0, NULL);
    logline("ping: on - asking %s:%d every 2 s, shown top right above the game", v, port);
}

static void ping_draw(IDirect3DDevice9 *dev)      // the meter, top right above the game (the player's place for it, 2026-10-07)
{
    float s = g_s, bw = 10.0f * s, gap = 4.0f * s, tscale = 0.8f * s, lscale = 0.42f * s, blockh = 62.0f * s;
    float midW, a, gw, gh, gx1, gy0, right, top, x, y, tw, lw, roww; LONG ms; int bars, i, inside;
    DWORD col, dim = D3DCOLOR_ARGB(255, 58, 62, 74), grey = D3DCOLOR_ARGB(255, 150, 156, 170); char txt[24];
    if (!g_ping_on) return;                       // online only
    ms = g_ping_ms;
    if (ms >= 0 && GetTickCount() - (DWORD)g_ping_tick > 6000) ms = -1;              // nothing for 6 s: no answer
    if (ms < 0) { col = grey; bars = 0; _snprintf(txt, sizeof txt, "-- ms"); }
    else {
        if (ms < 100)      { col = D3DCOLOR_ARGB(255, 70, 200, 90);  bars = ms < 50 ? 4 : 3; }
        else if (ms < 200) { col = D3DCOLOR_ARGB(255, 240, 200, 50); bars = 2; }
        else               { col = D3DCOLOR_ARGB(255, 230, 70, 60);  bars = 1; }
        _snprintf(txt, sizeof txt, "%ld ms", ms);
    }
    txt[sizeof txt - 1] = 0;
    if (!g_font_tex) build_font(dev);
    // where the game's picture is (draw_game_scaled's own sums): the meter sits in the band above it, against the
    // picture's right edge; a window with no band for it gets it just inside the picture's top right, on a dark box
    midW = g_mx1 - g_mx0; a = (g_gw && g_gh) ? (float)g_gw / (float)g_gh : 1.6f;
    gw = midW; gh = midW / a;
    if (gh > g_ch) { gh = g_ch; gw = gh * a; }
    gx1 = g_mx0 + (midW - gw) * 0.5f + gw; gy0 = (g_ch - gh) * 0.5f;
    inside = gy0 < blockh;
    right = gx1 - 14.0f * s;
    top = inside ? gy0 + 8.0f * s : (gy0 - blockh) * 0.5f;
    tw = g_font_tex ? str_w(txt, tscale) : 0.0f;
    lw = g_font_tex ? str_w("PING TO SERVER", lscale) : 0.0f;
    roww = 4 * bw + 3 * gap + 10.0f * s + tw;
    set_flat(dev);
    if (inside) fill_rect(dev, right - (roww > lw ? roww : lw) - 8.0f * s, top - 4.0f * s,
                          (roww > lw ? roww : lw) + 16.0f * s, blockh + 8.0f * s, D3DCOLOR_ARGB(190, 10, 11, 15));
    x = right - roww; y = top;
    for (i = 0; i < 4; i++) {                     // four rising bars, lit up to `bars`
        float h = (10.0f + 8.0f * i) * s;
        fill_rect(dev, x + i * (bw + gap), y + 36.0f * s - h, bw, h, i < bars ? col : dim);
    }
    if (g_font_tex) {
        set_picture(dev, g_font_tex, 1);
        put_str(dev, right - tw, y + 6.0f * s, tscale, col, txt);
        put_str(dev, right - lw, y + 46.0f * s, lscale, grey, "PING TO SERVER");
    }
}

// The whole picture, into whatever render target is bound (its size = the canvas layout() last ran for).
// have_game 0 = the frame copy failed: no wipe, the panels go over the game's own frame as they did originally.
static void compose(IDirect3DDevice9 *dev, int have_game)
{
    if (!g_skin) load_skin(dev);
    set_2d_states(dev);
    if (have_game) IDirect3DDevice9_Clear(dev, 0, NULL, D3DCLEAR_TARGET, D3DCOLOR_XRGB(11, 11, 15), 1.0f, 0);
    if (SUCCEEDED(IDirect3DDevice9_BeginScene(dev))) {
        if (have_game) draw_game_scaled(dev);       // the game in the middle
        draw_skin(dev);                             // the panels on the sides
        board_draw(dev);                            // the player's cards on the formation pitch
        ping_draw(dev);                             // the ping meter, online (under the panels that open on top)
        browse_draw(dev);                           // the card browser, when it is open
        keys_draw(dev);                             // the KEYS panel, when it is open
        set_draw(dev);                              // the SETTINGS panel, when it is open
        club_draw(dev);                             // the CLUB CARD panel, when it is open
        close_draw(dev);                            // a close during a card session: the warning
        IDirect3DDevice9_EndScene(dev);
    }
}

// The main path: compose at the window's own size on our swap chain and show it.  Returns 0 if any step is not
// possible (nothing shown), and the caller falls back to the old path for this frame.
static int present_composed(IDirect3DDevice9 *dev, HWND wnd, HRESULT *phr)
{
    if (g_sc_fail) return 0;
    if (!g_devwnd) {
        IDirect3DSwapChain9 *imp = NULL; D3DPRESENT_PARAMETERS ip; D3DDEVICE_CREATION_PARAMETERS cp;
        if (SUCCEEDED(IDirect3DDevice9_GetSwapChain(dev, 0, &imp)) && imp) {
            if (SUCCEEDED(IDirect3DSwapChain9_GetPresentParameters(imp, &ip))) g_devwnd = ip.hDeviceWindow;
            IDirect3DSwapChain9_Release(imp);
        }
        if (!g_devwnd && SUCCEEDED(IDirect3DDevice9_GetCreationParameters(dev, &cp))) g_devwnd = cp.hFocusWindow;
        logline("game draws into window %p", (void *)g_devwnd);
    }
    HWND target = wnd ? wnd : g_devwnd;
    RECT cr;
    if (!target || IsIconic(target) || !GetClientRect(target, &cr) || cr.right < 64 || cr.bottom < 64) return 0;
    if (!ensure_sc(dev, target, (UINT)cr.right, (UINT)cr.bottom)) return 0;

    IDirect3DStateBlock9 *sb = NULL;
    IDirect3DSurface9 *bb = NULL, *scbb = NULL, *oldrt = NULL, *oldds = NULL;
    D3DVIEWPORT9 vp; D3DSURFACE_DESC gd; int ok = 0;
    if (FAILED(IDirect3DDevice9_CreateStateBlock(dev, D3DSBT_ALL, &sb)) || !sb) return 0;
    IDirect3DDevice9_GetViewport(dev, &vp);
    if (SUCCEEDED(IDirect3DDevice9_GetBackBuffer(dev, 0, 0, D3DBACKBUFFER_TYPE_MONO, &bb)) && bb &&
        SUCCEEDED(IDirect3DSwapChain9_GetBackBuffer(g_sc, 0, D3DBACKBUFFER_TYPE_MONO, &scbb)) && scbb &&
        SUCCEEDED(IDirect3DDevice9_GetRenderTarget(dev, 0, &oldrt)) && oldrt) {
        IDirect3DSurface9_GetDesc(bb, &gd);
        g_gw = g_bw = gd.Width; g_gh = g_bh = gd.Height;
        // the game's finished frame -> our texture, same size; without it there is no picture to show
        if (ensure_gametex(dev, gd.Width, gd.Height) &&
            SUCCEEDED(IDirect3DDevice9_StretchRect(dev, bb, NULL, g_gamesurf, NULL, D3DTEXF_LINEAR))) {
            if (FAILED(IDirect3DDevice9_GetDepthStencilSurface(dev, &oldds))) oldds = NULL;
            IDirect3DDevice9_SetRenderTarget(dev, 0, scbb);
            IDirect3DDevice9_SetDepthStencilSurface(dev, NULL);    // the game's depth buffer is smaller than ours
            layout((UINT)cr.right, (UINT)cr.bottom);
            compose(dev, 1);
            maybe_dump(dev, scbb, (UINT)cr.right, (UINT)cr.bottom);
            IDirect3DDevice9_SetRenderTarget(dev, 0, oldrt);           // state blocks do not hold these two
            IDirect3DDevice9_SetDepthStencilSurface(dev, oldds);
            ok = 1;
        }
    }
    if (oldds) IDirect3DSurface9_Release(oldds);
    if (oldrt) IDirect3DSurface9_Release(oldrt);
    if (scbb)  IDirect3DSurface9_Release(scbb);
    if (bb)    IDirect3DSurface9_Release(bb);
    IDirect3DDevice9_SetViewport(dev, &vp);
    IDirect3DStateBlock9_Apply(sb);
    IDirect3DStateBlock9_Release(sb);
    if (!ok) return 0;

    *phr = IDirect3DSwapChain9_Present(g_sc, NULL, NULL, NULL, NULL, 0);
    if (++g_sc_frames == 1)
        logline("first composed frame shown (canvas %ldx%ld, hr=0x%08lX)", cr.right, cr.bottom, (unsigned long)*phr);
    return 1;
}

// The old path (fallback): compose inside the game's own back-buffer; the game's own Present then shows it.
// Only right while the window is the game's own size, so the window is put back to windowed if this takes over.
static void compose_into_game_bb(IDirect3DDevice9 *dev)
{
    IDirect3DStateBlock9 *sb = NULL; IDirect3DSurface9 *bb = NULL; D3DSURFACE_DESC desc; D3DVIEWPORT9 vp;
    if (FAILED(IDirect3DDevice9_CreateStateBlock(dev, D3DSBT_ALL, &sb)) || !sb) return;
    IDirect3DDevice9_GetViewport(dev, &vp);
    if (SUCCEEDED(IDirect3DDevice9_GetBackBuffer(dev, 0, 0, D3DBACKBUFFER_TYPE_MONO, &bb)) && bb) {
        IDirect3DSurface9_GetDesc(bb, &desc);
        g_gw = g_bw = desc.Width; g_gh = g_bh = desc.Height;
        layout(desc.Width, desc.Height);
        // letterbox: copy the game's frame; compose() wipes the buffer and redraws it shrunk into the middle
        int lb = ensure_gametex(dev, desc.Width, desc.Height) &&
                 SUCCEEDED(IDirect3DDevice9_StretchRect(dev, bb, NULL, g_gamesurf, NULL, D3DTEXF_LINEAR));
        compose(dev, lb);
        maybe_dump(dev, bb, desc.Width, desc.Height);
        IDirect3DSurface9_Release(bb);
    }
    IDirect3DDevice9_SetViewport(dev, &vp);
    IDirect3DStateBlock9_Apply(sb);
    IDirect3DStateBlock9_Release(sb);
}

// ask the window's own thread to change fullscreen (never resized from the render thread)
static void ask_fullscreen(int on)
{
    if (!g_hwnd || g_fs_msg_pending) return;
    g_fs_msg_pending = 1;
    if (!PostMessageA(g_hwnd, WM_WCCF_FS, (WPARAM)on, 0)) g_fs_msg_pending = 0;
}

// ---------------------------------------------------------------- the Present hook
static HRESULT WINAPI hook_present(IDirect3DDevice9 *dev, const RECT *src, const RECT *dst, HWND wnd, const RGNDATA *dirty)
{
    HRESULT hr;
    if (g_in_present) {                          // our own swap chain's Present came back through here
        static int said = 0;
        if (!said) { said = 1; logline("Present re-entered from inside the hook (passed straight through)"); }
        return g_orig_present(dev, src, dst, wnd, dirty);
    }
    g_in_present = 1;
    g_frames++;
    if (g_frames == 1) logline("Present hook is live (first frame)");
    frame_stats_tick();

    // release a held key once its minimum hold has elapsed and the mouse is up
    if (g_held_vk && !g_mouse_down && (GetTickCount() - g_down_tick) >= 140) {
        send_key(g_held_vk, 1); g_held_vk = 0; g_held_btn = -1;
    }
    dispenser_tick();
    if (g_write_pending) {                       // a card move FPR_Emu was reading over: swap it in now
        EnterCriticalSection(&g_board_cs);
        if (g_write_pending) write_table_locked();
        LeaveCriticalSection(&g_board_cs);
    }

    if (present_composed(dev, wnd, &hr)) {
        // shown at the window's own size, so a bigger window is safe: maximize once, at start-up
        if (g_want_fs && !g_fs_asked && g_hwnd && !g_fs_msg_pending) { g_fs_asked = 1; ask_fullscreen(1); }
    } else {
        // the old path cannot fill a bigger window without stretching: back to the game's own size
        if (g_sc_fail && g_hwnd && is_maximized(g_hwnd)) ask_fullscreen(0);
        compose_into_game_bb(dev);
        hr = g_orig_present(dev, src, dst, wnd, dirty);
    }
    g_in_present = 0;
    return hr;
}

// ---------------------------------------------------------------- the window: normal title bar, maximized
// the player (2026-10-04), after seeing it borderless: "fullscreen is working but there should be the close and the
// minimize, just like the normal window" - and, maximized with its title bar: "working perfectly".  So the game's
// window gets minimize + maximize/restore buttons and is MAXIMIZED: it fills the screen above the taskbar, title bar
// kept.  F11, or the title bar's own middle button, toggles maximized <-> the game's own window size.
static RECT g_test_saved;
static int  g_test_max = 0;

static int test_rect(RECT *m)            // WCCFPANEL_FS_RECT (tests): a pretend screen, off every real monitor
{
    char e[64]; int x, y, w, ht;
    if (GetEnvironmentVariableA("WCCFPANEL_FS_RECT", e, sizeof e) > 0 &&
        sscanf(e, "%d,%d,%d,%d", &x, &y, &w, &ht) == 4 && w > 0 && ht > 0) {
        m->left = x; m->top = y; m->right = x + w; m->bottom = y + ht; return 1;
    }
    return 0;
}

static int is_maximized(HWND h)
{
    RECT m;
    return test_rect(&m) ? g_test_max : (IsZoomed(h) ? 1 : 0);
}

static void set_maximized(HWND h, int on)
{
    RECT m, cr;
    if (!h) return;
    LONG st = GetWindowLongA(h, GWL_STYLE);
    LONG want = (st & ~(LONG)WS_POPUP) | (LONG)(WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX | WS_MAXIMIZEBOX);
    if (want != st) {                                  // the title bar gets its minimize + maximize/restore buttons
        SetWindowLongA(h, GWL_STYLE, want);
        SetWindowPos(h, NULL, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOOWNERZORDER |
                     SWP_NOACTIVATE | SWP_FRAMECHANGED);
    }
    if (test_rect(&m)) {                               // tests: onto the pretend screen, never activated
        if (on && !g_test_max) {
            GetWindowRect(h, &g_test_saved);
            SetWindowPos(h, NULL, m.left, m.top, m.right - m.left, m.bottom - m.top,
                         SWP_NOZORDER | SWP_NOOWNERZORDER | SWP_NOACTIVATE);
            g_test_max = 1;
        } else if (!on && g_test_max) {
            SetWindowPos(h, NULL, g_test_saved.left, g_test_saved.top, g_test_saved.right - g_test_saved.left,
                         g_test_saved.bottom - g_test_saved.top, SWP_NOZORDER | SWP_NOOWNERZORDER | SWP_NOACTIVATE);
            g_test_max = 0;
        }
    } else {
        ShowWindow(h, on ? SW_MAXIMIZE : SW_RESTORE);  // exactly what the title bar's own button does
    }
    GetClientRect(h, &cr);
    logline("%s: client now %ldx%ld", on ? "maximized" : "window", cr.right, cr.bottom);
}

// ---------------------------------------------------------------- mouse (subclass the game window)
// window pixels -> canvas pixels (the same thing on the main path; differs only if the old path runs in a bigger window)
static void to_canvas(HWND h, int *x, int *y)
{
    RECT cr;
    if (GetClientRect(h, &cr) && cr.right > 0 && cr.bottom > 0) {
        *x = (int)((float)*x * g_cw / (float)cr.right);
        *y = (int)((float)*y * g_ch / (float)cr.bottom);
    }
}

static int button_at(int x, int y)
{
    for (int i = 0; i < NBTN; i++) {
        RECT r = g_btn[i].px;
        if (x >= r.left && x < r.right && y >= r.top && y < r.bottom) return i;
    }
    return -1;
}

static LRESULT CALLBACK wndproc(HWND h, UINT m, WPARAM wp, LPARAM lp)
{
    if (m == WM_WCCF_FS) { g_fs_msg_pending = 0; set_maximized(h, (int)wp); return 0; }
    if (m == WM_CLOSE && !close_allowed()) return 0;               // a match is on: warned once (close_allowed)
    if (m == WM_DEVICECHANGE) InterlockedExchange(&g_pad_rescan, 1);   // plugged in or out: KEYS looks again (passed on)
    if ((m == WM_KEYDOWN || m == WM_KEYUP) && wp == VK_F11) {        // F11: maximized <-> window (the game never sees it)
        if (m == WM_KEYDOWN && !(lp & 0x40000000) && g_sc_frames > 0 && !g_sc_fail) set_maximized(h, !is_maximized(h));
        return 0;
    }
    if (g_club && (m == WM_KEYDOWN || m == WM_SYSKEYDOWN)) { if (wp == VK_ESCAPE) club_open(h, 0); return 0; }
    if (g_club && m == WM_MOUSEWHEEL) { club_wheel(GET_WHEEL_DELTA_WPARAM(wp)); return 0; }     // YOUR CARDS' pages
    if (g_club && (m == WM_KEYUP || m == WM_SYSKEYUP || m == WM_CHAR || m == WM_SYSCHAR)) return 0;
    if (g_set && (m == WM_KEYDOWN || m == WM_SYSKEYDOWN)) { set_key(h, wp, lp); return 0; }     // SETTINGS: its typing
    if (g_set && (m == WM_KEYUP || m == WM_SYSKEYUP || m == WM_CHAR || m == WM_SYSCHAR || m == WM_MOUSEWHEEL)) return 0;
    if (g_keys && (m == WM_KEYDOWN || m == WM_SYSKEYDOWN)) { keys_key(h, wp, lp); return 0; }   // KEYS: the new key
    if (g_keys && (m == WM_KEYUP || m == WM_SYSKEYUP || m == WM_CHAR || m == WM_SYSCHAR || m == WM_MOUSEWHEEL)) return 0;
    if (g_browse && m == WM_KEYDOWN) { browse_key(h, wp, lp); return 0; }       // the browser's search line
    if (g_browse && (m == WM_KEYUP || m == WM_CHAR)) return 0;
    if (g_browse && m == WM_MOUSEWHEEL) { browse_wheel(GET_WHEEL_DELTA_WPARAM(wp) / WHEEL_DELTA); return 0; }
    if (m == WM_LBUTTONDOWN) {
        int wx = (short)LOWORD(lp), wy = (short)HIWORD(lp), x = wx, y = wy, card = 0;
        to_canvas(h, &x, &y);
        RECT ab = add_button(), kb = keys_button(), sb = set_button(), cb = club_button();
        if (x >= ab.left && x < ab.right && y >= ab.top && y < ab.bottom) {   // "+ CARD": the browser open / shut
            if (!g_browse && g_keys) keys_open(h, 0);                         // one panel at a time
            if (!g_browse && g_set) set_open(h, 0);
            if (!g_browse && g_club) club_open(h, 0);
            browse_open(h, !g_browse);
            return 0;
        }
        if (in_rect(&kb, x, y)) {                                              // KEYS: its panel open / shut
            if (!g_keys && g_browse) browse_open(h, 0);
            if (!g_keys && g_set) set_open(h, 0);
            if (!g_keys && g_club) club_open(h, 0);
            keys_open(h, !g_keys);
            return 0;
        }
        if (in_rect(&sb, x, y)) {                                              // SETTINGS: its panel open / shut
            if (!g_set && g_browse) browse_open(h, 0);
            if (!g_set && g_keys) keys_open(h, 0);
            if (!g_set && g_club) club_open(h, 0);
            set_open(h, !g_set);
            return 0;
        }
        if (in_rect(&cb, x, y)) {                                              // CLUB CARD: its panel open / shut
            if (!g_club && g_browse) browse_open(h, 0);
            if (!g_club && g_keys) keys_open(h, 0);
            if (!g_club && g_set) set_open(h, 0);
            club_open(h, !g_club);
            return 0;
        }
        if (g_club && x >= (int)g_mx0 && x < (int)g_mx1) { club_click(h, x, y); return 0; }
        if (g_set && x >= (int)g_mx0 && x < (int)g_mx1) { set_click(h, x, y); return 0; }
        if (g_set && g_typing) {                         // a click outside ends the typing (a good address is kept)
            EnterCriticalSection(&g_board_cs);
            set_commit_locked();
            LeaveCriticalSection(&g_board_cs);
        }
        if (g_keys && x >= (int)g_mx0 && x < (int)g_mx1) { keys_click(h, x, y); return 0; }
        if (g_keys && (g_kcap >= 0 || g_kpadcap >= 0)) { // a click elsewhere ends the wait for a key (a side button's
            EnterCriticalSection(&g_board_cs);           // own key must not become the new key) or a control
            g_kcap = -1; g_kpadcap = -1;
            LeaveCriticalSection(&g_board_cs);
        }
        if (g_browse && x >= (int)g_mx0 && x < (int)g_mx1) { browse_click(h, x, y); return 0; }
        int b = button_at(x, y);
        if (b < 0) card = board_press(h, x, y);
        if (card) {
            logline("click at %d,%d (canvas %d,%d) -> card %d (picked up)", wx, wy, x, y, card);
            return 0;                            // a card: the game must not see this click either
        }
        logline("click at %d,%d (canvas %d,%d) -> %s", wx, wy, x, y, b >= 0 ? g_btn[b].label : "the game");
        if (b >= 0) {
            if (g_held_vk) send_key(g_held_vk, 1);
            g_held_vk = g_btn[b].vk; g_held_btn = b; g_mouse_down = 1; g_down_tick = GetTickCount();
            send_key(g_held_vk, 0);
            return 0;                            // swallow: the game must not also see this click
        }
    } else if (m == WM_MOUSEMOVE) {
        int x = (short)LOWORD(lp), y = (short)HIWORD(lp);
        to_canvas(h, &x, &y);
        if (g_sdrag >= 0) { slider_move(x); return 0; }      // a slider handle being dragged
        if (g_drag >= 0) { board_move(x, y); return 0; }
        board_hover(h, x, y);
        if (g_keys) keys_hover(x, y);            // the KEYS action under the mouse gets a frame
        if (g_browse) {                          // the browser's card under the mouse gets a frame
            struct Geo g;
            EnterCriticalSection(&g_board_cs);
            browse_geo(&g);
            g_bhover = (x >= (int)g_mx0 && x < (int)g_mx1) ? browse_hit_locked(&g, x, y) : -1;
            if (g_bhover >= 0) g_bdetail = g_res[g_bhover];      // the stats pane keeps the last card pointed at
            LeaveCriticalSection(&g_board_cs);
        }
    } else if (m == WM_LBUTTONUP) {
        if (g_sdrag >= 0) { slider_end(); ReleaseCapture(); return 0; }
        if (g_drag >= 0) { board_drop(); ReleaseCapture(); return 0; }
        if (g_mouse_down) { g_mouse_down = 0; return 0; }
    } else if (m == WM_RBUTTONDOWN || m == WM_RBUTTONUP) {
        static int took = 0;                     // the up of a right-click that took a card off is ours too
        int x = (short)LOWORD(lp), y = (short)HIWORD(lp), card;
        if (m == WM_RBUTTONUP) { if (took) { took = 0; return 0; } }
        else {
            to_canvas(h, &x, &y);
            if (g_keys && x >= (int)g_mx0 && x < (int)g_mx1) { keys_rclick(x, y); took = 1; return 0; }   // KEYS: clear
            card = board_remove(x, y);
            if (card) { took = 1; logline("right-click at canvas %d,%d -> card %d off the table", x, y, card); return 0; }
        }
    } else if (m == WM_CAPTURECHANGED) {
        if (g_sdrag >= 0 && (HWND)lp != h) slider_end();
        if (g_drag >= 0 && (HWND)lp != h) board_drop();      // the mouse was taken away mid-drag: the card stays put
    } else if (m == WM_MOUSELEAVE) {
        EnterCriticalSection(&g_board_cs); g_hover = -1; LeaveCriticalSection(&g_board_cs);
    }
    return CallWindowProcA(g_oldproc, h, m, wp, lp);
}

static BOOL CALLBACK find_win(HWND h, LPARAM lp)
{
    DWORD pid = 0; GetWindowThreadProcessId(h, &pid);
    if (pid == GetCurrentProcessId() && IsWindowVisible(h) && !GetWindow(h, GW_OWNER)) {
        RECT r; GetWindowRect(h, &r);
        long area = (long)(r.right - r.left) * (r.bottom - r.top);
        long *best = (long *)lp;
        if (area > best[1]) { best[0] = (long)h; best[1] = area; }
    }
    return TRUE;
}

static void hook_mouse(void)
{
    long best[2] = { 0, 0 };
    for (int tries = 0; tries < 120 && !best[0]; tries++) {      // injected early? wait up to 60 s for the window
        EnumWindows(find_win, (LPARAM)best);
        if (!best[0]) Sleep(500);
    }
    if (!best[0]) { logline("no game window found for mouse"); return; }
    g_hwnd = (HWND)best[0];
    g_oldproc = (WNDPROC)SetWindowLongPtrA(g_hwnd, GWLP_WNDPROC, (LONG_PTR)wndproc);
    logline("mouse hooked on window %p", (void *)g_hwnd);
}

// ---------------------------------------------------------------- a bad % no longer stops seat 1 (2026-10-05)
// Seat 1 stopped itself at the start of a match three times on 2026-10-05 (0xC0000417): the game's 2D text drawer
// FUN_0040e170 uses every text AS A FORMAT - vsprintf_s(buf, 0x401, text, ...) - and msvcr90's secure printf ends the
// program when a text holds a % that starts no valid code.  Which text it was is not known yet.  So the game's own
// import of MSVCR90.dll!vsprintf_s points here: the call goes to msvcr90 as before, but under a flag that our
// invalid-parameter handler honours - when msvcr90 refuses THIS call, the text is drawn as it is (no stop) and
// written to the log once.  msvcr90 itself judges every text, so nothing valid is ever changed.  Every other invalid
// parameter, from any thread, goes on to msvcr90's _invoke_watson exactly as before (the catcher still sees those).
typedef int  (__cdecl *VsprintfS)(char *, size_t, const char *, va_list);
typedef void (__cdecl *InvalidParamH)(const wchar_t *, const wchar_t *, const wchar_t *, unsigned int, uintptr_t);
typedef InvalidParamH (__cdecl *SetInvalidParamH)(InvalidParamH);
static VsprintfS     g_real_vsprintf_s = NULL;
static InvalidParamH g_invoke_watson = NULL;
static DWORD         g_fmt_tls = TLS_OUT_OF_INDEXES;     // per thread: 1 = inside our vsprintf_s, 2 = msvcr90 refused it
static int           g_fmt_guard_on = 0;                  // the guard's wrapper is in the vsprintf_s import slot
static unsigned int  g_badfmt_seen[64];                  // the refused texts already written to the log (hashes)
static volatile LONG g_badfmt_n = 0;

// ---------------------------------------------------------------- money with commas, step 1 (2026-10-06)
// the player: "lets all fix these" - the projector's "$10000000", "$3707200".  The game cuts each amount into a 100-million-
// yen part ($1,000,000) and a 10,000-yen part ($100) and formats them with its own templates
// (docs\research\MONEY-2010-11.md).  Step 1: the 27 places that format ONE whole amount in ONE call - roles FULL (the
// value, in $100), FULL2 (the two parts), FULLOKU (the 100-million part alone) of that doc's Appendix A, every place
// checked against both client copies there (site_table.py, 86 of 86) - now write "$2,299,000".  The split places (two
// calls, glued: step 2) are left exactly as they are.  A place is known by WHERE the game called from, never by text:
//   'S' = the game's FUN_006d7da0(fmt, ...) -> vsprintf_s (the fmt guard's wrapper, called from 0x006D7DD5): the
//         place is the return address *(ap - 8);   'P' = the game's own sprintf_s call: the place is our return address.
// Three places choose between two formats; the format POINTER tells which (alt_fmt: its address never moves).
// money_install() checks every place byte by byte, that the program sits at 0x00400000 and that English is on
// (0x00A62914 holds the kit's "$%d,000,000") - anything else: off, said in the log.  Only digits, commas, "$" and "-"
// are written (never a %), cut to the size the game gave; the numbers are the game's own ints, x100 in 64 bits.
#define MONEY_SETTEXT_RET 0x006D7DD5u            // FUN_006d7da0's call [vsprintf_s] returns here
#define MONEY_P429_RET    0x00429769u            // FUN_00429750's call [vsprintf_s] returns here ('Q' places)
// FULL/FULL2/FULLOKU: one call, the whole amount.  OKU/PASS/ZERO/MAN: the after-match total (D9), two boxes side by
// side - the 100-million box (OKU: the count; PASS: none, '') then, in the SAME call of FUN_00705330 and with no other
// text between them, the box beside it (ZERO: the rest is 0; MAN: the rest, or the whole value when PASS came first) -
// read off the machine code 2026-10-06 (research\money\dis_00705330.txt, both the count-up and the final block).  the player's
// screenshot that day: the second box ends at the same right edge as Match Prize above it.  So OKU leaves its box empty
// and remembers its count; ZERO/MAN write the whole amount ("Total Prize Money $3,761,200").
// The fan event's and the golden age's Prize Money (D2, D4; the player's picture 2026-10-07: "Prize Money: $5 million$431900",
// the second box ending at Income's right edge) are the same two boxes without a PASS: each of their six functions
// (start, count-up, final) sets the 100-million box only when there is a 100-million part, then at once the box beside
// it, with only string lookups between - read off the machine code 2026-10-07 (research\money\dis_fan_golden.txt; the
// golden age count-up passes its number too: Ghidra's C hides it, FUN_0042c350 takes its key in EAX).  A ZERO there
// with no count waiting means the whole amount is 0: the game's own text, blank in kit English, as after a match.
// The PIECES displays (D13-D17: CLUB TEAM DATA's Prize Money / Annual Salary - the player's picture the same evening - the
// coach room, coach data, old license card, match offer): an empty text; if the 100-million count > 0 its piece (OKU)
// is added; then either the literal "0000万" (no call - kit English blanks it, exe_text.tsv 0x627C04) or the rest's
// piece (MAN); then ONE call prints the joined text, "%s%s" with the yen word (FINAL) - read off the code of all six
// (research\money\dis_00576ca0.txt, dis_00577370.txt, dis_pieces.txt).  OKU's piece is left empty, MAN's carries the
// whole amount, FINAL prints that as it is - or, when the "0000万" came instead of MAN, the waiting count's amount.
enum { M_NONE, M_FULL, M_FULL2, M_FULLOKU, M_OKU, M_PASS, M_ZERO, M_MAN, M_FINAL };
struct MSite { DWORD ret; char kind; BYTE grp, role, alt_role; DWORD alt_fmt; const char *what; };
static const struct MSite MSITES[] = {           // Appendix A's places for step 1, D9 and the pieces, by address
    { 0x0045F188, 'S', 12, M_FULL2,   M_NONE,    0,          "D12 manager license salary" },
    { 0x0045F1CB, 'S', 12, M_FULL,    M_NONE,    0,          "D12 manager license salary" },
    { 0x00533634, 'S',  1, M_FULLOKU, M_NONE,    0,          "D1 fan event income" },
    { 0x005337AD, 'S',  2, M_OKU,     M_NONE,    0,          "D2 fan event Prize Money, start (100-million box)" },
    { 0x005337C5, 'S',  2, M_ZERO,    M_NONE,    0,          "D2 fan event Prize Money, start" },
    { 0x00533803, 'S',  2, M_MAN,     M_NONE,    0,          "D2 fan event Prize Money, start" },
    { 0x0053385B, 'P',  3, M_FULLOKU, M_NONE,    0,          "D3 fan event UP line" },
    { 0x00533B29, 'S',  2, M_OKU,     M_NONE,    0,          "D2 fan event Prize Money, counting up (100-million box)" },
    { 0x00533B41, 'S',  2, M_ZERO,    M_NONE,    0,          "D2 fan event Prize Money, counting up" },
    { 0x00533B89, 'S',  2, M_MAN,     M_NONE,    0,          "D2 fan event Prize Money, counting up" },
    { 0x00533C02, 'S',  2, M_OKU,     M_NONE,    0,          "D2 fan event Prize Money (100-million box)" },
    { 0x00533C19, 'S',  2, M_ZERO,    M_NONE,    0,          "D2 fan event Prize Money" },
    { 0x00533C6C, 'S',  2, M_MAN,     M_NONE,    0,          "D2 fan event Prize Money" },
    { 0x0053862D, 'S',  4, M_OKU,     M_NONE,    0,          "D4 golden age Prize Money, start (100-million box)" },
    { 0x00538645, 'S',  4, M_ZERO,    M_NONE,    0,          "D4 golden age Prize Money, start" },
    { 0x00538683, 'S',  4, M_MAN,     M_NONE,    0,          "D4 golden age Prize Money, start" },
    { 0x005386FB, 'P',  5, M_FULL2,   M_NONE,    0,          "D5 golden age UP line" },
    { 0x00538716, 'P',  5, M_FULLOKU, M_FULL,    0x00A27240, "D5 golden age UP line" },
    { 0x00538A7F, 'S',  4, M_OKU,     M_NONE,    0,          "D4 golden age Prize Money, counting up (100-million box)" },
    { 0x00538A93, 'S',  4, M_ZERO,    M_NONE,    0,          "D4 golden age Prize Money, counting up" },
    { 0x00538ABD, 'S',  4, M_MAN,     M_NONE,    0,          "D4 golden age Prize Money, counting up" },
    { 0x00538B92, 'S',  4, M_OKU,     M_NONE,    0,          "D4 golden age Prize Money (100-million box)" },
    { 0x00538BA9, 'S',  4, M_ZERO,    M_NONE,    0,          "D4 golden age Prize Money" },
    { 0x00538BFC, 'S',  4, M_MAN,     M_NONE,    0,          "D4 golden age Prize Money" },
    { 0x005432C0, 'Q', 15, M_OKU,     M_NONE,    0,          "D15 old license card salary (100-million piece)" },
    { 0x00543328, 'Q', 15, M_MAN,     M_NONE,    0,          "D15 old license card salary" },
    { 0x00543386, 'S', 15, M_FINAL,   M_NONE,    0,          "D15 old license card salary (joined)" },
    { 0x00550128, 'Q', 14, M_OKU,     M_NONE,    0,          "D14 coach data salary (100-million piece)" },
    { 0x0055018D, 'Q', 14, M_MAN,     M_NONE,    0,          "D14 coach data salary" },
    { 0x005501F8, 'S', 14, M_FINAL,   M_NONE,    0,          "D14 coach data salary (joined)" },
    { 0x00552C2F, 'S', 13, M_FULL,    M_NONE,    0,          "D13 coach room prize (zero)" },
    { 0x00552C4D, 'Q', 13, M_OKU,     M_NONE,    0,          "D13 coach room prize (100-million piece)" },
    { 0x00552CB5, 'Q', 13, M_MAN,     M_NONE,    0,          "D13 coach room prize" },
    { 0x00552D18, 'S', 13, M_FINAL,   M_NONE,    0,          "D13 coach room prize (joined)" },
    { 0x0055839D, 'Q', 16, M_OKU,     M_NONE,    0,          "D16 match offer seat prize (100-million piece)" },
    { 0x005583FE, 'Q', 16, M_MAN,     M_NONE,    0,          "D16 match offer seat prize" },
    { 0x00558465, 'S', 16, M_FINAL,   M_NONE,    0,          "D16 match offer seat prize (joined)" },
    { 0x00576F69, 'S', 171, M_FULL,   M_NONE,    0,          "D17 CLUB TEAM DATA Prize Money (zero)" },
    { 0x00576FF3, 'P', 171, M_OKU,    M_NONE,    0,          "D17 CLUB TEAM DATA Prize Money (100-million piece)" },
    { 0x0057705A, 'P', 171, M_MAN,    M_NONE,    0,          "D17 CLUB TEAM DATA Prize Money" },
    { 0x005770B8, 'S', 171, M_FINAL,  M_NONE,    0,          "D17 CLUB TEAM DATA Prize Money (joined)" },
    { 0x0057758C, 'S', 172, M_FULL,   M_NONE,    0,          "D17 CLUB TEAM DATA Annual Salary (zero)" },
    { 0x00577610, 'P', 172, M_OKU,    M_NONE,    0,          "D17 CLUB TEAM DATA Annual Salary (100-million piece)" },
    { 0x0057766E, 'P', 172, M_MAN,    M_NONE,    0,          "D17 CLUB TEAM DATA Annual Salary" },
    { 0x005776CE, 'S', 172, M_FINAL,  M_NONE,    0,          "D17 CLUB TEAM DATA Annual Salary (joined)" },
    { 0x0060345D, 'P', 18, M_FULL2,   M_NONE,    0,          "D18/D19 projector prize" },
    { 0x006034A0, 'P', 18, M_FULL,    M_NONE,    0,          "D18/D19 projector prize" },
    { 0x00661703, 'P', 19, M_FULL,    M_NONE,    0,          "D19 projector ranking prize" },
    { 0x0066172A, 'P', 19, M_FULL2,   M_NONE,    0,          "D19 projector ranking prize" },
    { 0x006F5049, 'S', 11, M_FULL,    M_NONE,    0,          "D11 contract end prize (zero)" },
    { 0x006F50FB, 'S', 11, M_FULLOKU, M_NONE,    0,          "D11 contract end previous salary" },
    { 0x006F515F, 'S', 11, M_FULL,    M_NONE,    0,          "D11 contract end previous salary (zero)" },
    { 0x006F51A9, 'S', 11, M_FULL2,   M_FULL,    0x00A2BDB4, "D11 contract end previous salary" },
    { 0x006F5E57, 'S', 11, M_FULL,    M_NONE,    0,          "D11 contract end last pay (zero)" },
    { 0x00705437, 'S',  9, M_OKU,     M_NONE,    0,          "D9 after-match total, counting up (100-million box)" },
    { 0x00705455, 'S',  9, M_PASS,    M_NONE,    0,          "D9 after-match total, counting up (100-million box)" },
    { 0x00705470, 'S',  9, M_ZERO,    M_NONE,    0,          "D9 after-match total, counting up" },
    { 0x007054AA, 'S',  9, M_MAN,     M_NONE,    0,          "D9 after-match total, counting up" },
    { 0x0070558C, 'S',  7, M_FULL2,   M_NONE,    0,          "D7 after-match Match Prize / Matches" },
    { 0x007055D4, 'S',  7, M_FULL,    M_FULLOKU, 0x00A62914, "D7 after-match Match Prize / Matches" },
    { 0x00705636, 'S',  8, M_FULL2,   M_NONE,    0,          "D8 after-match Club Income / Titles" },
    { 0x0070567D, 'S',  8, M_FULL,    M_FULLOKU, 0x00A62914, "D8 after-match Club Income / Titles" },
    { 0x00705702, 'S',  9, M_OKU,     M_NONE,    0,          "D9 after-match total (100-million box)" },
    { 0x00705722, 'S',  9, M_PASS,    M_NONE,    0,          "D9 after-match total (100-million box)" },
    { 0x0070573D, 'S',  9, M_ZERO,    M_NONE,    0,          "D9 after-match total / Annual Salary" },
    { 0x0070577F, 'S',  9, M_MAN,     M_NONE,    0,          "D9 after-match total / Annual Salary" },
    { 0x007079D5, 'S', 10, M_FULL2,   M_NONE,    0,          "D10 kick-off box, home" },
    { 0x007079E9, 'S', 10, M_FULL,    M_FULLOKU, 0x00A62914, "D10 kick-off box, home" },
    { 0x00707C24, 'S', 10, M_FULLOKU, M_NONE,    0,          "D10 kick-off box, away" },
    { 0x00707CA1, 'S', 10, M_FULL2,   M_NONE,    0,          "D10 kick-off box, away" },
    { 0x00707CB5, 'S', 10, M_FULL,    M_NONE,    0,          "D10 kick-off box, away" },
};
#define NMSITES ((int)(sizeof MSITES / sizeof MSITES[0]))
static volatile LONG g_msite_said[NMSITES];      // each place says its first amount in the log, once
static int g_money_on = 0;
static struct { DWORD tid; int grp, oku; } g_mpend;   // an OKU's count waiting for its ZERO/MAN (tid 0 = none)

// v in $100 (the game's 10,000-yen unit) -> "$2,299,000", "-$15,000", "$0", cut to the box; the length, -1 = no box
static int money_text(char *buf, size_t size, LONGLONG v)
{
    char rev[40], out[48]; int m = 0, n = 0, digits = 0, neg = v < 0;
    ULONGLONG d = (ULONGLONG)(neg ? -v : v) * 100ULL;
    if (!buf || size == 0) return -1;
    do {
        if (digits && digits % 3 == 0) rev[m++] = ',';
        rev[m++] = (char)('0' + (int)(d % 10)); d /= 10; digits++;
    } while (d && m < (int)sizeof rev - 2);
    if (neg) out[n++] = '-';
    out[n++] = '$';
    while (m) out[n++] = rev[--m];
    out[n] = 0;
    if ((size_t)n >= size) n = (int)size - 1;
    memcpy(buf, out, (size_t)n);
    buf[n] = 0;
    return n;
}

static LONGLONG money_value(BYTE role, const int *a)     // the amount in $100, from the game's own arguments
{
    if (role == M_FULL) return a[0];
    if (role == M_FULLOKU) return (LONGLONG)a[0] * 10000;
    if (a[0] < 0) return (LONGLONG)a[0] * 10000 - (a[1] < 0 ? -(LONGLONG)a[1] : (LONGLONG)a[1]);   // -(|o| x 10000 + w)
    return (LONGLONG)a[0] * 10000 + a[1];                                                         // FULL2
}

// a place the table knows -> the amount written there (its length); -2 = not ours: the game's own text goes on
static int money_place(DWORD ret, char kind, char *buf, size_t size, const char *fmt, va_list ap)
{
    int i, r, oku = 0, waiting; BYTE role; LONGLONG v; DWORD tid = GetCurrentThreadId(); const int *a = (const int *)ap;
    for (i = 0; i < NMSITES && (MSITES[i].ret != ret || MSITES[i].kind != kind); i++) {}
    if (i == NMSITES) return -2;
    role = (MSITES[i].alt_fmt && (DWORD)(UINT_PTR)fmt == MSITES[i].alt_fmt) ? MSITES[i].alt_role : MSITES[i].role;
    waiting = g_mpend.tid == tid && g_mpend.grp == MSITES[i].grp;
    if (waiting) oku = g_mpend.oku;
    if (g_mpend.tid == tid) g_mpend.tid = 0;     // every place of ours on this thread uses up what was waiting
    if (role == M_OKU) {                         // the 100-million box: empty, its count waits for the box beside it
        if (!buf || size == 0) return -2;
        g_mpend.oku = a[0]; g_mpend.grp = MSITES[i].grp; g_mpend.tid = tid;
        buf[0] = 0;
        r = 0;
    } else if (role == M_PASS) {
        return -2;                               // no 100-million part: the game's own empty text
    } else if (role == M_FINAL && !waiting) {
        return -2;                               // the pieces carry the whole amount already: the game joins them
    } else if (role == M_FINAL) {                // "0000万" came instead of a MAN piece: the waiting count's amount
        r = money_text(buf, size, (LONGLONG)oku * 10000);
        if (r < 0) return -2;
    } else {
        if (role == M_ZERO && !waiting) return -2;               // never seen: the game's own text
        if (role == M_ZERO) v = (LONGLONG)oku * 10000;
        else if (role == M_MAN && waiting)                       // the rest comes as |rest| after a 100-million part
            v = (LONGLONG)oku * 10000 + (oku < 0 ? -(LONGLONG)abs(a[0]) : (LONGLONG)abs(a[0]));
        else if (role == M_MAN) v = a[0];                        // after PASS: the whole value, signed
        else v = money_value(role, a);
        r = money_text(buf, size, v);
        if (r < 0) return -2;
    }
    if (!InterlockedExchange(&g_msite_said[i], 1))
        logline("money: %s (place 0x%08lX%s) -> \"%s\"", MSITES[i].what, (unsigned long)ret,
                role != MSITES[i].role ? ", its other format" : role == M_MAN && waiting ? ", with its 100-million part" : "",
                buf);
    return r;
}

static void __cdecl fmt_handler(const wchar_t *e, const wchar_t *f, const wchar_t *file, unsigned int line, uintptr_t r)
{
    DWORD err = GetLastError();
    if (g_fmt_tls != TLS_OUT_OF_INDEXES && TlsGetValue(g_fmt_tls) == (LPVOID)1) {
        TlsSetValue(g_fmt_tls, (LPVOID)2);
        SetLastError(err);
        return;                                          // vsprintf_s now returns -1 to our wrapper
    }
    SetLastError(err);
    g_invoke_watson(e, f, file, line, r);                // anything else: the stop, exactly as before
}

static int __cdecl safe_vsprintf_s(char *buf, size_t size, const char *fmt, va_list ap)
{
    DWORD err = GetLastError(); int r; LPVOID was;
    if (g_money_on && _ReturnAddress() == (void *)(UINT_PTR)MONEY_SETTEXT_RET) {   // a box text: one of ours?
        r = money_place(*(DWORD *)((char *)ap - 8), 'S', buf, size, fmt, ap);
        SetLastError(err);
        if (r >= 0) return r;
    } else if (g_money_on && _ReturnAddress() == (void *)(UINT_PTR)MONEY_P429_RET) {   // a piece: one of ours?
        r = money_place(*(DWORD *)((char *)ap - 0xC), 'Q', buf, size, fmt, ap);
        SetLastError(err);
        if (r >= 0) return r;
    }
    TlsSetValue(g_fmt_tls, (LPVOID)1);
    SetLastError(err);
    r = g_real_vsprintf_s(buf, size, fmt, ap);
    err = GetLastError();
    was = TlsGetValue(g_fmt_tls);
    TlsSetValue(g_fmt_tls, (LPVOID)0);
    SetLastError(err);
    if (was == (LPVOID)2 && buf && size > 0) {           // refused: the text as it is, cut to the box
        size_t n = 0; unsigned int h = 2166136261u; LONG k; int seen = 0;
        if (fmt) for (; fmt[n] && n < size - 1; n++) buf[n] = fmt[n];
        buf[n] = 0;
        r = (int)n;
        for (const unsigned char *p = (const unsigned char *)(fmt ? fmt : ""); *p; p++) h = (h ^ *p) * 16777619u;
        for (k = 0; k < g_badfmt_n && k < 64; k++) if (g_badfmt_seen[k] == h) seen = 1;
        if (!seen && g_badfmt_n < 64) {
            char esc[400]; int m = 0;
            k = InterlockedIncrement(&g_badfmt_n) - 1;
            if (k < 64) g_badfmt_seen[k] = h;
            for (const unsigned char *p = (const unsigned char *)(fmt ? fmt : ""); *p && m < (int)sizeof esc - 6; p++)
                m += (*p >= 32 && *p < 127 && *p != '\\') ? (esc[m] = (char)*p, 1) : _snprintf(esc + m, 5, "\\x%02x", *p);
            esc[m] = 0;
            logline("badfmt: msvcr90 refused this text as a format - drawn as it is instead of stopping seat 1: \"%s\"", esc);
        }
    }
    return r;
}

// the import slot of dll!fn in module mod (by name, from the import table), or NULL
static void **iat_slot(HMODULE mod, const char *dll, const char *fn)
{
    BYTE *b = (BYTE *)mod;
    IMAGE_NT_HEADERS32 *nt = (IMAGE_NT_HEADERS32 *)(b + ((IMAGE_DOS_HEADER *)b)->e_lfanew);
    IMAGE_DATA_DIRECTORY dd = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
    IMAGE_IMPORT_DESCRIPTOR *d;
    if (!dd.VirtualAddress) return NULL;
    for (d = (IMAGE_IMPORT_DESCRIPTOR *)(b + dd.VirtualAddress); d->Name; d++) {
        IMAGE_THUNK_DATA32 *names, *slots;
        if (_stricmp((const char *)(b + d->Name), dll) != 0 || !d->OriginalFirstThunk) continue;
        names = (IMAGE_THUNK_DATA32 *)(b + d->OriginalFirstThunk);
        slots = (IMAGE_THUNK_DATA32 *)(b + d->FirstThunk);
        for (; names->u1.AddressOfData; names++, slots++) {
            if (IMAGE_SNAP_BY_ORDINAL32(names->u1.Ordinal)) continue;
            if (strcmp((const char *)((IMAGE_IMPORT_BY_NAME *)(b + names->u1.AddressOfData))->Name, fn) == 0)
                return (void **)&slots->u1.Function;
        }
    }
    return NULL;
}

static void fmt_guard_install(void)
{
    HMODULE crt = GetModuleHandleA("msvcr90.dll");
    SetInvalidParamH set = crt ? (SetInvalidParamH)GetProcAddress(crt, "_set_invalid_parameter_handler") : NULL;
    void *real = crt ? (void *)GetProcAddress(crt, "vsprintf_s") : NULL;
    void **slot = crt ? iat_slot(GetModuleHandleA(NULL), "msvcr90.dll", "vsprintf_s") : NULL;
    InvalidParamH prev; DWORD old;
    g_invoke_watson = crt ? (InvalidParamH)GetProcAddress(crt, "_invoke_watson") : NULL;
    if (!crt || !set || !real || !g_invoke_watson || !slot) {
        logline("fmt guard: not installed (msvcr90 %p, handler setter %p, vsprintf_s %p, _invoke_watson %p, the program's import slot %p)",
                (void *)crt, (void *)set, real, (void *)g_invoke_watson, (void *)slot);
        return;
    }
    if (*slot != real) { logline("fmt guard: the import slot does not hold msvcr90's vsprintf_s - left alone"); return; }
    g_fmt_tls = TlsAlloc();
    if (g_fmt_tls == TLS_OUT_OF_INDEXES) { logline("fmt guard: no TLS slot - not installed"); return; }
    g_real_vsprintf_s = (VsprintfS)real;
    prev = set(fmt_handler);
    if (prev) {                                          // the game has its own handler: do not stand in its way
        set(prev);
        logline("fmt guard: the program already has an invalid-parameter handler - not installed");
        return;
    }
    if (!VirtualProtect(slot, sizeof *slot, PAGE_READWRITE, &old)) {
        set(NULL);
        logline("fmt guard: the import slot could not be opened (error %lu) - not installed", GetLastError());
        return;
    }
    *slot = (void *)safe_vsprintf_s;
    VirtualProtect(slot, sizeof *slot, old, &old);
    g_fmt_guard_on = 1;
    logline("fmt guard: vsprintf_s (import slot %p) checked - a text msvcr90 refuses is drawn as it is and logged", (void *)slot);
}

// money step 1: the game's own sprintf_s import points here.  One of the table's 'P' places -> the amount with commas;
// anything else -> formatted exactly as before (msvcr90's vsprintf_s - through the fmt guard in seat 1, so a bad % in
// a sprintf_s text no longer stops it either)
static VsprintfS g_msvcr_vsprintf_s = NULL;

static int __cdecl money_sprintf_s(char *buf, size_t size, const char *fmt, ...)
{
    va_list ap; int r = -2; DWORD err = GetLastError();
    va_start(ap, fmt);
    if (g_money_on) r = money_place((DWORD)(UINT_PTR)_ReturnAddress(), 'P', buf, size, fmt, ap);
    SetLastError(err);
    if (r < 0) r = g_fmt_guard_on ? safe_vsprintf_s(buf, size, fmt, ap) : g_msvcr_vsprintf_s(buf, size, fmt, ap);
    va_end(ap);
    return r;
}

// WCCFPANEL_MONEYTEST=1 (the tests): every role through money_place itself, with the game's arguments faked;
// "money test: PASS|FAIL ..." lines and a total in the log.  What it changed is put back afterwards.
static int g_mt_n = 0, g_mt_fail = 0;

static void mt_check(const char *name, const char *got, const char *want)
{
    int ok = strcmp(got, want) == 0;
    g_mt_n++; g_mt_fail += !ok;
    logline("money test: %s  %s -> \"%s\"%s%s%s", ok ? "PASS" : "FAIL", name, got,
            ok ? "" : "  (wanted \"", ok ? "" : want, ok ? "" : "\")");
}

static void mt_place(const char *name, DWORD ret, char kind, int a0, int a1, const char *fmt, const char *want)
{
    int args[2]; char b[48];
    args[0] = a0; args[1] = a1;
    if (money_place(ret, kind, b, sizeof b, fmt, (va_list)args) == -2) strcpy(b, "(the game's own)");
    mt_check(name, b, want);
}

static DWORD WINAPI mt_other_thread(LPVOID arg)          // an OKU on another thread: must never reach this one's MAN
{
    (void)arg;
    mt_place("another thread: OKU 5", 0x00705702, 'S', 5, 0, "x", "");
    return 0;
}

static void money_selftest(void)
{
    static const struct { LONGLONG v; const char *want; } T[] = {
        { 0, "$0" }, { 1, "$100" }, { 99, "$9,900" }, { 150, "$15,000" }, { 2299, "$229,900" }, { 10000, "$1,000,000" },
        { 22990, "$2,299,000" }, { 37072, "$3,707,200" }, { 100000, "$10,000,000" }, { -150, "-$15,000" },
        { -22990, "-$2,299,000" }, { 2147483647LL, "$214,748,364,700" }, { -2147483647LL - 1, "-$214,748,364,800" } };
    static const struct { int o, w; const char *want; } F2[] = {
        { 2, 2990, "$2,299,000" }, { 10, 0, "$10,000,000" }, { 0, 7500, "$750,000" }, { -2, 2990, "-$2,299,000" },
        { 3, 7072, "$3,707,200" } };
    const char *ENGFMT = (const char *)(UINT_PTR)0x00A62914;     // compared as a pointer, never read
    char b[48], name[64]; int i, a[2]; HANDLE th;
    for (i = 0; i < (int)(sizeof T / sizeof T[0]); i++) {
        money_text(b, sizeof b, T[i].v);
        _snprintf(name, sizeof name, "money(%I64d)", T[i].v); name[sizeof name - 1] = 0;
        mt_check(name, b, T[i].want);
    }
    for (i = 0; i < (int)(sizeof F2 / sizeof F2[0]); i++) {
        a[0] = F2[i].o; a[1] = F2[i].w;
        money_text(b, sizeof b, money_value(M_FULL2, a));
        _snprintf(name, sizeof name, "FULL2 %d, %d", F2[i].o, F2[i].w); name[sizeof name - 1] = 0;
        mt_check(name, b, F2[i].want);
    }
    a[0] = 10; money_text(b, sizeof b, money_value(M_FULLOKU, a)); mt_check("FULLOKU 10", b, "$10,000,000");
    money_text(b, 6, 22990);                                     mt_check("22990 in a 6-byte box", b, "$2,29");
    money_text(b, 1, 22990);                                     mt_check("22990 in a 1-byte box", b, "");
    mt_check("no box at all", money_text(NULL, 0, 5) == -1 ? "-1" : "?", "-1");
    // D9, as FUN_00705330 calls it: the 100-million box, then the box beside it
    mt_place("D9 OKU 3", 0x00705702, 'S', 3, 0, "x", "");
    mt_place("D9 then MAN 7612", 0x0070577F, 'S', 7612, 0, "x", "$3,761,200");
    mt_place("D9 PASS", 0x00705722, 'S', 0, 0, "", "(the game's own)");
    mt_place("D9 then MAN 2309 (Annual Salary)", 0x0070577F, 'S', 2309, 0, "x", "$230,900");
    mt_place("D9 count-up OKU 1", 0x00705437, 'S', 1, 0, "x", "");
    mt_place("D9 then ZERO", 0x00705470, 'S', 0, 0, "", "$1,000,000");
    mt_place("D9 OKU -1", 0x00705702, 'S', -1, 0, "x", "");
    mt_place("D9 then MAN 5000 (|rest|)", 0x0070577F, 'S', 5000, 0, "x", "-$1,500,000");
    mt_place("D9 count-up MAN 0, nothing waiting", 0x007054AA, 'S', 0, 0, "x", "$0");
    mt_place("D9 ZERO, nothing waiting", 0x0070573D, 'S', 0, 0, "", "(the game's own)");
    mt_place("D9 OKU 2", 0x00705702, 'S', 2, 0, "x", "");
    mt_place("then D7 Matches 133 (uses the wait up)", 0x007055D4, 'S', 133, 0, "x", "$13,300");
    mt_place("then D9 MAN 99: not 2 million more", 0x0070577F, 'S', 99, 0, "x", "$9,900");
    th = CreateThread(NULL, 0, mt_other_thread, NULL, 0, NULL);
    if (th) { WaitForSingleObject(th, 5000); CloseHandle(th); }
    mt_place("D9 MAN 99 here, after the other thread's OKU", 0x0070577F, 'S', 99, 0, "x", "$9,900");
    // D2 / D4, as their start / count-up / final functions call them: [the 100-million box], then the box beside it
    mt_place("D2 fan event final: OKU 5", 0x00533C02, 'S', 5, 0, "x", "");
    mt_place("then MAN 4319 (the fan event screenshot)", 0x00533C6C, 'S', 4319, 0, "x", "$5,431,900");
    mt_place("D2 counting up: OKU 2", 0x00533B29, 'S', 2, 0, "x", "");
    mt_place("then ZERO", 0x00533B41, 'S', 0, 0, "", "$2,000,000");
    mt_place("D2 start: MAN 9500, no 100-million part", 0x00533803, 'S', 9500, 0, "x", "$950,000");
    mt_place("D4 golden age counting up: OKU 1", 0x00538A7F, 'S', 1, 0, "x", "");
    mt_place("then MAN 2990", 0x00538ABD, 'S', 2990, 0, "x", "$1,299,000");
    mt_place("D4 start: OKU 3", 0x0053862D, 'S', 3, 0, "x", "");
    mt_place("then ZERO", 0x00538645, 'S', 0, 0, "", "$3,000,000");
    mt_place("D2 start: OKU 3", 0x005337AD, 'S', 3, 0, "x", "");
    mt_place("then D4 final MAN 100: not D2's 3 million", 0x00538BFC, 'S', 100, 0, "x", "$10,000");
    mt_place("D4 final ZERO, nothing waiting (a total of 0)", 0x00538BA9, 'S', 0, 0, "", "(the game's own)");
    // the pieces displays, as FUN_00576ca0 and the others call them: [the 100-million piece], then the rest's piece or
    // the literal "0000万" (no call), then the join
    mt_place("D17 Prize Money: OKU 3", 0x00576FF3, 'P', 3, 0, "x", "");
    mt_place("then MAN 8174", 0x0057705A, 'P', 8174, 0, "x", "$3,817,400");
    mt_place("then the join", 0x005770B8, 'S', 0, 0, "%s%s", "(the game's own)");
    mt_place("D17 Prize Money: OKU 3 again", 0x00576FF3, 'P', 3, 0, "x", "");
    mt_place("then the join with \"0000\" instead of MAN", 0x005770B8, 'S', 0, 0, "%s%s", "$3,000,000");
    mt_place("D17 Annual Salary: MAN 2309, no OKU", 0x0057766E, 'P', 2309, 0, "x", "$230,900");
    mt_place("then its join", 0x005776CE, 'S', 0, 0, "%s%s", "(the game's own)");
    mt_place("D13 coach room: OKU 1 (FUN_00429750)", 0x00552C4D, 'Q', 1, 0, "x", "");
    mt_place("then MAN 2500", 0x00552CB5, 'Q', 2500, 0, "x", "$1,250,000");
    mt_place("then its join", 0x00552D18, 'S', 0, 0, "%s%s", "(the game's own)");
    mt_place("D16 match offer: MAN 0, no OKU", 0x005583FE, 'Q', 0, 0, "x", "$0");
    mt_place("D17 Prize Money: OKU 3, once more", 0x00576FF3, 'P', 3, 0, "x", "");
    mt_place("then Annual Salary's join: another display", 0x005776CE, 'S', 0, 0, "%s%s", "(the game's own)");
    mt_place("then Prize Money's join: the wait was used up", 0x005770B8, 'S', 0, 0, "%s%s", "(the game's own)");
    mt_place("a piece place reached through sprintf_s", 0x00552C4D, 'P', 1, 0, "x", "(the game's own)");
    // the one-call places
    mt_place("D7 Match Prize FULL2 2, 2990", 0x0070558C, 'S', 2, 2990, "x", "$2,299,000");
    mt_place("D8 Titles FULL 0", 0x0070567D, 'S', 0, 0, "x", "$0");
    mt_place("D8 Club Income, its other format: FULLOKU 2", 0x0070567D, 'S', 2, 0, ENGFMT, "$2,000,000");
    mt_place("D10 kick-off home FULL2 3, 7072", 0x007079D5, 'S', 3, 7072, "x", "$3,707,200");
    mt_place("D10 kick-off away FULL 7500", 0x00707CB5, 'S', 7500, 0, "x", "$750,000");
    mt_place("D5 its other format: FULL 150", 0x00538716, 'P', 150, 0, (const char *)(UINT_PTR)0x00A27240, "$15,000");
    mt_place("projector prize FULL2 10, 0", 0x0060345D, 'P', 10, 0, "x", "$10,000,000");
    mt_place("projector prize FULL 7500", 0x006034A0, 'P', 7500, 0, "x", "$750,000");
    mt_place("a projector place reached as a box text", 0x0060345D, 'S', 10, 0, "x", "(the game's own)");
    mt_place("a box place reached through sprintf_s", 0x0070558C, 'P', 2, 2990, "x", "(the game's own)");
    mt_place("a place not in the table", 0x00401000, 'S', 1, 2, "x", "(the game's own)");
    logline("money test: %d checks, %d failed", g_mt_n, g_mt_fail);
    memset((void *)g_msite_said, 0, sizeof g_msite_said);       // the real run says its first amounts again
    g_mpend.tid = 0;
}

// ---------------------------------------------------------------- the match relay (2026-10-06)
// A match between two players: the cabinets send their moves to each other directly, over UDP to port 20000 + the
// other's seat - read off the code: FUN_00453640 sends and FUN_00453520 receives on ONE socket (their object's
// +0x8c), through sendto (FUN_00458090) and recvfrom (FUN_00458150, which keeps the sender's address for the
// handler FUN_00453750).  Home routers drop that traffic, and the game falls back to a CPU match ("Network
// disconnected. Switching to CPU match.") - seen 2026-10-06 between the player and a friend on the Azure server.  When
// play.py starts this cabinet on a server it sets WCCF_RELAY=ADDRESS:20040 and WCCF_SEAT=n, and the game's own
// sendto / recvfrom imports come here: a packet for another player (a public address, port 20001-20008) goes to the
// server's relay (_relay.py) labelled with both seats; what the relay passes on arrives on the same socket and is
// handed to the game as if straight from that player - from the very address the game itself sends to it (else the
// address the relay saw, port 20000 + its seat).  Every 5 s each socket that played tells the relay "I am seat n",
// which also keeps the router open for the replies.  Everything else - 127.x (the CPU match's own local channel),
// the server's TCP, other ports - passes untouched.  Off: no WCCF_RELAY, or the import slots are not the ones read.
#define RELAY_MAGIC   "WRL1"
#define SLOT_SENDTO   0x0097E8FCu                // WS2_32 #20 sendto   (pe.py / imports.py seat1)
#define SLOT_RECVFROM 0x0097E8F8u                // WS2_32 #17 recvfrom
typedef int (WSAAPI *SendtoFn)(SOCKET, const char *, int, int, const struct sockaddr *, int);
typedef int (WSAAPI *RecvfromFn)(SOCKET, char *, int, int, struct sockaddr *, int *);
static SendtoFn           g_real_sendto = NULL;
static RecvfromFn         g_real_recvfrom = NULL;
static struct sockaddr_in g_relay;               // the server's relay
static int                g_relay_on = 0, g_my_seat = 0, g_relay_test = 0;
static struct sockaddr_in g_peer[9];             // per seat: the address the game itself sends to (its source, back)
static SOCKET             g_rsock[8];            // the sockets that played: "I am seat n" every 5 s
static volatile LONG      g_rsock_n = 0, g_rl_out = 0, g_rl_in = 0, g_rl_said_out = 0, g_rl_said_in = 0;

static int relay_peer(const struct sockaddr *to, int tolen, int *seat)   // a packet for another player's cabinet?
{
    const struct sockaddr_in *a = (const struct sockaddr_in *)to;
    unsigned long ip; unsigned port;
    if (!to || tolen < (int)sizeof(struct sockaddr_in) || a->sin_family != AF_INET) return 0;
    port = ntohs(a->sin_port);
    ip = ntohl(a->sin_addr.s_addr);
    if (port < 20001 || port > 20008 || ip == 0 || ip == 0xFFFFFFFFu) return 0;
    if ((ip >> 24) == 127 && !(g_relay_test && ip == 0x7F000002u)) return 0;   // 127.x: this PC's own channels
    *seat = (int)port - 20000;
    return 1;
}

static void relay_hello(SOCKET s)                 // "I am seat n" from this socket
{
    char p[6];
    memcpy(p, RELAY_MAGIC, 4); p[4] = 'R'; p[5] = (char)g_my_seat;
    g_real_sendto(s, p, 6, 0, (const struct sockaddr *)&g_relay, sizeof g_relay);
}

static void relay_keep(SOCKET s)                  // the game's thread: a socket that sends to another player
{
    LONG i, n = g_rsock_n;
    for (i = 0; i < n; i++) if (g_rsock[i] == s) return;
    if (n < 8) { g_rsock[n] = s; InterlockedIncrement(&g_rsock_n); }
    relay_hello(s);
}

static int WSAAPI relay_sendto(SOCKET s, const char *buf, int len, int flags, const struct sockaddr *to, int tolen)
{
    char pkt[4200]; int seat, r;
    if (!g_relay_on || len < 0 || len > 4096 || !relay_peer(to, tolen, &seat))
        return g_real_sendto(s, buf, len, flags, to, tolen);
    g_peer[seat] = *(const struct sockaddr_in *)to;
    relay_keep(s);
    memcpy(pkt, RELAY_MAGIC, 4); pkt[4] = 'D'; pkt[5] = (char)seat; pkt[6] = (char)g_my_seat;
    memcpy(pkt + 7, buf, len);
    r = g_real_sendto(s, pkt, len + 7, flags, (const struct sockaddr *)&g_relay, sizeof g_relay);
    if (r == SOCKET_ERROR) return r;
    InterlockedIncrement(&g_rl_out);
    if (!InterlockedExchange(&g_rl_said_out, 1))
        logline("relay: the first packet for seat %d's cabinet goes through the server's relay", seat);
    return len;
}

static int WSAAPI relay_recvfrom(SOCKET s, char *buf, int len, int flags, struct sockaddr *from, int *fromlen)
{
    char tmp[4200]; struct sockaddr_in src; int sl, r, n, seat;
    if (!g_relay_on || (flags & MSG_PEEK)) return g_real_recvfrom(s, buf, len, flags, from, fromlen);
    for (;;) {
        sl = sizeof src;
        r = g_real_recvfrom(s, tmp, sizeof tmp, flags, (struct sockaddr *)&src, &sl);
        if (r == SOCKET_ERROR) return r;
        if (src.sin_family == AF_INET && src.sin_addr.s_addr == g_relay.sin_addr.s_addr && src.sin_port == g_relay.sin_port) {
            if (r < 10 || memcmp(tmp, RELAY_MAGIC, 4) || tmp[4] != 'F' || (seat = (unsigned char)tmp[5]) < 1 || seat > 8)
                continue;                        // the relay's, not the game's: read the next one
            n = r - 10;
            if (n > len) n = len;
            memcpy(buf, tmp + 10, n);
            if (from && fromlen && *fromlen >= (int)sizeof(struct sockaddr_in)) {
                struct sockaddr_in f;
                if (g_peer[seat].sin_family == AF_INET) f = g_peer[seat];
                else {
                    memset(&f, 0, sizeof f);
                    f.sin_family = AF_INET;
                    memcpy(&f.sin_addr, tmp + 6, 4);
                    f.sin_port = htons((u_short)(20000 + seat));
                }
                memcpy(from, &f, sizeof f);
                *fromlen = sizeof f;
            }
            InterlockedIncrement(&g_rl_in);
            if (!InterlockedExchange(&g_rl_said_in, 1))
                logline("relay: the first packet from seat %d's cabinet came through the server's relay", seat);
            return n;
        }
        if (r > len) {                           // what the game's own recvfrom would have said: too big, cut
            memcpy(buf, tmp, len);
            WSASetLastError(WSAEMSGSIZE);
            return SOCKET_ERROR;
        }
        memcpy(buf, tmp, r);
        if (from && fromlen) {
            memcpy(from, &src, (size_t)(*fromlen < sl ? *fromlen : sl));
            *fromlen = sl;
        }
        return r;
    }
}

static DWORD WINAPI relay_watch(LPVOID arg)       // every 5 s "I am seat n" from each socket that played; counts
{
    DWORD next = GetTickCount() + 60000; LONG o0 = 0, i0 = 0;
    (void)arg;
    for (;;) {
        LONG i, n = g_rsock_n;
        Sleep(5000);
        for (i = 0; i < n; i++) relay_hello(g_rsock[i]);
        if ((LONG)(GetTickCount() - next) >= 0) {
            LONG o = g_rl_out, in = g_rl_in;
            if (o != o0 || in != i0) logline("relay: last minute %ld packets out, %ld in, through the server", o - o0, in - i0);
            o0 = o; i0 = in; next = GetTickCount() + 60000;
        }
    }
}

static void relay_install(void)                   // seat 1's cabinet on a server: play.py set WCCF_RELAY and WCCF_SEAT
{
    char v[64], sn[8], *colon, exe[MAX_PATH], *nm; HMODULE ws; DWORD old; unsigned long ip; int port;
    if (GetEnvironmentVariableA("WCCF_RELAY", v, sizeof v) == 0) return;                // this PC alone: no relay
    if (GetEnvironmentVariableA("WCCF_SEAT", sn, sizeof sn) == 0 || atoi(sn) < 1 || atoi(sn) > 8) {
        logline("relay: off - no seat (WCCF_SEAT)");
        return;
    }
    colon = strchr(v, ':');
    if (!colon) { logline("relay: off - WCCF_RELAY is not ADDRESS:PORT (%s)", v); return; }
    *colon = 0;
    ip = inet_addr(v); port = atoi(colon + 1);
    if (ip == INADDR_NONE || port < 1 || port > 65535) { logline("relay: off - not an address: %s:%s", v, colon + 1); return; }
    GetModuleFileNameA(NULL, exe, MAX_PATH);
    nm = strrchr(exe, '\\'); nm = nm ? nm + 1 : exe;
    ws = GetModuleHandleA("ws2_32.dll");
    if (_stricmp(nm, "client_Release.exe") != 0 || GetModuleHandleA(NULL) != (HMODULE)(UINT_PTR)0x00400000 || !ws) {
        logline("relay: off - not the game (%s)", nm);
        return;
    }
    g_real_sendto = (SendtoFn)GetProcAddress(ws, "sendto");
    g_real_recvfrom = (RecvfromFn)GetProcAddress(ws, "recvfrom");
    if (!g_real_sendto || !g_real_recvfrom || *(void **)(UINT_PTR)SLOT_SENDTO != (void *)g_real_sendto ||
        *(void **)(UINT_PTR)SLOT_RECVFROM != (void *)g_real_recvfrom) {
        logline("relay: off - the game's sendto / recvfrom imports are not the ones read");
        return;
    }
    memset(&g_relay, 0, sizeof g_relay);
    g_relay.sin_family = AF_INET;
    g_relay.sin_addr.s_addr = ip;
    g_relay.sin_port = htons((u_short)port);
    g_my_seat = atoi(sn);
    if (!VirtualProtect((void *)(UINT_PTR)SLOT_RECVFROM, 8, PAGE_READWRITE, &old)) {
        logline("relay: off - the import slots could not be opened (error %lu)", GetLastError());
        return;
    }
    g_relay_on = 1;                              // before the slots change: the hooks must find it on
    *(void **)(UINT_PTR)SLOT_SENDTO = (void *)relay_sendto;
    *(void **)(UINT_PTR)SLOT_RECVFROM = (void *)relay_recvfrom;
    VirtualProtect((void *)(UINT_PTR)SLOT_RECVFROM, 8, old, &old);
    CreateThread(NULL, 0, relay_watch, NULL, 0, NULL);
    logline("relay: on - seat %d; a match against another player goes through %s:%d", g_my_seat, v, port);
}

// WCCFPANEL_RELAYTEST=1 (the tests): two sockets on this PC play seats 1 and 2 through a relay on 127.0.0.1:20941
// (the test starts _relay.py there); 127.0.0.2 stands for "another player's address"
static void rt_check(const char *name, int ok, const char *detail)
{
    logline("relay test: %s  %s%s%s", ok ? "PASS" : "FAIL", name, detail && *detail ? "  - " : "", detail ? detail : "");
}

static int rt_recv(SOCKET s, char *buf, int len, struct sockaddr_in *from)   // up to 2 s for a datagram
{
    int i, r, fl;
    for (i = 0; i < 200; i++) {
        fl = sizeof *from;
        r = relay_recvfrom(s, buf, len, 0, (struct sockaddr *)from, &fl);
        if (r != SOCKET_ERROR) return r;
        if (WSAGetLastError() != WSAEWOULDBLOCK) return -1;
        Sleep(10);
    }
    return -2;
}

static void relay_selftest(void)
{
    WSADATA wd; SOCKET a, b; struct sockaddr_in la, lb, to, from; int ln, r; u_long nb = 1; char buf[256], d[96];
    HMODULE ws;
    WSAStartup(MAKEWORD(2, 2), &wd);
    ws = GetModuleHandleA("ws2_32.dll");
    g_real_sendto = (SendtoFn)GetProcAddress(ws, "sendto");
    g_real_recvfrom = (RecvfromFn)GetProcAddress(ws, "recvfrom");
    memset(&g_relay, 0, sizeof g_relay);
    g_relay.sin_family = AF_INET; g_relay.sin_addr.s_addr = inet_addr("127.0.0.1"); g_relay.sin_port = htons(20941);
    g_relay_on = 1; g_relay_test = 1; g_rsock_n = 0;
    memset(g_peer, 0, sizeof g_peer);
    a = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    b = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    memset(&la, 0, sizeof la); la.sin_family = AF_INET; la.sin_addr.s_addr = inet_addr("127.0.0.1");
    lb = la;
    bind(a, (struct sockaddr *)&la, sizeof la); bind(b, (struct sockaddr *)&lb, sizeof lb);
    ln = sizeof la; getsockname(a, (struct sockaddr *)&la, &ln);
    ln = sizeof lb; getsockname(b, (struct sockaddr *)&lb, &ln);
    ioctlsocket(a, FIONBIO, &nb); ioctlsocket(b, FIONBIO, &nb);
    memset(&to, 0, sizeof to); to.sin_family = AF_INET; to.sin_addr.s_addr = inet_addr("127.0.0.2");
    g_my_seat = 1; to.sin_port = htons(20002);                               // seat 1 -> seat 2 (2 not known yet)
    r = relay_sendto(a, "first-to-2", 10, 0, (struct sockaddr *)&to, sizeof to);
    rt_check("seat 1's packet for seat 2 is taken (as sent)", r == 10, "");
    Sleep(200);
    g_my_seat = 2; to.sin_port = htons(20001);                               // seat 2 -> seat 1
    r = relay_sendto(b, "hello-1", 7, 0, (struct sockaddr *)&to, sizeof to);
    r = rt_recv(a, buf, sizeof buf, &from);
    _snprintf(d, sizeof d, "%d bytes from %s:%u", r, inet_ntoa(from.sin_addr), ntohs(from.sin_port)); d[sizeof d - 1] = 0;
    rt_check("seat 1 gets seat 2's packet through the relay", r == 7 && !memcmp(buf, "hello-1", 7), d);
    rt_check("... as if from the address seat 1 sends to (127.0.0.2:20002)", r == 7 &&
             from.sin_addr.s_addr == inet_addr("127.0.0.2") && ntohs(from.sin_port) == 20002, d);
    g_my_seat = 1; to.sin_port = htons(20002);                               // and back: seat 2 is known now
    relay_sendto(a, "hello-2", 7, 0, (struct sockaddr *)&to, sizeof to);
    r = rt_recv(b, buf, sizeof buf, &from);
    _snprintf(d, sizeof d, "%d bytes from %s:%u", r, inet_ntoa(from.sin_addr), ntohs(from.sin_port)); d[sizeof d - 1] = 0;
    rt_check("seat 2 gets seat 1's reply through the relay, from 127.0.0.2:20001", r == 7 && !memcmp(buf, "hello-2", 7) &&
             ntohs(from.sin_port) == 20001, d);
    rt_check("the first packet (before seat 2 was known) was dropped, not delivered late",
             rt_recv(b, buf, sizeof buf, &from) == -2, "");
    r = relay_sendto(a, "direct", 6, 0, (struct sockaddr *)&lb, sizeof lb);  // 127.0.0.1, not a player port: direct
    r = rt_recv(b, buf, sizeof buf, &from);
    _snprintf(d, sizeof d, "%d bytes from port %u", r, ntohs(from.sin_port)); d[sizeof d - 1] = 0;
    rt_check("a packet for this PC's own channel (127.0.0.1) goes direct, untouched", r == 6 && !memcmp(buf, "direct", 6) &&
             from.sin_port == la.sin_port, d);
    r = relay_sendto(a, "big", 3, 0, (struct sockaddr *)&lb, sizeof lb);
    { char tiny[2]; int fl = sizeof from; Sleep(50);       // ("small" is a macro in Windows' own headers)
      r = relay_recvfrom(b, tiny, 2, 0, (struct sockaddr *)&from, &fl);
      rt_check("a datagram bigger than the buffer: WSAEMSGSIZE, like Windows' own", r == SOCKET_ERROR &&
               WSAGetLastError() == WSAEMSGSIZE, ""); }
    g_relay_on = 0;
    r = relay_sendto(a, "off", 3, 0, (struct sockaddr *)&lb, sizeof lb);
    rt_check("switched off: everything goes direct", r == 3, "");
    closesocket(a); closesocket(b);
    g_relay_test = 0; g_my_seat = 0; g_rsock_n = 0;
    logline("relay test: done");
}

// this program is the projector, not seat 1.  play.py gives both programs WCCF_GAME, the game's "extracted" folder
// (kit_common.find_game): the projector runs from it, seat 1 from seat1\ beside it.  Without WCCF_GAME (the player's own
// runs): a folder named "extracted".  WCCFPANEL_ROLE=projector|seat1 decides in the tests.
// ---------------------------------------------------------------- the frame wait (2026-10-06)
// Sega's frame limiter FUN_0075fcd0 (called right before Present) waits for the next 1/30 s by SPINNING: its loop at
// 0x0075FD90 calls the clock FUN_00720540 (microseconds) again and again until the frame's due time, held in esi -
// a whole processor core per game window, even idle (measured 2026-10-06 on this PC, nothing playing: the projector
// ~102%, seat 1 ~69% of one core, the server ~96%).  On a 2-core laptop that leaves too little for the game itself (a
// player: play felt "heavy" from the line-ups on).  That one call now goes to limiter_now(): when the frame is due in
// more than 3 ms it first SLEEPS on a high-resolution waitable timer until 2 ms before, then returns the clock
// exactly as FUN_00720540 does - the loop's own compares (and its wrap-around guard) decide as before, so Sega's
// timing is unchanged; only the empty spinning goes.  Installed only if the loop's bytes are the ones read
// (research\money: pe.py dis seat1 0x0075FCD0) and the timer exists (Windows 10 1803+); else Sega's spin stays.
// A file "limiter_off" beside this DLL switches it off within a second (A/B tests), "frame_stats" logs seat 1's frame
// timing every 10 s; WCCFPANEL_LIMITER=0 keeps it out.
#define LIMITER_CALL  0x0075FD90u                // "call FUN_00720540" inside the spin loop, 16-byte aligned
#define LIMITER_CLOCK 0x00720540u
static const BYTE LIMITER_LOOP[16] = {           // call clock; cmp eax,edi; ja back; cmp eax,esi; jb back; jmp; imul
    0xE8, 0xAB, 0x07, 0xFC, 0xFF, 0x3B, 0xC7, 0x77, 0xF7, 0x3B, 0xC6, 0x72, 0xF3, 0xEB, 0x0D, 0x69 };
typedef unsigned int (__cdecl *ClockFn)(void);
static ClockFn       g_lclock = (ClockFn)(UINT_PTR)LIMITER_CLOCK;  // the self-test swaps in a stand-in
static HANDLE        g_ltimer = NULL;
static DWORD         g_ltid = 0;                 // the one thread that sleeps (the game's main loop)
static int           g_limiter_in = 0;           // the loop's call goes to limiter_now
static volatile LONG g_limiter_on = 0, g_stats_on = 0;
static volatile LONG g_lsleeps = 0, g_llate = 0; // sleeps, and sleeps that woke after the frame was due
static volatile LONG g_lgaps = 0, g_lgap_sum = 0, g_lgap_max = 0, g_lhitch = 0;   // us between frame waits; > 45 ms
static unsigned int  g_llast = 0;                // the clock when the last frame's sleep ended (the waiting thread)

static unsigned int __cdecl limiter_wait(unsigned int due)
{
    unsigned int now = g_lclock(), left = due - now;        // unsigned: a past or wrapped due time is huge: no sleep
    if (g_limiter_on && g_ltimer && left > 3000 && left < 200000) {
        DWORD me = GetCurrentThreadId();
        if (!g_ltid) g_ltid = me;
        if (me == g_ltid) {
            LARGE_INTEGER t;
            t.QuadPart = -(LONGLONG)(left - 2000) * 10;      // relative, in 100 ns
            if (SetWaitableTimer(g_ltimer, &t, 0, NULL, NULL, FALSE) && WaitForSingleObject(g_ltimer, 300) == WAIT_OBJECT_0) {
                now = g_lclock();
                InterlockedIncrement(&g_lsleeps);
                if ((int)(now - due) > 0) InterlockedIncrement(&g_llate);
                if (g_llast) {                   // frames are 33.3 ms apart; a late frame skips its wait: ~67 ms
                    LONG gap = (LONG)(now - g_llast);
                    if (gap > 0 && gap < 2000000) {
                        InterlockedIncrement(&g_lgaps);
                        InterlockedExchangeAdd(&g_lgap_sum, gap);
                        if (gap > g_lgap_max) g_lgap_max = gap;
                        if (gap > 45000) InterlockedIncrement(&g_lhitch);
                    }
                }
                g_llast = now;
            } else {
                now = g_lclock();
            }
        }
    }
    return now;
}

// replaces "call FUN_00720540" in the loop: esi holds the due time; eax = the clock, as the loop expects
static __declspec(naked) void limiter_now(void)
{
    __asm {
        push esi
        call limiter_wait
        add esp, 4
        ret
    }
}

static DWORD WINAPI limiter_watch(LPVOID arg)    // the two switch files, once a second; the sleep counts every 10 s
{
    char off[MAX_PATH], stats[MAX_PATH]; DWORD next = GetTickCount() + 10000; LONG s0 = 0, l0 = 0;
    (void)arg;
    _snprintf(off, MAX_PATH, "%s\\limiter_off", g_dlldir); off[MAX_PATH - 1] = 0;
    _snprintf(stats, MAX_PATH, "%s\\frame_stats", g_dlldir); stats[MAX_PATH - 1] = 0;
    for (;;) {
        LONG on = GetFileAttributesA(off) == INVALID_FILE_ATTRIBUTES, st = GetFileAttributesA(stats) != INVALID_FILE_ATTRIBUTES;
        if (InterlockedExchange(&g_limiter_on, on) != on && g_limiter_in)
            logline("limiter: %s", on ? "ON - the frame wait sleeps until 2 ms before each frame"
                                      : "OFF (limiter_off beside the DLL) - Sega's spin, as before");
        if (InterlockedExchange(&g_stats_on, st) != st) logline("frame stats %s", st ? "on (frame_stats beside the DLL)" : "off");
        if (st && g_limiter_in && (LONG)(GetTickCount() - next) >= 0) {
            LONG s = g_lsleeps, l = g_llate, n = InterlockedExchange(&g_lgaps, 0), sum = InterlockedExchange(&g_lgap_sum, 0);
            LONG mx = InterlockedExchange(&g_lgap_max, 0), h = InterlockedExchange(&g_lhitch, 0);
            logline("limiter: %ld sleeps in 10 s, %ld woke after the frame was due; frames %.1f ms apart on average, "
                    "the longest %.1f ms, %ld over 45 ms", s - s0, l - l0, n ? sum / 1000.0 / n : 0.0, mx / 1000.0, h);
            s0 = s; l0 = l; next = GetTickCount() + 10000;
        }
        Sleep(1000);
    }
}

static void frame_stats_tick(void)               // seat 1's render thread, every game frame (hook_present)
{
    static LARGE_INTEGER f, last, t0; static double sum, mx; static int n, late, was;
    LARGE_INTEGER now; double ms, secs;
    if (!g_stats_on) { was = 0; return; }
    QueryPerformanceCounter(&now);
    if (!was) { was = 1; QueryPerformanceFrequency(&f); last = t0 = now; n = late = 0; sum = mx = 0; return; }
    ms = (double)(now.QuadPart - last.QuadPart) * 1000.0 / (double)f.QuadPart;
    last = now;
    n++; sum += ms;
    if (ms > mx) mx = ms;
    if (ms > 45.0) late++;
    secs = (double)(now.QuadPart - t0.QuadPart) / (double)f.QuadPart;
    if (secs >= 10.0) {
        logline("frames: %d in %.1f s = %.2f a second; %.1f ms apart on average, the longest %.1f ms, %d over 45 ms; "
                "the frame wait %s", n, secs, n / secs, sum / n, mx, late,
                g_limiter_in && g_limiter_on ? "sleeps" : "spins (Sega's)");
        n = late = 0; sum = mx = 0; t0 = now;
    }
}

static void limiter_install(void)
{
    typedef HANDLE (WINAPI *CreateTimerEx)(LPSECURITY_ATTRIBUTES, LPCSTR, DWORD, DWORD);
    char e[8], exe[MAX_PATH], *nm; BYTE *p = (BYTE *)(UINT_PTR)LIMITER_CALL; DWORD prot; LONGLONG old8, new8;
    LONG rel = (LONG)((UINT_PTR)limiter_now - (LIMITER_CALL + 5));
    CreateTimerEx cte = (CreateTimerEx)GetProcAddress(GetModuleHandleA("kernel32.dll"), "CreateWaitableTimerExA");
    if (GetEnvironmentVariableA("WCCFPANEL_LIMITER", e, sizeof e) > 0 && e[0] == '0') {
        logline("limiter: kept out (WCCFPANEL_LIMITER=0) - Sega's spin");
        return;
    }
    GetModuleFileNameA(NULL, exe, MAX_PATH);
    nm = strrchr(exe, '\\'); nm = nm ? nm + 1 : exe;
    if (_stricmp(nm, "client_Release.exe") != 0 || GetModuleHandleA(NULL) != (HMODULE)(UINT_PTR)0x00400000) {
        logline("limiter: not the game (%s) - nothing changed", nm);
        return;
    }
    __try {
        if (memcmp(p, LIMITER_LOOP, sizeof LIMITER_LOOP) != 0) {
            logline("limiter: the frame wait is not the code studied - Sega's spin stays");
            return;
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        logline("limiter: the frame wait could not be read - Sega's spin stays");
        return;
    }
    g_ltimer = cte ? cte(NULL, NULL, 0x00000002 /* CREATE_WAITABLE_TIMER_HIGH_RESOLUTION */, TIMER_ALL_ACCESS) : NULL;
    if (!g_ltimer) {
        logline("limiter: no high-resolution timer here (Windows 10 1803 or later has one) - Sega's spin stays");
        return;
    }
    if (!VirtualProtect(p, 8, PAGE_EXECUTE_READWRITE, &prot)) {
        logline("limiter: the code could not be opened (error %lu) - Sega's spin stays", GetLastError());
        return;
    }
    old8 = *(volatile LONGLONG *)p;
    new8 = old8;
    memcpy((BYTE *)&new8 + 1, &rel, 4);
    {
        char off[MAX_PATH];
        _snprintf(off, MAX_PATH, "%s\\limiter_off", g_dlldir); off[MAX_PATH - 1] = 0;
        g_limiter_on = GetFileAttributesA(off) == INVALID_FILE_ATTRIBUTES;      // on unless limiter_off is there
    }
    if (InterlockedCompareExchange64((volatile LONGLONG *)p, new8, old8) != old8) {
        VirtualProtect(p, 8, prot, &prot);
        logline("limiter: the code changed while being patched - Sega's spin stays");
        return;
    }
    VirtualProtect(p, 8, prot, &prot);
    FlushInstructionCache(GetCurrentProcess(), p, 8);
    g_limiter_in = 1;
    logline("limiter: the frame wait (0x%08lX) now sleeps until 2 ms before each frame; Sega's loop keeps the timing%s",
            (unsigned long)LIMITER_CALL, g_limiter_on ? "" : " - but limiter_off is there: OFF for now");
}

static void limiter_selftest(void);

static void limiter_start(void)                  // both programs: the test (if asked), the change, the two switches
{
    char e[8];
    if (GetEnvironmentVariableA("WCCFPANEL_LIMITERTEST", e, sizeof e) > 0) limiter_selftest();
    limiter_install();
    CreateThread(NULL, 0, limiter_watch, NULL, 0, NULL);
}

// WCCFPANEL_LIMITERTEST=1 (the tests): limiter_wait and limiter_now with a stand-in clock (QueryPerformanceCounter in
// microseconds), on a high-resolution timer of their own - nothing of the game is touched
static unsigned int __cdecl lt_clock(void)
{
    static LARGE_INTEGER f; LARGE_INTEGER c;
    if (!f.QuadPart) QueryPerformanceFrequency(&f);
    QueryPerformanceCounter(&c);
    return (unsigned int)(c.QuadPart * 1000000 / f.QuadPart);
}

static unsigned int lt_call_now(unsigned int due)   // calls limiter_now the way the loop does: due in esi
{
    unsigned int r;
    __asm {
        push esi
        mov esi, due
        call limiter_now
        mov r, eax
        pop esi
    }
    return r;
}

static DWORD WINAPI lt_other(LPVOID arg)
{
    unsigned int due = lt_clock() + 20000, got = limiter_wait(due);
    *(unsigned int *)arg = due - got;                  // how long before the due time it returned
    return 0;
}

static void limiter_selftest(void)
{
    typedef HANDLE (WINAPI *CreateTimerEx)(LPSECURITY_ATTRIBUTES, LPCSTR, DWORD, DWORD);
    CreateTimerEx cte = (CreateTimerEx)GetProcAddress(GetModuleHandleA("kernel32.dll"), "CreateWaitableTimerExA");
    unsigned int due, got, early, other = 0; LONG s0; HANDLE th; int i, worst = 0, ok_all = 1;
    g_lclock = lt_clock;
    g_ltimer = cte ? cte(NULL, NULL, 0x00000002, TIMER_ALL_ACCESS) : NULL;
    logline("limiter test: high-resolution timer %s", g_ltimer ? "made" : "NOT available");
    if (!g_ltimer) return;
    g_limiter_on = 1; g_ltid = 0;
    for (i = 0; i < 20; i++) {                          // 20 frames 20 ms ahead: it must return 1.0-3.0 ms early
        due = lt_clock() + 20000;
        got = lt_call_now(due);
        early = due - got;
        if ((int)early < 1000 || early > 3000) ok_all = 0;
        if ((int)(2000 - early) > worst) worst = (int)(2000 - early);
    }
    logline("limiter test: %s  20 frames 20 ms ahead returned 1.0-3.0 ms before the due time (latest wake %d us past the "
            "2 ms mark)", ok_all ? "PASS" : "FAIL", worst);
    s0 = g_lsleeps;
    due = lt_clock() + 2500; got = lt_call_now(due);
    logline("limiter test: %s  due in 2.5 ms: no sleep, the clock at once", g_lsleeps == s0 && (int)(due - got) > 2000 ? "PASS" : "FAIL");
    due = lt_clock() - 5000; got = lt_call_now(due);
    logline("limiter test: %s  due 5 ms ago (late frame): no sleep", g_lsleeps == s0 ? "PASS" : "FAIL");
    due = lt_clock() + 400000; got = lt_call_now(due);
    logline("limiter test: %s  due 400 ms ahead (not a frame): no sleep", g_lsleeps == s0 ? "PASS" : "FAIL");
    th = CreateThread(NULL, 0, lt_other, &other, 0, NULL);
    if (th) { WaitForSingleObject(th, 5000); CloseHandle(th); }
    logline("limiter test: %s  another thread: no sleep (returned %u us before its due time)",
            g_lsleeps == s0 && other > 15000 ? "PASS" : "FAIL", other);
    g_limiter_on = 0;
    due = lt_clock() + 20000; got = lt_call_now(due);
    logline("limiter test: %s  switched off: no sleep", g_lsleeps == s0 && (int)(due - got) > 15000 ? "PASS" : "FAIL");
    CloseHandle(g_ltimer); g_ltimer = NULL; g_lclock = (ClockFn)(UINT_PTR)LIMITER_CLOCK; g_ltid = 0;
}

static int is_projector(void)
{
    char e[16], exe[MAX_PATH], game[MAX_PATH], full[MAX_PATH], *sl, *dir; DWORD n; size_t k;
    if (GetEnvironmentVariableA("WCCFPANEL_ROLE", e, sizeof e) > 0) return !_stricmp(e, "projector");
    GetModuleFileNameA(NULL, exe, MAX_PATH);
    sl = strrchr(exe, '\\');
    if (!sl) return 0;
    *sl = 0;
    dir = strrchr(exe, '\\');
    if (!_stricmp(dir ? dir + 1 : exe, "extracted")) return 1;
    n = GetEnvironmentVariableA("WCCF_GAME", game, MAX_PATH);
    if (n == 0 || n >= MAX_PATH || !GetFullPathNameA(game, MAX_PATH, full, NULL)) return 0;
    k = strlen(full);
    while (k > 3 && full[k - 1] == '\\') full[--k] = 0;
    return !_stricmp(full, exe);
}

// the two helpers' code from their first byte to the return of their vsprintf_s call, as read 2026-10-06: the place
// is found at ap - 8 (FUN_006d7da0) and ap - 0xC (FUN_00429750) only while these bytes are these
static const BYTE SETTEXT_HEAD[0x35] = {
    0x81, 0xEC, 0x08, 0x04, 0x00, 0x00, 0xA1, 0x08, 0x32, 0xAE, 0x00, 0x33, 0xC4, 0x89, 0x84, 0x24, 0x04, 0x04, 0x00,
    0x00, 0x8B, 0x8C, 0x24, 0x0C, 0x04, 0x00, 0x00, 0x57, 0x8D, 0x84, 0x24, 0x14, 0x04, 0x00, 0x00, 0x50, 0x51, 0x8D,
    0x54, 0x24, 0x0C, 0x68, 0x01, 0x04, 0x00, 0x00, 0x52, 0xFF, 0x15, 0xA8, 0xE6, 0x97, 0x00 };
static const BYTE P429_HEAD[0x19] = {
    0x8B, 0x4C, 0x24, 0x08, 0x53, 0x8D, 0x44, 0x24, 0x10, 0x50, 0x8B, 0x44, 0x24, 0x0C, 0x51, 0x52, 0x50, 0xB3, 0x01,
    0xFF, 0x15, 0xA8, 0xE6, 0x97, 0x00 };

static void money_install(int projector)
{
    static const BYTE SPR_CALL[6] = { 0xFF, 0x15, 0x98, 0xE6, 0x97, 0x00 };
    char exe[MAX_PATH], *nm, e[8]; HMODULE me = GetModuleHandleA(NULL), crt = GetModuleHandleA("msvcr90.dll");
    void *real = crt ? (void *)GetProcAddress(crt, "sprintf_s") : NULL, **slot; int i, bad = 0; DWORD old;
    if (GetEnvironmentVariableA("WCCFPANEL_MONEYTEST", e, sizeof e) > 0) money_selftest();
    GetModuleFileNameA(NULL, exe, MAX_PATH);
    nm = strrchr(exe, '\\'); nm = nm ? nm + 1 : exe;
    if (_stricmp(nm, "client_Release.exe") != 0) { logline("money: off - not the game (%s)", nm); return; }
    if (me != (HMODULE)(UINT_PTR)0x00400000 || !crt || !real) {
        logline("money: off - the program is not where the table was made for (base %p, msvcr90 %p, sprintf_s %p)",
                (void *)me, (void *)crt, real);
        return;
    }
    __try {
        if (memcmp((const void *)(UINT_PTR)0x00A62914, "$%d,000,000", 12) != 0) {
            logline("money: off - English is not on (0x00A62914 is not the kit's \"$%%d,000,000\")");
            return;
        }
        for (i = 0; i < NMSITES; i++) {
            const BYTE *p = (const BYTE *)(UINT_PTR)MSITES[i].ret; int ok;
            DWORD to = (DWORD)(UINT_PTR)p + *(const DWORD *)(p - 4);     // where an E8 call before p goes
            if (MSITES[i].kind == 'S') ok = p[-5] == 0xE8 && to == 0x006D7DA0u;
            else if (MSITES[i].kind == 'Q') ok = p[-5] == 0xE8 && to == 0x00429750u;
            else ok = !memcmp(p - 6, SPR_CALL, 6) || (p[-2] == 0xFF && p[-1] == 0xD7);
            if (!ok) { logline("money: place 0x%08lX (%s) is not the call studied", (unsigned long)MSITES[i].ret, MSITES[i].what); bad++; }
        }
        if (memcmp((const void *)(UINT_PTR)0x006D7DA0u, SETTEXT_HEAD, sizeof SETTEXT_HEAD) != 0 ||
            0x006D7DA0u + sizeof SETTEXT_HEAD != MONEY_SETTEXT_RET) {
            logline("money: FUN_006d7da0 is not the code studied");
            bad++;
        }
        if (memcmp((const void *)(UINT_PTR)0x00429750u, P429_HEAD, sizeof P429_HEAD) != 0 ||
            0x00429750u + sizeof P429_HEAD != MONEY_P429_RET) {
            logline("money: FUN_00429750 is not the code studied");
            bad++;
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        logline("money: off - the program's memory is not as studied (a read failed)");
        return;
    }
    if (bad) { logline("money: off - %d place(s) not as studied: not the program the table was made for", bad); return; }
    slot = iat_slot(me, "msvcr90.dll", "sprintf_s");
    g_msvcr_vsprintf_s = (VsprintfS)GetProcAddress(crt, "vsprintf_s");
    if (!slot || (UINT_PTR)slot != 0x0097E698u || *slot != real || !g_msvcr_vsprintf_s) {
        logline("money: off - the program's sprintf_s import is not as studied (slot %p)", (void *)slot);
        return;
    }
    if (!VirtualProtect(slot, sizeof *slot, PAGE_READWRITE, &old)) {
        logline("money: off - the sprintf_s import could not be opened (error %lu)", GetLastError());
        return;
    }
    g_money_on = 1;                              // before the slot changes: our sprintf_s must find it on
    *slot = (void *)money_sprintf_s;
    VirtualProtect(slot, sizeof *slot, old, &old);
    logline("money: on - %d places checked, amounts with commas (%s)", NMSITES, projector ? "the projector: its 4 places" :
            g_fmt_guard_on ? "seat 1: box texts through the fmt guard, pieces through sprintf_s" :
                             "seat 1: pieces only - the fmt guard is not installed, so no box texts");
}

// ---------------------------------------------------------------- the card dispenser that is not there (2026-10-05)
// Every player card earned adds one to an "owed" count (FUN_004cf650) that only a real dispenser brings down, so seat 1
// kept saying "You are owed N Player Card(s)" (FUN_004ecf80, message 0xc04).  In the game, FUN_004cf650 = ret (no
// card is owed from now on), and the count kept in its backup memory is set to 0 now and then (it comes back from
// the backup at each start).  Only in client_Release.exe, and only if the code is byte for byte the one studied;
// the count is reached the way FUN_004cf650 reaches it: *( *(0x009FBCAC) + 8 ) + 5.
static const BYTE OWED_SIG[16] = { 0x55, 0x8B, 0xEC, 0x83, 0xE4, 0xF8, 0xA1, 0xAC, 0xBC, 0x9F, 0x00, 0x8B, 0x40, 0x08, 0x56, 0x57 };
static int g_owed_fix = 0;

static void dispenser_install(void)
{
    char exe[MAX_PATH], *nm; BYTE *f = (BYTE *)0x004CF650; DWORD old; MEMORY_BASIC_INFORMATION mi;
    GetModuleFileNameA(NULL, exe, MAX_PATH);
    nm = strrchr(exe, '\\'); nm = nm ? nm + 1 : exe;
    if (_stricmp(nm, "client_Release.exe") != 0) { logline("dispenser: not the game (%s) - nothing changed", nm); return; }
    if (!VirtualQuery(f, &mi, sizeof mi) || mi.State != MEM_COMMIT || memcmp(f, OWED_SIG, sizeof OWED_SIG) != 0) {
        logline("dispenser: FUN_004cf650 is not the code studied - nothing changed");
        return;
    }
    if (!VirtualProtect(f, 1, PAGE_EXECUTE_READWRITE, &old)) { logline("dispenser: code not writable - nothing changed"); return; }
    f[0] = 0xC3;                                         // ret: a card it cannot hand out is no longer counted
    VirtualProtect(f, 1, old, &old);
    FlushInstructionCache(GetCurrentProcess(), f, 1);
    g_owed_fix = 1;
    logline("dispenser: FUN_004cf650 patched (ret) - no player card is owed from now on");
}

static void dispenser_tick(void)                         // every 2 s on the render thread: the owed count back to 0
{
    static DWORD next = 0; static int said = 0;
    DWORD now = GetTickCount();
    if (!g_owed_fix || (LONG)(now - next) < 0) return;
    next = now + 2000;
    __try {
        BYTE *p = *(BYTE **)0x009FBCAC, *q = p ? *(BYTE **)(p + 8) : NULL;
        if (q && *(int *)(q + 5) != 0) {
            if (said < 5) { logline("dispenser: %d player card(s) owed -> 0", *(int *)(q + 5)); said++; }
            *(int *)(q + 5) = 0;
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        g_owed_fix = 0;
        logline("dispenser: the owed count could not be reached - stopped");
    }
}

// ---------------------------------------------------------------- install the Present hook
static void *inline_hook5(void *target, void *detour)
{
    unsigned char *t = (unsigned char *)target;
    if (!(t[0] == 0x8B && t[1] == 0xFF && t[2] == 0x55 && t[3] == 0x8B && t[4] == 0xEC)) {
        logline("Present prologue not the expected stub; NOT hooking (safe)"); return NULL;
    }
    unsigned char *tramp = (unsigned char *)VirtualAlloc(NULL, 16, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
    if (!tramp) return NULL;
    memcpy(tramp, t, 5);
    tramp[5] = 0xE9; *(DWORD *)(tramp + 6) = (DWORD)((t + 5) - (tramp + 10));
    DWORD old;
    if (!VirtualProtect(t, 5, PAGE_EXECUTE_READWRITE, &old)) { VirtualFree(tramp, 0, MEM_RELEASE); return NULL; }
    t[0] = 0xE9; *(DWORD *)(t + 1) = (DWORD)((unsigned char *)detour - (t + 5));
    VirtualProtect(t, 5, old, &old);
    FlushInstructionCache(GetCurrentProcess(), t, 5);
    return tramp;
}

static int install_hook(void)
{
    IDirect3D9 *d3d = Direct3DCreate9(D3D_SDK_VERSION);
    if (!d3d) { logline("Direct3DCreate9 failed"); return 0; }
    WNDCLASSA wc; ZeroMemory(&wc, sizeof wc);
    wc.lpfnWndProc = DefWindowProcA; wc.hInstance = GetModuleHandleA(NULL); wc.lpszClassName = "wccfpanel_dummy";
    RegisterClassA(&wc);
    HWND hw = CreateWindowExA(0, "wccfpanel_dummy", "", WS_OVERLAPPED, 0, 0, 8, 8, NULL, NULL, wc.hInstance, NULL);
    if (!hw) { IDirect3D9_Release(d3d); return 0; }
    D3DPRESENT_PARAMETERS pp; ZeroMemory(&pp, sizeof pp);
    pp.Windowed = TRUE; pp.SwapEffect = D3DSWAPEFFECT_DISCARD; pp.BackBufferFormat = D3DFMT_X8R8G8B8;
    pp.BackBufferWidth = 8; pp.BackBufferHeight = 8; pp.BackBufferCount = 1; pp.hDeviceWindow = hw;
    IDirect3DDevice9 *dev = NULL; HRESULT hr = E_FAIL;
    struct { D3DDEVTYPE t; DWORD f; } tries[] = {
        { D3DDEVTYPE_HAL, D3DCREATE_HARDWARE_VERTEXPROCESSING | D3DCREATE_FPU_PRESERVE },
        { D3DDEVTYPE_HAL, D3DCREATE_SOFTWARE_VERTEXPROCESSING | D3DCREATE_FPU_PRESERVE },
        { D3DDEVTYPE_REF, D3DCREATE_SOFTWARE_VERTEXPROCESSING | D3DCREATE_FPU_PRESERVE },
    };
    for (int i = 0; i < 3 && (FAILED(hr) || !dev); i++)
        hr = IDirect3D9_CreateDevice(d3d, D3DADAPTER_DEFAULT, tries[i].t, hw, tries[i].f, &pp, &dev);
    if (FAILED(hr) || !dev) { logline("throwaway CreateDevice failed hr=0x%08lX", (unsigned long)hr);
        DestroyWindow(hw); IDirect3D9_Release(d3d); return 0; }

    void **vtbl = *(void ***)dev;
    void *present_fn = vtbl[17];                 // IDirect3DDevice9::Present
    void *reset_fn = vtbl[16];                   // IDirect3DDevice9::Reset
    logline("shared Present=%p Reset=%p", present_fn, reset_fn);
    IDirect3DDevice9_Release(dev); IDirect3D9_Release(d3d); DestroyWindow(hw);

    void *ptr = inline_hook5(present_fn, (void *)hook_present);
    if (ptr) { g_orig_present = (PresentFn)ptr; g_ready = 1; logline("Present detoured (tramp=%p)", ptr); }
    void *rtr = inline_hook5(reset_fn, (void *)hook_reset);
    if (rtr) { g_orig_reset = (ResetFn)rtr; logline("Reset detoured (tramp=%p)", rtr); }
    return g_ready;
}

static DWORD WINAPI init_thread(LPVOID arg)
{
    char e[8];
    (void)arg;
    Sleep(300);
    if (GetEnvironmentVariableA("WCCFPANEL_RELAYTEST", e, sizeof e) > 0) relay_selftest();   // the tests only
    if (is_projector()) {                        // the projector: amounts with commas, and nothing else of ours
        g_projector = 1;
        logline("wccfpanel init (pid %lu) - the PROJECTOR: money with commas and the frame wait only, no panels",
                (unsigned long)GetCurrentProcessId());
        money_install(1);
        limiter_start();                         // the frame wait sleeps instead of spinning a core
        return 0;
    }
    if (GetEnvironmentVariableA("WCCFPANEL_FULLSCREEN", e, sizeof e) > 0 && e[0] == '0') g_want_fs = 0;
    logline("wccfpanel init (pid %lu) - fullscreen at start: %s", (unsigned long)GetCurrentProcessId(), g_want_fs ? "yes" : "no");
    board_paths();
    keys_init();
    set_init();
    fmt_guard_install();                         // a bad % no longer stops seat 1
    money_install(0);                            // amounts with commas (after the guard: box texts go through it)
    limiter_start();                             // the frame wait sleeps instead of spinning a core
    relay_install();                             // on a server: a match against another player through its relay
    ping_install();                              // on a server: the ping meter (its own socket, every 2 s)
    dispenser_install();                         // no player card owed to a dispenser that is not there
    CreateThread(NULL, 0, board_thread, NULL, 0, NULL);
    if (install_hook()) hook_mouse();
    return 0;
}

BOOL WINAPI DllMain(HINSTANCE inst, DWORD reason, LPVOID reserved)
{
    (void)reserved;
    if (reason == DLL_PROCESS_ATTACH) {
        char *sl;
        DisableThreadLibraryCalls(inst);
        GetModuleFileNameA(inst, g_dlldir, MAX_PATH);    // this DLL's own folder: where our files are
        sl = strrchr(g_dlldir, '\\'); if (sl) *sl = 0;
        InitializeCriticalSection(&g_board_cs);  // before any thread that uses it exists
        CreateThread(NULL, 0, init_thread, NULL, 0, NULL);
    }
    return TRUE;
}
