/* test_winsize.c - the game's window at the size the game asked for (wccfk.c "window size"; no game). check.ps1 runs it
 * as client_Release.exe in a scratch folder with programs\wccfk.dll, which hooks this program's CreateWindowExA as the
 * game's.  The tablet case (2026-11-23): the projector's 1600x600 window on a 1920x1200 screen at 150 %, 1280x800 for a
 * program that is not DPI aware - Windows cut the window to the screen, the game's frame to ~1284x600, and the picture
 * lost its right part.  Here the window asks for 320 more than this screen allows (1600 - 1280), so the cut happens on
 * any screen; the device is made the game's way (windowed, back-buffer 0 x 0 = the client's size, 0x760E89).
 *   test_winsize.exe <path to wccfk.dll>     (named client_Release.exe) */
#define COBJMACROS
#include <windows.h>
#include <d3d9.h>
#include <math.h>
#include <stdio.h>

static int g_fail = 0, g_n = 0;
#define CHECK(c, what) do { g_n++; if (!(c)) { g_fail++; printf("FAILED: %s (line %d)\n", what, __LINE__); } } while (0)

int main(int argc, char **argv)
{
    const DWORD style = WS_CAPTION | WS_SYSMENU;             /* the game's windowed style (0x91D430) */
    const int ch = 600, pw = 990, ph = 592;                  /* the player's projector window: 990x592 client */
    int cw = GetSystemMetrics(SM_CXMAXTRACK) + 320, fw, fh;
    float a, gw, gh;
    WNDCLASSA wc = {0};
    RECT r, c;
    HWND h;
    IDirect3D9 *d3d;
    IDirect3DDevice9 *dev = NULL;
    IDirect3DSurface9 *bb = NULL;
    D3DPRESENT_PARAMETERS pp;
    D3DSURFACE_DESC d;

    if (argc < 2 || !LoadLibraryA(argv[1])) {
        printf("FAILED: wccfk.dll not loaded (%s)\n", argc > 1 ? argv[1] : "no path given");
        return 1;
    }
    wc.lpfnWndProc = DefWindowProcA;
    wc.hInstance = GetModuleHandleA(NULL);
    wc.lpszClassName = "wccf_test_winsize";
    RegisterClassA(&wc);
    SetRect(&r, 0, 0, cw, ch);                               /* as the game: its client size, framed */
    AdjustWindowRect(&r, style, FALSE);
    h = CreateWindowExA(0, wc.lpszClassName, wc.lpszClassName, style, CW_USEDEFAULT, CW_USEDEFAULT,
                        r.right - r.left, r.bottom - r.top, NULL, NULL, wc.hInstance, NULL);
    CHECK(h != NULL, "the window");
    if (!h)
        goto done;
    GetClientRect(h, &c);
    printf("asked %dx%d, client %ldx%ld\n", cw, ch, c.right, c.bottom);
    CHECK(c.right == cw && c.bottom == ch, "the client is the size the game asked for, wider than the screen");
    fw = c.right; fh = c.bottom;

    ZeroMemory(&pp, sizeof pp);                              /* the game's windowed device: the back-buffer = the client */
    pp.Windowed = TRUE;
    pp.SwapEffect = D3DSWAPEFFECT_DISCARD;
    pp.BackBufferFormat = D3DFMT_UNKNOWN;
    pp.hDeviceWindow = h;
    d3d = Direct3DCreate9(D3D_SDK_VERSION);
    if (d3d && SUCCEEDED(IDirect3D9_CreateDevice(d3d, 0, D3DDEVTYPE_HAL, h, D3DCREATE_SOFTWARE_VERTEXPROCESSING, &pp, &dev)) &&
        SUCCEEDED(IDirect3DDevice9_GetBackBuffer(dev, 0, 0, D3DBACKBUFFER_TYPE_MONO, &bb))) {
        IDirect3DSurface9_GetDesc(bb, &d);
        printf("the game's frame: %ux%u\n", d.Width, d.Height);
        CHECK((int)d.Width == cw && (int)d.Height == ch, "the frame is the game's whole picture, not cut to the screen");
        fw = (int)d.Width; fh = (int)d.Height;
        IDirect3DSurface9_Release(bb);
    } else {
        printf("the frame: skipped - no Direct3D 9 device here (the client's size stands for it)\n");
    }
    if (dev) IDirect3DDevice9_Release(dev);
    if (d3d) IDirect3D9_Release(d3d);

    /* wccfpanel.c draw_game_scaled into the player's window: the whole frame, letterboxed, keeps the game's shape */
    a = (float)fw / (float)fh;
    gw = (float)pw; gh = gw / a;
    if (gh > ph) { gh = (float)ph; gw = gh * a; }
    printf("in the player's %dx%d window: the picture %.0fx%.0f, bars %.0f above and below\n", pw, ph, gw, gh, (ph - gh) / 2);
    CHECK(gw <= pw && gh <= ph, "the letterboxed frame fits the window");
    CHECK(fabsf(gw / gh - (float)cw / (float)ch) < 0.01f, "the letterboxed frame has the whole picture's shape");
    DestroyWindow(h);
done:
    printf("window size: %d of %d checks passed\n", g_n - g_fail, g_n);
    return g_fail ? 1 : 0;
}
