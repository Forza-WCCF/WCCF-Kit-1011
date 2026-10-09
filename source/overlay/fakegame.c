// fakegame.exe - a stand-in for seat 1's client_Release.exe, to see wccfpanel.dll at work without the game
// (2026-10-08).  A 1440x900 Direct3D 9 window - the game's own size - that presents a plain picture about 60 times a
// second, loads the panel, then plays the steps on its command line and quits:
//
//     fakegame.exe PANEL.dll STEP ...
//       wait:MS          let MS milliseconds of frames go by
//       click:X,Y        a left click at X,Y in the window (client pixels)
//       move:X,Y         the mouse to X,Y, no click
//       close            the window's X (WM_CLOSE): like the real game, the program runs on after its window goes
//       type:TEXT        the keys of TEXT (letters, digits, space)
//       key:VK           one key by its virtual-key code (27 Esc, 8 Backspace, 13 Enter)
//       size:W,H         the window's client size: the panel writes its frame dump (wccfpanel_frame.bmp, beside
//                        this exe) once a new size has held for 10 frames
//       copy:NAME        wccfpanel_frame.bmp copied to NAME
//
// The panel's game-only parts (money, the % guard, the dispenser, the relay) check that they are in the real game
// and stay off here.  Run it with WCCFPANEL_DRYKEYS=1 (button keys are logged, never pressed),
// WCCFPANEL_FULLSCREEN=0 (the window is never maximized over the screen) and WCCF_DATA / WCCF_KEYS on scratch files.
// The window opens off every screen and is never activated, so it takes no focus from what the player is doing.
//
//   cl /nologo /O2 /MT /W3 /D_CRT_SECURE_NO_WARNINGS fakegame.c /Fe:fakegame.exe /link d3d9.lib user32.lib
#define CINTERFACE
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <d3d9.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define GAME_W 1440
#define GAME_H 900

static HWND g_win;

static void client_size(int w, int h)
{
    RECT r = { 0, 0, w, h };
    AdjustWindowRect(&r, WS_OVERLAPPEDWINDOW, FALSE);
    SetWindowPos(g_win, NULL, 0, 0, r.right - r.left, r.bottom - r.top, SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE);
}

static void post_key(WPARAM vk)
{
    LPARAM lp = 1 | ((LPARAM)MapVirtualKeyA((UINT)vk, MAPVK_VK_TO_VSC) << 16);
    PostMessageA(g_win, WM_KEYDOWN, vk, lp);
    PostMessageA(g_win, WM_KEYUP, vk, lp | (1u << 30) | (1u << 31));
}

// one step of the command line; returns how long to let frames run before the next one (ms)
static int step(const char *s, const char *dir)
{
    int a = 0, b = 0;
    if (!strncmp(s, "wait:", 5)) return atoi(s + 5);
    if (!strncmp(s, "click:", 6) && sscanf(s + 6, "%d,%d", &a, &b) == 2) {
        PostMessageA(g_win, WM_MOUSEMOVE, 0, MAKELPARAM(a, b));
        PostMessageA(g_win, WM_LBUTTONDOWN, MK_LBUTTON, MAKELPARAM(a, b));
        PostMessageA(g_win, WM_LBUTTONUP, 0, MAKELPARAM(a, b));
        return 150;
    }
    if (!strcmp(s, "close")) { PostMessageA(g_win, WM_CLOSE, 0, 0); return 150; }
    if (!strncmp(s, "move:", 5) && sscanf(s + 5, "%d,%d", &a, &b) == 2) {
        PostMessageA(g_win, WM_MOUSEMOVE, 0, MAKELPARAM(a, b));
        return 150;
    }
    if (!strncmp(s, "type:", 5)) {
        for (const char *p = s + 5; *p; p++) post_key((WPARAM)(VkKeyScanA(*p) & 0xFF));
        return 150;
    }
    if (!strncmp(s, "key:", 4)) { post_key((WPARAM)atoi(s + 4)); return 150; }
    if (!strncmp(s, "size:", 5) && sscanf(s + 5, "%d,%d", &a, &b) == 2) { client_size(a, b); return 600; }
    if (!strncmp(s, "copy:", 5)) {
        char from[MAX_PATH], to[MAX_PATH];
        _snprintf(from, MAX_PATH, "%s\\wccfpanel_frame.bmp", dir); from[MAX_PATH - 1] = 0;
        _snprintf(to, MAX_PATH, "%s\\%s", dir, s + 5); to[MAX_PATH - 1] = 0;
        if (!CopyFileA(from, to, FALSE)) printf("copy: %s -> %s failed (%lu)\n", from, to, GetLastError());
        return 0;
    }
    printf("unknown step: %s\n", s);
    return 0;
}

int main(int argc, char **argv)
{
    char dir[MAX_PATH], *sl;
    WNDCLASSA wc; IDirect3D9 *d3d; IDirect3DDevice9 *dev = NULL; D3DPRESENT_PARAMETERS pp;
    int next = 2; DWORD due;
    if (argc < 2) { printf("fakegame.exe PANEL.dll [wait:MS click:X,Y move:X,Y close type:TEXT key:VK size:W,H copy:NAME ...]\n"); return 2; }
    GetModuleFileNameA(NULL, dir, MAX_PATH);
    sl = strrchr(dir, '\\'); if (sl) *sl = 0;

    ZeroMemory(&wc, sizeof wc);
    wc.lpfnWndProc = DefWindowProcA; wc.hInstance = GetModuleHandleA(NULL); wc.lpszClassName = "fakegame";
    wc.hCursor = LoadCursor(NULL, IDC_ARROW);
    RegisterClassA(&wc);
    g_win = CreateWindowExA(0, "fakegame", "fakegame (wccfpanel test)", WS_OVERLAPPEDWINDOW, -32000, -32000,
                            GAME_W, GAME_H, NULL, NULL, wc.hInstance, NULL);
    if (!g_win) { printf("no window (%lu)\n", GetLastError()); return 1; }
    client_size(GAME_W, GAME_H);
    ShowWindow(g_win, SW_SHOWNOACTIVATE);

    d3d = Direct3DCreate9(D3D_SDK_VERSION);
    if (!d3d) { printf("no Direct3D 9\n"); return 1; }
    ZeroMemory(&pp, sizeof pp);
    pp.Windowed = TRUE; pp.SwapEffect = D3DSWAPEFFECT_DISCARD; pp.BackBufferFormat = D3DFMT_X8R8G8B8;
    pp.BackBufferWidth = GAME_W; pp.BackBufferHeight = GAME_H; pp.BackBufferCount = 1; pp.hDeviceWindow = g_win;
    if (FAILED(IDirect3D9_CreateDevice(d3d, D3DADAPTER_DEFAULT, D3DDEVTYPE_HAL, g_win,
                                       D3DCREATE_SOFTWARE_VERTEXPROCESSING | D3DCREATE_FPU_PRESERVE, &pp, &dev))) {
        printf("no device\n"); return 1;
    }
    if (!LoadLibraryA(argv[1])) { printf("could not load %s (%lu)\n", argv[1], GetLastError()); return 1; }

    due = GetTickCount() + 2500;                 // the panel's init: its own Present detour, the window, the files
    for (;;) {
        MSG m;
        while (PeekMessageA(&m, NULL, 0, 0, PM_REMOVE)) {
            if (m.message == WM_MOUSELEAVE) continue;    // the real pointer is not over this window: the pointer
            TranslateMessage(&m);                        // stays where the steps put it (the panel's 8 s hover)
            DispatchMessageA(&m);
        }
        if ((LONG)(GetTickCount() - due) >= 0) {
            if (next >= argc) break;
            due = GetTickCount() + (DWORD)step(argv[next++], dir);
        }
        {                                        // "the game": a green pitch with a lighter band
            D3DRECT band = { 0, GAME_H / 3, GAME_W, GAME_H * 2 / 3 };
            IDirect3DDevice9_Clear(dev, 0, NULL, D3DCLEAR_TARGET, D3DCOLOR_XRGB(20, 92, 40), 1.0f, 0);
            IDirect3DDevice9_Clear(dev, 1, &band, D3DCLEAR_TARGET, D3DCOLOR_XRGB(34, 120, 58), 1.0f, 0);
            IDirect3DDevice9_BeginScene(dev);
            IDirect3DDevice9_EndScene(dev);
            IDirect3DDevice9_Present(dev, NULL, NULL, NULL, NULL);
        }
        Sleep(15);
    }
    IDirect3DDevice9_Release(dev);
    IDirect3D9_Release(d3d);
    return 0;
}
