/*
 * mxhook.c - WCCF RingEdge hardware-emulation shim.
 *
 * A drop-in winmm.dll proxy for the arcade game client_Release.exe. The game
 * is a 2010-11 Sega RingEdge title; on a real cabinet it talks to cabinet
 * hardware (settings chip, save SRAM, JVS IO board, hwmon) through a set of
 * kernel device drivers that do not exist on a plain PC. This shim is the PC
 * stand-in for that hardware - the same role segatools / TeknoParrot play for
 * other Sega boards.
 *
 * It is loaded ONLY by the game processes we launch (client_Release and
 * control_Release import winmm by name, and winmm is not a protected KnownDLL,
 * so our local copy loads first). It touches no other process. What it does:
 *  - logs every device open / file-mapping / DeviceIoControl, passing each
 *    straight through (observation);
 *  - blocks DHCP release/renew on the host NIC (it dropped the player's LAN);
 *  - answers the cabinet's NETWORK-ADDRESS question (2026-10-03): both programs
 *    look up this PC's own addresses (gethostbyname) and demand one in Sega's
 *    arcade network 192.168.46.0/24, else error 8001 "Network address error
 *    (DHCP)" - fatal for the cabinet. The hook presents ONE address,
 *    MXHOOK_NET_IP (default 127.0.0.1), and makes the game's
 *    inet_addr("192.168.46.0") return that address's /24 network, so the check
 *    passes with an address that really exists on this PC. MXHOOK_NET_IP=off
 *    turns this off.
 *
 *  - answers the server's start of logowin.exe itself (no process): see
 *    "logowin" below (2026-10-09; before, the kit put a stand-in exe there);
 *  - loads the kit's overlay (WCCF_PANEL, wccfpanel.dll) once the game's
 *    window is up, for seat 1 and the projector (2026-10-09; before, the
 *    kit's inject.exe wrote it into the game from outside).
 *
 * Load method : winmm.dll proxy in the game folder (no process injection).
 * Hook method : IAT patch of the game module's imports (in-process), by name
 *               or by ordinal (ws2_32 functions are imported by ordinal).
 */

#include <windows.h>
#include <winioctl.h>
#include <stdio.h>
#include <stdarg.h>
#include <string.h>
#include "winmm_fwd.h"   /* generated: forwards all 192 winmm exports to winmm_orig.dll */
#pragma comment(lib, "user32.lib")   /* the overlay: EnumWindows, to see the game's window */

/* ---- logging ----------------------------------------------------------- */

static HANDLE           g_log = INVALID_HANDLE_VALUE;
static CRITICAL_SECTION g_lock;
static LONG             g_ready = 0;
static int              g_verbose = 0;   /* set by env MXHOOK_VERBOSE: log every file open */
static int              g_ringedge = 0;  /* set by env MXHOOK_RINGEDGE=1: stand in for the mx devices */

static void open_log(void)
{
    /* one log per process, in the folder named by MXHOOK_LOG_DIR (the kit's play.py sets it); unset = no log */
    char dir[400], path[512];
    DWORD n = GetEnvironmentVariableA("MXHOOK_LOG_DIR", dir, sizeof(dir));
    if (n == 0 || n >= sizeof(dir))
        return;
    _snprintf(path, sizeof(path) - 1, "%s\\mxhook_%lu.log", dir, GetCurrentProcessId());
    path[sizeof(path) - 1] = 0;
    g_log = CreateFileA(path, GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE,
                        NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
}

static void logline(const char *fmt, ...)
{
    char    buf[1200];
    int     n;
    DWORD   wr;
    va_list ap;

    va_start(ap, fmt);
    n = _vsnprintf(buf, sizeof(buf) - 3, fmt, ap);
    va_end(ap);
    if (n < 0 || n > (int)sizeof(buf) - 3)
        n = (int)sizeof(buf) - 3;
    buf[n++] = '\r';
    buf[n++] = '\n';

    if (!InterlockedCompareExchange(&g_ready, 0, 0))
        return;
    EnterCriticalSection(&g_lock);
    if (g_log != INVALID_HANDLE_VALUE) {
        WriteFile(g_log, buf, (DWORD)n, &wr, NULL);
        FlushFileBuffers(g_log);           /* crash-safe: the game may fault */
    }
    LeaveCriticalSection(&g_lock);
}

/* case-insensitive substring, no CRT locale */
static int ci_has(const char *hay, const char *needle)
{
    size_t nl = strlen(needle);
    const char *p;
    for (p = hay; *p; p++)
        if (_strnicmp(p, needle, nl) == 0)
            return 1;
    return 0;
}

/* Is this CreateFile name worth logging? Device namespace, or a cabinet token.
 * Ordinary game files (textures, data) are skipped to keep the log readable. */
static int interesting_a(const char *n)
{
    if (!n)
        return 0;
    if (n[0] == '\\' && n[1] == '\\')      /* \\.\dev  \\?\dev  \\server */
        return 1;
    return ci_has(n, "moai")  || ci_has(n, "mx")      || ci_has(n, "5c49e1fe") ||
           ci_has(n, "keychip") || ci_has(n, "memcard") || ci_has(n, "eeprom") ||
           ci_has(n, "busram") || ci_has(n, "sram")    || ci_has(n, "jvs")      ||
           ci_has(n, "columba") || ci_has(n, "superio") || ci_has(n, "parallel");
}

static int interesting_w(LPCWSTR w)
{
    char tmp[600];
    int  i = 0;
    if (!w)
        return 0;
    for (; w[i] && i < 599; i++)
        tmp[i] = (char)(w[i] < 128 ? w[i] : '?');
    tmp[i] = 0;
    return interesting_a(tmp);
}

/* ---- winmm exports ------------------------------------------------------
 * We do NOT re-implement winmm. winmm.def (generated by _make_winmm_def.py)
 * forwards every real winmm export to winmm_orig.dll - a copy of the system
 * 32-bit winmm placed beside the game. So this proxy satisfies ALL importers
 * in the process (the exe's time*, glut32's joy*, DirectSound's wave*, ...),
 * not just the three the main exe uses. Our only added behaviour is DllMain,
 * below, installing the kernel32 IAT hooks. */

/* ---- real kernel32 originals (captured when we patch the IAT) ---------- */

typedef HANDLE (WINAPI *pfn_CreateFileW)(LPCWSTR, DWORD, DWORD, LPSECURITY_ATTRIBUTES, DWORD, DWORD, HANDLE);
typedef HANDLE (WINAPI *pfn_CreateFileA)(LPCSTR, DWORD, DWORD, LPSECURITY_ATTRIBUTES, DWORD, DWORD, HANDLE);
typedef HANDLE (WINAPI *pfn_CreateFileMappingA)(HANDLE, LPSECURITY_ATTRIBUTES, DWORD, DWORD, DWORD, LPCSTR);
typedef HANDLE (WINAPI *pfn_OpenFileMappingA)(DWORD, BOOL, LPCSTR);
typedef BOOL   (WINAPI *pfn_DeviceIoControl)(HANDLE, DWORD, LPVOID, DWORD, LPVOID, DWORD, LPDWORD, LPOVERLAPPED);

static pfn_CreateFileW        real_CreateFileW;
static pfn_CreateFileA        real_CreateFileA;
static pfn_CreateFileMappingA real_CreateFileMappingA;
static pfn_OpenFileMappingA   real_OpenFileMappingA;
static pfn_DeviceIoControl    real_DeviceIoControl;

typedef DWORD (WINAPI *pfn_IpAddr)(void *);   /* IpReleaseAddress / IpRenewAddress */
static pfn_IpAddr real_IpReleaseAddress;
static pfn_IpAddr real_IpRenewAddress;

/* ---- hooks: LOG-ONLY, every call passes through to the real function --- */

static HANDLE sram_open(void);
static HANDLE columba_open(void);

static HANDLE WINAPI hook_CreateFileW(LPCWSTR name, DWORD acc, DWORD share,
        LPSECURITY_ATTRIBUTES sa, DWORD disp, DWORD flags, HANDLE tmpl)
{
    HANDLE h;
    DWORD  err;
    if (g_ringedge && name && lstrcmpiW(name, L"\\\\.\\mxsram") == 0)
        return sram_open();
    if (g_ringedge && name && lstrcmpiW(name, L"\\\\.\\columba") == 0)
        return columba_open();
    h   = real_CreateFileW(name, acc, share, sa, disp, flags, tmpl);
    err = GetLastError();
    if (g_verbose || interesting_w(name))
        logline("CreateFileW   \"%S\"  access=0x%08lX -> %s  err=%lu  (h=0x%p)",
                name ? name : L"(null)", acc,
                h == INVALID_HANDLE_VALUE ? "FAIL" : "ok", err, h);
    SetLastError(err);          /* logging must not disturb the caller's last-error */
    return h;
}

static int    vcom_for_name(const char *name);     /* virtual serial ports, below */
static HANDLE vcom_open(int i);

/* ---- RingEdge mx devices (2026-10-04) -------------------------------------
 * In real-cabinet mode (IS_RINGEDGE=1) the player cabinet opens Sega's kernel drivers, which do not
 * exist on a PC. MXHOOK_RINGEDGE=1 makes this hook stand in for them, one at a time:
 *  - \\.\mxsram (battery-backed save memory, client amSramInit FUN_008317c0): a real file mxsram.bin in
 *    the working folder (2 MiB). amSramReadInternal / amSramWriteInternal use SetFilePointer + ReadFile /
 *    WriteFile, which work on the file as they are; the hook answers the device questions:
 *    0x9C406000 version (low word must be 1), 0x00070000 disk geometry (24 bytes), 0x9C406004 sector
 *    size (<= 0x800), 0x0007405C length (8 bytes).
 * Every other device the game opens is logged (and fails as before) so the next one can be added. */

#define MXDEV_MAX   16
#define DEV_SRAM    1
#define DEV_COLUMBA 2
#define SRAM_SIZE   (2 * 1024 * 1024)
#define SRAM_SECTOR 512
static struct { HANDLE h; int kind; } g_dev[MXDEV_MAX];

/* \\.\columba reads PHYSICAL memory (ioctl 0x9C406104, in: {address low, address high, unit, length}).
 * The game (amPlatform*, client FUN_00837e50 / FUN_00837f60) scans 0xF0000-0xFFFFF for the "_DMI_"
 * anchor, reads the SMBIOS table it points to, and keeps: type 0 texts 1-2 (BIOS version, date), type 1
 * text 0 (manufacturer), type 11 texts 0-4 (OEM). Texts are counted from 0. amPlatformGetBoardType
 * (FUN_00824070) wants OEM text 2 = "AAL" (RingEdge; "AAM" = RingWide), manufacturer "NEC", and OEM
 * text 4 not "AAL2" (else RingEdge 2); anything else -> unknown board -> a NULL table -> the crash at
 * ArcadeManager::initialize (FUN_007a5560). This is a fake BIOS area built to those rules. */
#define DMI_BASE   0xE0000
#define DMI_SIZE   0x20000
#define DMI_TABLE  0xE0000
#define DMI_ANCHOR 0xF0010
static unsigned char g_dmi[DMI_SIZE];

static int dmi_put(int at, const void *data, int n)
{
    memcpy(g_dmi + at, data, n);
    return at + n;
}

static int dmi_texts(int at, const char *const *texts, int n)
{
    int i;
    for (i = 0; i < n; i++)
        at = dmi_put(at, texts[i], (int)strlen(texts[i]) + 1);
    g_dmi[at++] = 0;                 /* the empty string that ends the set */
    return at;
}

static void dmi_build(void)
{
    static const unsigned char t0[18] = { 0, 18, 0, 0, 1, 2, 0x00, 0xE8, 3, 0x0F, 0, 0, 0, 0, 0, 0, 0, 0 };
    static const char *const s0[] = { "Phoenix Technologies, LTD", "6.00 PG", "06/20/2008" };
    static const unsigned char t1[8]  = { 1, 8, 1, 0, 1, 2, 3, 4 };
    static const char *const s1[] = { "NEC", "RingEdge", "1.00", "AAL0000000000" };
    static const unsigned char t11[5] = { 11, 5, 2, 0, 5 };
    static const char *const s11[] = { "SEGA", "RINGEDGE", "AAL", "0", " " };
    static const unsigned char t127[4] = { 127, 4, 3, 0 };
    int at = DMI_TABLE - DMI_BASE, start = at, len, i;
    unsigned char a[15], sum = 0;
    ZeroMemory(g_dmi, sizeof(g_dmi));
    at = dmi_put(at, t0, sizeof(t0));
    at = dmi_texts(at, s0, 3);
    at = dmi_put(at, t1, sizeof(t1));
    at = dmi_texts(at, s1, 4);
    at = dmi_put(at, t11, sizeof(t11));
    at = dmi_texts(at, s11, 5);
    at = dmi_put(at, t127, sizeof(t127));
    g_dmi[at++] = 0;
    g_dmi[at++] = 0;
    len = at - start;
    memcpy(a, "_DMI_", 5);
    a[5] = 0;
    a[6] = (unsigned char)len;
    a[7] = (unsigned char)(len >> 8);
    a[8] = (unsigned char)(DMI_TABLE & 0xFF);
    a[9] = (unsigned char)((DMI_TABLE >> 8) & 0xFF);
    a[10] = (unsigned char)((DMI_TABLE >> 16) & 0xFF);
    a[11] = 0;
    a[12] = 4;                       /* number of structures */
    a[13] = 0;
    a[14] = 0x25;                    /* SMBIOS 2.5 */
    for (i = 0; i < 15; i++)
        sum += a[i];
    a[5] = (unsigned char)(0 - sum);
    dmi_put(DMI_ANCHOR - DMI_BASE, a, 15);
}

static int mxdev_kind(HANDLE h)
{
    int i;
    if (!h || h == INVALID_HANDLE_VALUE)
        return 0;
    for (i = 0; i < MXDEV_MAX; i++)
        if (g_dev[i].h == h)
            return g_dev[i].kind;
    return 0;
}

static void mxdev_add(HANDLE h, int kind)
{
    int i;
    for (i = 0; i < MXDEV_MAX; i++)
        if (!g_dev[i].h) {
            g_dev[i].h = h;
            g_dev[i].kind = kind;
            return;
        }
}

static void mxdev_forget(HANDLE h)
{
    int i;
    for (i = 0; i < MXDEV_MAX; i++)
        if (g_dev[i].h == h)
            g_dev[i].h = NULL;
}

static HANDLE sram_open(void)
{
    LARGE_INTEGER size;
    HANDLE h = real_CreateFileA("mxsram.bin", GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE,
                                NULL, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (h == INVALID_HANDLE_VALUE) {
        logline("mxsram: cannot open mxsram.bin (err %lu)", GetLastError());
        return h;
    }
    if (GetFileSizeEx(h, &size) && size.QuadPart < SRAM_SIZE) {
        LARGE_INTEGER end;
        end.QuadPart = SRAM_SIZE;
        SetFilePointerEx(h, end, NULL, FILE_BEGIN);
        SetEndOfFile(h);
        end.QuadPart = 0;
        SetFilePointerEx(h, end, NULL, FILE_BEGIN);
        logline("mxsram: new mxsram.bin, %d bytes of zeros", SRAM_SIZE);
    }
    mxdev_add(h, DEV_SRAM);
    logline("mxsram: \\\\.\\mxsram -> mxsram.bin (h=0x%p)", h);
    SetLastError(0);
    return h;
}

static HANDLE columba_open(void)
{
    HANDLE h = real_CreateFileA("NUL", GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE,
                                NULL, OPEN_EXISTING, 0, NULL);
    if (h != INVALID_HANDLE_VALUE) {
        dmi_build();
        mxdev_add(h, DEV_COLUMBA);
    }
    logline("columba: \\\\.\\columba -> fake BIOS area 0x%05X-0x%05X, SMBIOS table at 0x%05X, anchor at 0x%05X (h=0x%p)",
            DMI_BASE, DMI_BASE + DMI_SIZE - 1, DMI_TABLE, DMI_ANCHOR, h);
    SetLastError(0);
    return h;
}

/* Answers a device question; returns 1 if handled (result in *ok), 0 to pass through. */
static int mxdev_ioctl(HANDLE h, DWORD code, LPVOID ib, DWORD is, LPVOID ob, DWORD os, LPDWORD ret, BOOL *ok)
{
    int kind = mxdev_kind(h);
    DWORD n = 0;
    if (!kind)
        return 0;
    *ok = FALSE;
    if (kind == DEV_COLUMBA) {
        DWORD addr, i;
        if (code != 0x9C406104 || is < 16 || !ib || !ob) {
            logline("columba: unhandled ioctl 0x%08lX (in %lu out %lu)", code, is, os);
            SetLastError(ERROR_INVALID_FUNCTION);
            return 1;
        }
        addr = ((DWORD *)ib)[0];
        for (i = 0; i < os; i++) {
            DWORD p = addr + i;
            ((unsigned char *)ob)[i] = (p >= DMI_BASE && p < DMI_BASE + DMI_SIZE) ? g_dmi[p - DMI_BASE] : 0;
        }
        logline("columba: read %lu bytes at physical 0x%05lX", os, addr);
        n = os;
    } else if (kind == DEV_SRAM) {
        if (code == 0x9C406000 && os >= 4) {
            *(DWORD *)ob = 1;
            n = 4;
        } else if (code == 0x00070000 && os >= sizeof(DISK_GEOMETRY)) {
            DISK_GEOMETRY *g = (DISK_GEOMETRY *)ob;
            ZeroMemory(g, sizeof(*g));
            g->Cylinders.QuadPart = 1;
            g->MediaType = FixedMedia;
            g->TracksPerCylinder = 1;
            g->SectorsPerTrack = SRAM_SIZE / SRAM_SECTOR;
            g->BytesPerSector = SRAM_SECTOR;
            n = sizeof(DISK_GEOMETRY);
        } else if (code == 0x9C406004 && os >= 4) {
            *(DWORD *)ob = SRAM_SECTOR;
            n = 4;
        } else if (code == 0x0007405C && os >= 8) {
            ((LARGE_INTEGER *)ob)->QuadPart = SRAM_SIZE;
            n = 8;
        } else {
            logline("mxsram: unhandled ioctl 0x%08lX (out %lu)", code, os);
            SetLastError(ERROR_INVALID_FUNCTION);
            return 1;
        }
    }
    if (ret)
        *ret = n;
    *ok = TRUE;
    return 1;
}

static HANDLE WINAPI hook_CreateFileA(LPCSTR name, DWORD acc, DWORD share,
        LPSECURITY_ATTRIBUTES sa, DWORD disp, DWORD flags, HANDLE tmpl)
{
    HANDLE h;
    DWORD  err;
    int    vi = vcom_for_name(name);
    if (vi >= 0)
        return vcom_open(vi);
    h   = real_CreateFileA(name, acc, share, sa, disp, flags, tmpl);
    err = GetLastError();
    if (g_verbose || interesting_a(name))
        logline("CreateFileA   \"%s\"  access=0x%08lX -> %s  err=%lu  (h=0x%p)",
                name ? name : "(null)", acc,
                h == INVALID_HANDLE_VALUE ? "FAIL" : "ok", err, h);
    SetLastError(err);          /* logging must not disturb the caller's last-error */
    return h;
}

static HANDLE WINAPI hook_CreateFileMappingA(HANDLE fh, LPSECURITY_ATTRIBUTES sa,
        DWORD prot, DWORD hi, DWORD lo, LPCSTR name)
{
    HANDLE h   = real_CreateFileMappingA(fh, sa, prot, hi, lo, name);
    DWORD  err = GetLastError();
    logline("CreateFileMappingA  \"%s\"  size=%lu -> 0x%p  err=%lu",
            name ? name : "(anon)", lo, h, err);
    SetLastError(err);          /* game checks ERROR_ALREADY_EXISTS here */
    return h;
}

static HANDLE WINAPI hook_OpenFileMappingA(DWORD acc, BOOL inherit, LPCSTR name)
{
    HANDLE h   = real_OpenFileMappingA(acc, inherit, name);
    DWORD  err = GetLastError();
    logline("OpenFileMappingA    \"%s\"  -> %s  err=%lu  (h=0x%p)",
            name ? name : "(null)", h ? "FOUND" : "NOT FOUND", err, h);
    SetLastError(err);
    return h;
}

static int mxdev_ioctl(HANDLE h, DWORD code, LPVOID ib, DWORD is, LPVOID ob, DWORD os, LPDWORD ret, BOOL *ok);

static BOOL WINAPI hook_DeviceIoControl(HANDLE h, DWORD code, LPVOID ib, DWORD is,
        LPVOID ob, DWORD os, LPDWORD ret, LPOVERLAPPED ov)
{
    BOOL  r;
    DWORD err;
    if (g_ringedge && mxdev_ioctl(h, code, ib, is, ob, os, ret, &r)) {
        err = GetLastError();
        logline("DeviceIoControl     h=0x%p  ioctl=0x%08lX  inSz=%lu outSz=%lu -> %s (emulated)",
                h, code, is, os, r ? "ok" : "FAIL");
        SetLastError(err);
        return r;
    }
    r   = real_DeviceIoControl(h, code, ib, is, ob, os, ret, ov);
    err = GetLastError();
    logline("DeviceIoControl     h=0x%p  ioctl=0x%08lX  inSz=%lu outSz=%lu -> %s  err=%lu",
            h, code, is, os, r ? "ok" : "FAIL", err);
    SetLastError(err);
    return r;
}

/* ---- iphlpapi stubs ----------------------------------------------------
 * On boot the game does a DHCP release/renew (IpReleaseAddress + IpRenewAddress) on a host NIC
 * it enumerates - normal for a cabinet that owns its network, but on this PC it DROPS the real
 * LAN (the "cable keeps disconnecting"). These stubs return NO_ERROR without touching any adapter,
 * so the game believes it configured its network and the host connection is never disturbed. */
static DWORD WINAPI hook_IpReleaseAddress(void *info)
{
    (void)info;
    logline("IpReleaseAddress  BLOCKED (would release the host DHCP lease) -> NO_ERROR");
    return 0;   /* NO_ERROR */
}
static DWORD WINAPI hook_IpRenewAddress(void *info)
{
    (void)info;
    logline("IpRenewAddress    BLOCKED (would renew the host DHCP lease) -> NO_ERROR");
    return 0;   /* NO_ERROR */
}

/* ---- the cabinet's network address --------------------------------------
 * client FUN_004584c0 / control FUN_00409a80: gethostname -> gethostbyname, then for each address
 * test (addr & inet_addr("255.255.255.0")) == inet_addr("192.168.46.0"); every address before a match
 * sets error 8001. We answer gethostbyname(<this PC>) with ONE address (MXHOOK_NET_IP) and
 * inet_addr("192.168.46.0") with that address's /24 network. Nothing else is changed. */

typedef struct hostent *(WINAPI *pfn_gethostbyname)(const char *);
typedef unsigned long   (WINAPI *pfn_inet_addr)(const char *);
typedef int             (WINAPI *pfn_gethostname)(char *, int);
static pfn_gethostbyname real_gethostbyname;
static pfn_inet_addr     real_inet_addr;

static int            g_net_on = 0;
static char           g_net_ip[32];
static struct in_addr g_net_addr;
static char          *g_net_list[2];
static char          *g_net_alias[1];
static char           g_net_name[256];
static struct hostent g_net_host;

static int parse_ipv4(const char *s, struct in_addr *out)
{
    unsigned a, b, c, d;
    char tail;
    if (sscanf(s, "%u.%u.%u.%u%c", &a, &b, &c, &d, &tail) != 4 || a > 255 || b > 255 || c > 255 || d > 255)
        return 0;
    out->S_un.S_un_b.s_b1 = (u_char)a;
    out->S_un.S_un_b.s_b2 = (u_char)b;
    out->S_un.S_un_b.s_b3 = (u_char)c;
    out->S_un.S_un_b.s_b4 = (u_char)d;
    return 1;
}

static void net_setup(void)
{
    char v[64];
    DWORD n = GetEnvironmentVariableA("MXHOOK_NET_IP", v, sizeof(v));
    if (n == 0 || n >= sizeof(v))
        lstrcpyA(v, "127.0.0.1");
    if (lstrcmpiA(v, "off") == 0) {
        logline("network address: OFF (MXHOOK_NET_IP=off) - the game sees this PC's real addresses");
        return;
    }
    if (!parse_ipv4(v, &g_net_addr)) {
        logline("network address: MXHOOK_NET_IP=\"%s\" is not an IPv4 address - OFF", v);
        return;
    }
    lstrcpynA(g_net_ip, v, sizeof(g_net_ip));
    g_net_list[0] = (char *)&g_net_addr;
    g_net_list[1] = NULL;
    g_net_alias[0] = NULL;
    g_net_host.h_name = g_net_name;
    g_net_host.h_aliases = g_net_alias;
    g_net_host.h_addrtype = AF_INET;
    g_net_host.h_length = 4;
    g_net_host.h_addr_list = g_net_list;
    g_net_on = 1;
}

static int is_this_pc(const char *name)
{
    char me[256];
    pfn_gethostname gh;
    HMODULE ws = GetModuleHandleA("ws2_32.dll");
    if (!name || !*name)
        return 1;
    gh = ws ? (pfn_gethostname)GetProcAddress(ws, "gethostname") : NULL;
    if (!gh || gh(me, sizeof(me)) != 0)
        return 0;
    if (lstrcmpiA(name, me) != 0)
        return 0;
    lstrcpynA(g_net_name, me, sizeof(g_net_name));
    return 1;
}

static struct hostent *WINAPI hook_gethostbyname(const char *name)
{
    if (g_net_on && is_this_pc(name)) {
        logline("gethostbyname(\"%s\") -> %s only  (MXHOOK_NET_IP; the real list is not shown to the game)",
                name ? name : "", g_net_ip);
        return &g_net_host;
    }
    return real_gethostbyname(name);
}

static unsigned long WINAPI hook_inet_addr(const char *cp)
{
    if (g_net_on && cp && lstrcmpA(cp, "192.168.46.0") == 0) {
        unsigned long net = g_net_addr.S_un.S_addr & 0x00FFFFFFUL;   /* first three octets, network order */
        logline("inet_addr(\"192.168.46.0\") -> %u.%u.%u.0  (the arcade network = MXHOOK_NET_IP's /24)",
                g_net_addr.S_un.S_un_b.s_b1, g_net_addr.S_un.S_un_b.s_b2, g_net_addr.S_un.S_un_b.s_b3);
        return net;
    }
    return real_inet_addr(cp);
}

/* ---- IAT patch (operates on our own host process, in-memory) ----------- */

/* ---- virtual serial ports (2026-10-04) ----------------------------------
 * The player cabinet's Club Team Card reader is a serial device: client FUN_004d5820 opens "COM1"
 * (COM3 on a real cabinet), 115200 8N1, then polls ClearCommError for bytes and reads exactly those.
 * MXHOOK_COM = "COM1=\\.\pipe\wccf_icc_seat1" (several separated by ';') makes CreateFileA of that
 * port open the named pipe instead; a stand-in reader (.work/_icc_reader.py) is the pipe's server.
 * On such a handle the comm functions succeed, ClearCommError reports the bytes waiting in the pipe,
 * and ReadFile waits at most the port's timeouts (capped at 1 s) and never for more than is there.
 * Without MXHOOK_COM nothing here is installed. */

#define MAX_VCOM 4
typedef struct {
    char         com[16];
    char         pipe[200];
    HANDLE       h;
    DCB          dcb;
    COMMTIMEOUTS to;
    int          jvs;        /* the I/O board ("mxjvs"): overlapped I/O and the JVS sense line */
    int          addressed;  /* JVS: the game sent "set address" (F1) since its last reset (F0 D9) */
} vcom_t;
/* CORRECTION (2026-10-04, .work/jvs_init_debug.md): on "\\.\mxjvs" (JVS mode 2) the game sends every
 * command as DeviceIoControl 0x9C402000, which this hook does not serve. FUN_008387b0 / FUN_00838850
 * below are the MODE 0 helpers, used on "COM4" - seat 1's exe is patched to mode 0 for that reason.
 * The I/O board (2026-10-04): client amJvstDriverSetup FUN_008398c0 opens "\\.\mxjvs" OVERLAPPED;
 * FUN_008387b0 / FUN_00838850 write and read with an OVERLAPPED and wait 150 ms on its event, and
 * assume a completed read delivered every byte asked for. With MXHOOK_COM "mxjvs=\\.\pipe\..." the
 * board stand-in (.work/_jvs_board.py) serves it; these requests are completed at once (event set) or,
 * if the bytes do not come within ~120 ms, left "pending" so the game's own 150 ms timeout applies.
 * The SENSE line comes from GetCommModemStatus (FUN_00839730: DSR 0x20, RLSD 0x80 -> 0..3); the node
 * setup (code around 0x0082DA0A / 0x0082DB9F) reads 2 = no board, 3 = a board without an address,
 * 1 = all boards addressed. So: no bits until the game has sent F1 (set address), then DSR. */
static vcom_t g_vcom[MAX_VCOM];
static int    g_nvcom = 0;

typedef BOOL (WINAPI *pfn_GetCommState)(HANDLE, LPDCB);
typedef BOOL (WINAPI *pfn_SetupComm)(HANDLE, DWORD, DWORD);
typedef BOOL (WINAPI *pfn_PurgeComm)(HANDLE, DWORD);
typedef BOOL (WINAPI *pfn_GetCommTimeouts)(HANDLE, LPCOMMTIMEOUTS);
typedef BOOL (WINAPI *pfn_GetCommModemStatus)(HANDLE, LPDWORD);
typedef BOOL (WINAPI *pfn_ClearCommError)(HANDLE, LPDWORD, LPCOMSTAT);
typedef BOOL (WINAPI *pfn_ReadFile)(HANDLE, LPVOID, DWORD, LPDWORD, LPOVERLAPPED);
typedef BOOL (WINAPI *pfn_WriteFile)(HANDLE, LPCVOID, DWORD, LPDWORD, LPOVERLAPPED);
typedef BOOL (WINAPI *pfn_GetOverlappedResult)(HANDLE, LPOVERLAPPED, LPDWORD, BOOL);
typedef BOOL (WINAPI *pfn_CancelIo)(HANDLE);
typedef BOOL (WINAPI *pfn_CloseHandle)(HANDLE);
static pfn_WriteFile           real_WriteFile;
static pfn_GetOverlappedResult real_GetOverlappedResult;
static pfn_CancelIo            real_CancelIo;
static pfn_GetCommState       real_GetCommState, real_SetCommState;
static pfn_SetupComm          real_SetupComm;
static pfn_PurgeComm          real_PurgeComm;
static pfn_GetCommTimeouts    real_GetCommTimeouts, real_SetCommTimeouts;
static pfn_GetCommModemStatus real_GetCommModemStatus;
static pfn_ClearCommError     real_ClearCommError;
static pfn_ReadFile           real_ReadFile;
static pfn_CloseHandle        real_CloseHandle;

static void vcom_setup(void)
{
    char  all[1024], *item, *next;
    DWORD n = GetEnvironmentVariableA("MXHOOK_COM", all, sizeof(all));
    if (n == 0 || n >= sizeof(all))
        return;
    for (item = all; item && *item && g_nvcom < MAX_VCOM; item = next) {
        char *eq;
        next = strchr(item, ';');
        if (next)
            *next++ = 0;
        eq = strchr(item, '=');
        if (!eq || eq == item || eq - item >= (int)sizeof(g_vcom[0].com))
            continue;
        *eq = 0;
        lstrcpynA(g_vcom[g_nvcom].com, item, sizeof(g_vcom[0].com));
        lstrcpynA(g_vcom[g_nvcom].pipe, eq + 1, sizeof(g_vcom[0].pipe));
        /* the I/O board: "mxjvs", or any port served by the JVS stand-in's pipe. In JVS mode 0 (seat 1's
         * patch 0x004D91C9 push 1 -> push 0) the game opens the board as "COM4" (FUN_0082d5b0). */
        {
            char low[sizeof(g_vcom[0].pipe)];
            lstrcpynA(low, eq + 1, sizeof(low));
            _strlwr(low);
            g_vcom[g_nvcom].jvs = (lstrcmpiA(item, "mxjvs") == 0) || strstr(low, "jvs") != NULL;
        }
        g_nvcom++;
    }
}

static int vcom_for_name(const char *name)
{
    int i;
    if (!name)
        return -1;
    if (_strnicmp(name, "\\\\.\\", 4) == 0)
        name += 4;
    for (i = 0; i < g_nvcom; i++)
        if (lstrcmpiA(name, g_vcom[i].com) == 0)
            return i;
    return -1;
}

static int vcom_for_handle(HANDLE h)
{
    int i;
    if (!h || h == INVALID_HANDLE_VALUE)
        return -1;
    for (i = 0; i < g_nvcom; i++)
        if (g_vcom[i].h == h)
            return i;
    return -1;
}

static DWORD vcom_waiting(HANDLE h)
{
    DWORD avail = 0;
    if (!PeekNamedPipe(h, NULL, 0, NULL, &avail, NULL))
        avail = 0;
    return avail;
}

static HANDLE vcom_open(int i)
{
    HANDLE h = real_CreateFileA(g_vcom[i].pipe, GENERIC_READ | GENERIC_WRITE, 0, NULL, OPEN_EXISTING, 0, NULL);
    DWORD  err = GetLastError();
    if (h != INVALID_HANDLE_VALUE) {
        DWORD mode = PIPE_READMODE_BYTE;
        SetNamedPipeHandleState(h, &mode, NULL, NULL);
        ZeroMemory(&g_vcom[i].dcb, sizeof(DCB));
        g_vcom[i].dcb.DCBlength = sizeof(DCB);
        g_vcom[i].dcb.BaudRate = 115200;
        g_vcom[i].dcb.ByteSize = 8;
        g_vcom[i].dcb.fBinary = 1;
        ZeroMemory(&g_vcom[i].to, sizeof(COMMTIMEOUTS));
        g_vcom[i].h = h;
    }
    logline("virtual port %s -> pipe %s : %s (err %lu)", g_vcom[i].com, g_vcom[i].pipe,
            h == INVALID_HANDLE_VALUE ? "NO READER (pipe not there)" : "connected", err);
    SetLastError(h == INVALID_HANDLE_VALUE ? ERROR_FILE_NOT_FOUND : 0);
    return h;
}

static BOOL WINAPI hook_GetCommState(HANDLE h, LPDCB d)
{
    int i = vcom_for_handle(h);
    if (i < 0)
        return real_GetCommState(h, d);
    *d = g_vcom[i].dcb;
    return TRUE;
}

static BOOL WINAPI hook_SetCommState(HANDLE h, LPDCB d)
{
    int i = vcom_for_handle(h);
    if (i < 0)
        return real_SetCommState(h, d);
    g_vcom[i].dcb = *d;
    logline("virtual port %s: SetCommState %lu baud, %d bits, parity %d, stop %d", g_vcom[i].com,
            d->BaudRate, d->ByteSize, d->Parity, d->StopBits);
    return TRUE;
}

static BOOL WINAPI hook_SetupComm(HANDLE h, DWORD in, DWORD out)
{
    return vcom_for_handle(h) < 0 ? real_SetupComm(h, in, out) : TRUE;
}

static BOOL WINAPI hook_PurgeComm(HANDLE h, DWORD flags)
{
    char  junk[256];
    DWORD got;
    if (vcom_for_handle(h) < 0)
        return real_PurgeComm(h, flags);
    if (flags & PURGE_RXCLEAR)
        while (vcom_waiting(h) > 0 && real_ReadFile(h, junk, min(vcom_waiting(h), sizeof(junk)), &got, NULL) && got)
            ;
    return TRUE;
}

static BOOL WINAPI hook_GetCommTimeouts(HANDLE h, LPCOMMTIMEOUTS t)
{
    int i = vcom_for_handle(h);
    if (i < 0)
        return real_GetCommTimeouts(h, t);
    *t = g_vcom[i].to;
    return TRUE;
}

static BOOL WINAPI hook_SetCommTimeouts(HANDLE h, LPCOMMTIMEOUTS t)
{
    int i = vcom_for_handle(h);
    if (i < 0)
        return real_SetCommTimeouts(h, t);
    g_vcom[i].to = *t;
    return TRUE;
}

static BOOL WINAPI hook_GetCommModemStatus(HANDLE h, LPDWORD s)
{
    int i = vcom_for_handle(h);
    if (i < 0)
        return real_GetCommModemStatus(h, s);
    if (g_vcom[i].jvs)
        *s = g_vcom[i].addressed ? MS_DSR_ON : 0;    /* sense: 1 = addressed, 3 = board waiting */
    else
        *s = MS_CTS_ON | MS_DSR_ON;
    return TRUE;
}

/* A request on a virtual port is finished at once: the OVERLAPPED says done and its event is set. */
static BOOL vcom_complete(LPOVERLAPPED ov, LPDWORD got, DWORD n)
{
    if (got)
        *got = n;
    if (ov) {
        ov->Internal = 0;                /* STATUS_SUCCESS */
        ov->InternalHigh = n;
        if (ov->hEvent)
            SetEvent(ov->hEvent);
    }
    return TRUE;
}

/* JVS: watch what the game sends for reset (F0 D9) and set address (F1 n), to drive the sense line. */
static void jvs_watch(int i, const unsigned char *p, DWORD n)
{
    DWORD k;
    for (k = 0; k + 1 < n; k++) {
        if (p[k] == 0xF0 && p[k + 1] == 0xD9 && g_vcom[i].addressed) {
            g_vcom[i].addressed = 0;
            logline("JVS: reset seen - sense = board waiting for an address");
        } else if (p[k] == 0xF1 && !g_vcom[i].addressed) {
            g_vcom[i].addressed = 1;
            logline("JVS: set address %u seen - sense = all addressed", p[k + 1]);
        }
    }
}

static BOOL WINAPI hook_WriteFile(HANDLE h, LPCVOID buf, DWORD n, LPDWORD put, LPOVERLAPPED ov)
{
    int   i = vcom_for_handle(h);
    DWORD done = 0;
    BOOL  r;
    if (i < 0)
        return real_WriteFile(h, buf, n, put, ov);
    if (g_vcom[i].jvs)
        jvs_watch(i, (const unsigned char *)buf, n);
    r = real_WriteFile(h, buf, n, &done, NULL);     /* the pipe is synchronous */
    if (!r)
        return FALSE;
    return vcom_complete(ov, put, done);
}

static BOOL WINAPI hook_GetOverlappedResult(HANDLE h, LPOVERLAPPED ov, LPDWORD got, BOOL wait)
{
    if (vcom_for_handle(h) < 0)
        return real_GetOverlappedResult(h, ov, got, wait);
    if (got)
        *got = (DWORD)ov->InternalHigh;
    return TRUE;
}

static BOOL WINAPI hook_CancelIo(HANDLE h)
{
    return vcom_for_handle(h) < 0 ? real_CancelIo(h) : TRUE;
}

static BOOL WINAPI hook_ClearCommError(HANDLE h, LPDWORD errs, LPCOMSTAT st)
{
    if (vcom_for_handle(h) < 0)
        return real_ClearCommError(h, errs, st);
    if (errs)
        *errs = 0;
    if (st) {
        ZeroMemory(st, sizeof(COMSTAT));
        st->cbInQue = vcom_waiting(h);
    }
    return TRUE;
}

static BOOL WINAPI hook_ReadFile(HANDLE h, LPVOID buf, DWORD n, LPDWORD got, LPOVERLAPPED ov)
{
    int   i = vcom_for_handle(h);
    DWORD limit, waited = 0, avail, done = 0;
    if (i < 0)
        return real_ReadFile(h, buf, n, got, ov);
    if (ov) {
        /* overlapped (the I/O board): wait for ALL n bytes; if they do not come, leave it "pending" */
        while ((avail = vcom_waiting(h)) < n && waited < 120) {
            Sleep(1);
            waited++;
        }
        if (avail < n) {
            SetLastError(ERROR_IO_PENDING);
            return FALSE;
        }
        if (!real_ReadFile(h, buf, n, &done, NULL))
            return FALSE;
        return vcom_complete(ov, got, done);
    }
    limit = g_vcom[i].to.ReadTotalTimeoutConstant + g_vcom[i].to.ReadTotalTimeoutMultiplier * n;
    if (g_vcom[i].to.ReadIntervalTimeout == MAXDWORD && limit == 0)
        limit = 0;                       /* "return at once with what is there" */
    else if (limit == 0 || limit > 1000)
        limit = 1000;                    /* a real port would block; never hang the game */
    while ((avail = vcom_waiting(h)) == 0 && waited < limit) {
        Sleep(1);
        waited++;
    }
    if (avail == 0) {
        if (got)
            *got = 0;
        return TRUE;
    }
    if (!real_ReadFile(h, buf, min(n, avail), &done, NULL))
        return FALSE;
    if (got)
        *got = done;
    return TRUE;
}

static BOOL WINAPI hook_CloseHandle(HANDLE h)
{
    int i = vcom_for_handle(h);
    if (i >= 0) {
        logline("virtual port %s closed", g_vcom[i].com);
        g_vcom[i].h = NULL;
    }
    if (g_ringedge)
        mxdev_forget(h);
    return real_CloseHandle(h);
}

/* fn != NULL: match the import by name; fn == NULL: match it by ordinal `ord`. */
static void *patch_iat_any(HMODULE mod, const char *dll, const char *fn, WORD ord, void *newfn)
{
    BYTE                     *base = (BYTE *)mod;
    IMAGE_DOS_HEADER         *dos  = (IMAGE_DOS_HEADER *)base;
    IMAGE_NT_HEADERS         *nt;
    IMAGE_DATA_DIRECTORY      d;
    IMAGE_IMPORT_DESCRIPTOR  *imp;

    if (dos->e_magic != IMAGE_DOS_SIGNATURE)
        return NULL;
    nt = (IMAGE_NT_HEADERS *)(base + dos->e_lfanew);
    d  = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
    if (!d.VirtualAddress)
        return NULL;
    imp = (IMAGE_IMPORT_DESCRIPTOR *)(base + d.VirtualAddress);

    for (; imp->Name; imp++) {
        const char       *dn = (const char *)(base + imp->Name);
        IMAGE_THUNK_DATA *oft, *ft;
        if (lstrcmpiA(dn, dll) != 0)
            continue;
        if (!imp->OriginalFirstThunk)      /* need the name/ordinal table to match */
            continue;
        oft = (IMAGE_THUNK_DATA *)(base + imp->OriginalFirstThunk);
        ft  = (IMAGE_THUNK_DATA *)(base + imp->FirstThunk);
        for (; oft->u1.AddressOfData; oft++, ft++) {
            IMAGE_IMPORT_BY_NAME *ibn;
            void  *orig;
            DWORD  prot;
            if (oft->u1.Ordinal & IMAGE_ORDINAL_FLAG) {
                if (fn || IMAGE_ORDINAL(oft->u1.Ordinal) != ord)
                    continue;
            } else {
                if (!fn)
                    continue;
                ibn = (IMAGE_IMPORT_BY_NAME *)(base + oft->u1.AddressOfData);
                if (lstrcmpA((const char *)ibn->Name, fn) != 0)
                    continue;
            }
            orig = (void *)ft->u1.Function;
            if (!VirtualProtect(&ft->u1.Function, sizeof(void *), PAGE_READWRITE, &prot))
                return NULL;
            ft->u1.Function = (ULONG_PTR)newfn;
            VirtualProtect(&ft->u1.Function, sizeof(void *), prot, &prot);
            return orig;
        }
    }
    return NULL;
}

static void *patch_iat(HMODULE mod, const char *dll, const char *fn, void *newfn)
{
    return patch_iat_any(mod, dll, fn, 0, newfn);
}

/* Hook a kernel32 import; the original is returned even if the exe does not import it (then the hook
 * is simply not installed), so a real_ pointer is never NULL. *installed counts the hooks that took. */
static void *hook_k32(HMODULE exe, const char *fn, void *newfn, int *installed)
{
    void *orig = patch_iat(exe, "kernel32.dll", fn, newfn);
    if (orig)
        (*installed)++;
    else
        orig = (void *)GetProcAddress(GetModuleHandleA("kernel32.dll"), fn);
    return orig;
}

static void install_vcom_hooks(HMODULE exe)
{
    int n = 0, i;
    vcom_setup();
    if (g_nvcom == 0)
        return;
    real_GetCommState       = (pfn_GetCommState)       hook_k32(exe, "GetCommState",       hook_GetCommState, &n);
    real_SetCommState       = (pfn_GetCommState)       hook_k32(exe, "SetCommState",       hook_SetCommState, &n);
    real_SetupComm          = (pfn_SetupComm)          hook_k32(exe, "SetupComm",          hook_SetupComm, &n);
    real_PurgeComm          = (pfn_PurgeComm)          hook_k32(exe, "PurgeComm",          hook_PurgeComm, &n);
    real_GetCommTimeouts    = (pfn_GetCommTimeouts)    hook_k32(exe, "GetCommTimeouts",    hook_GetCommTimeouts, &n);
    real_SetCommTimeouts    = (pfn_GetCommTimeouts)    hook_k32(exe, "SetCommTimeouts",    hook_SetCommTimeouts, &n);
    real_GetCommModemStatus = (pfn_GetCommModemStatus) hook_k32(exe, "GetCommModemStatus", hook_GetCommModemStatus, &n);
    real_ClearCommError     = (pfn_ClearCommError)     hook_k32(exe, "ClearCommError",     hook_ClearCommError, &n);
    real_ReadFile           = (pfn_ReadFile)           hook_k32(exe, "ReadFile",           hook_ReadFile, &n);
    real_WriteFile          = (pfn_WriteFile)          hook_k32(exe, "WriteFile",          hook_WriteFile, &n);
    real_GetOverlappedResult = (pfn_GetOverlappedResult) hook_k32(exe, "GetOverlappedResult", hook_GetOverlappedResult, &n);
    real_CancelIo           = (pfn_CancelIo)           hook_k32(exe, "CancelIo",           hook_CancelIo, &n);
    real_CloseHandle        = (pfn_CloseHandle)        hook_k32(exe, "CloseHandle",        hook_CloseHandle, &n);
    for (i = 0; i < g_nvcom; i++)
        logline("virtual port %s -> %s%s (serial hooks installed: %d of 13)", g_vcom[i].com, g_vcom[i].pipe,
                g_vcom[i].jvs ? " [JVS I/O board]" : "", n);
}

/* ---- logowin.exe (2026-10-09) -------------------------------------------
 * control_Release starts Sega's logowin.exe for its logo and error screens
 * (FUN_00453bd0: CreateProcessA("logowin.exe", "logowin.exe error=..." or
 * "... warning=.. sega=.. allnet=.. mainid=.. keychipid=..")) - a white,
 * always-on-top window over the whole screen. It only ever asks whether it
 * still runs (GetExitCodeProcess == STILL_ACTIVE, FUN_00453f70) and, to end
 * it, posts WM_CLOSE to the window "logowin" or calls TerminateProcess
 * (FUN_00453ef0). So no program is started: the message goes to
 * logowin_messages.txt in the current folder (the game's), as the kit's
 * stand-in logowin.exe wrote it, and the server gets a handle to its own
 * process with query rights only - "still running", as the stand-in was until
 * the server ended, and a TerminateProcess on it fails harmlessly. The
 * stand-in, a windowless exe that waited on its parent, was what antivirus
 * programs flagged. Any other CreateProcessA (match_Release, FPR_Emu) passes. */

typedef BOOL (WINAPI *pfn_CreateProcessA)(LPCSTR, LPSTR, LPSECURITY_ATTRIBUTES, LPSECURITY_ATTRIBUTES, BOOL, DWORD,
                                          LPVOID, LPCSTR, LPSTARTUPINFOA, LPPROCESS_INFORMATION);
static pfn_CreateProcessA real_CreateProcessA;

static int is_logowin(LPCSTR app, LPCSTR cmd)
{
    const char *p = app ? app : cmd, *base;
    if (!p)
        return 0;
    base = strrchr(p, '\\');
    base = base ? base + 1 : p;
    return _strnicmp(base, "logowin.exe", 11) == 0 && (base[11] == 0 || base[11] == ' ' || base[11] == '"');
}

static BOOL WINAPI hook_CreateProcessA(LPCSTR app, LPSTR cmd, LPSECURITY_ATTRIBUTES pa, LPSECURITY_ATTRIBUTES ta,
                                       BOOL inherit, DWORD flags, LPVOID env, LPCSTR dir, LPSTARTUPINFOA si,
                                       LPPROCESS_INFORMATION pi)
{
    HANDLE me = GetCurrentProcess(), h = NULL, t = NULL;
    SYSTEMTIME st;
    FILE *f;
    if (!is_logowin(app, cmd))
        return real_CreateProcessA(app, cmd, pa, ta, inherit, flags, env, dir, si, pi);
    GetLocalTime(&st);
    f = fopen("logowin_messages.txt", "a");
    if (f) {
        fprintf(f, "%04d-%02d-%02d %02d:%02d:%02d  started by pid %lu  %s  (not run: the kit's winmm.dll)\n",
                st.wYear, st.wMonth, st.wDay, st.wHour, st.wMinute, st.wSecond,
                (unsigned long)GetCurrentProcessId(), cmd ? cmd : app);
        fclose(f);
    }
    logline("logowin: not started (%s)", cmd ? cmd : app);
    if (!pi || !DuplicateHandle(me, me, me, &h, PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, FALSE, 0)
            || !DuplicateHandle(me, me, me, &t, PROCESS_QUERY_LIMITED_INFORMATION, FALSE, 0)) {
        if (h)
            CloseHandle(h);
        SetLastError(ERROR_FILE_NOT_FOUND);
        return FALSE;            /* the server's own "could not start it" path: nothing shows either way */
    }
    pi->hProcess = h;
    pi->hThread = t;             /* the server closes it at once */
    pi->dwProcessId = 0;
    pi->dwThreadId = 0;
    return TRUE;
}

static void install_hooks(void)
{
    HMODULE exe = GetModuleHandleW(NULL);

    real_CreateFileW        = (pfn_CreateFileW)        patch_iat(exe, "kernel32.dll", "CreateFileW",        hook_CreateFileW);
    real_CreateFileA        = (pfn_CreateFileA)        patch_iat(exe, "kernel32.dll", "CreateFileA",        hook_CreateFileA);
    real_CreateFileMappingA = (pfn_CreateFileMappingA) patch_iat(exe, "kernel32.dll", "CreateFileMappingA", hook_CreateFileMappingA);
    real_OpenFileMappingA   = (pfn_OpenFileMappingA)   patch_iat(exe, "kernel32.dll", "OpenFileMappingA",   hook_OpenFileMappingA);
    real_DeviceIoControl    = (pfn_DeviceIoControl)    patch_iat(exe, "kernel32.dll", "DeviceIoControl",    hook_DeviceIoControl);
    real_IpReleaseAddress   = (pfn_IpAddr) patch_iat(exe, "iphlpapi.dll", "IpReleaseAddress", hook_IpReleaseAddress);
    real_IpRenewAddress     = (pfn_IpAddr) patch_iat(exe, "iphlpapi.dll", "IpRenewAddress",   hook_IpRenewAddress);
    real_CreateProcessA     = (pfn_CreateProcessA) patch_iat(exe, "kernel32.dll", "CreateProcessA", hook_CreateProcessA);

    logline("==== mxhook attached (pid %lu) ====", GetCurrentProcessId());
    {
        char v[8];
        DWORD n = GetEnvironmentVariableA("MXHOOK_RINGEDGE", v, sizeof(v));
        g_ringedge = (n == 1 && v[0] == '1');
    }
    install_vcom_hooks(exe);
    if (g_ringedge && !real_CloseHandle) {
        int n = 0;
        real_CloseHandle = (pfn_CloseHandle)hook_k32(exe, "CloseHandle", hook_CloseHandle, &n);
    }
    logline("RingEdge devices (MXHOOK_RINGEDGE): %s", g_ringedge ? "ON - mxsram" : "off");
    net_setup();
    if (g_net_on) {   /* ws2_32 ordinals: 52 gethostbyname, 11 inet_addr (both exes import them by ordinal) */
        real_gethostbyname = (pfn_gethostbyname) patch_iat_any(exe, "ws2_32.dll", NULL, 52, hook_gethostbyname);
        real_inet_addr     = (pfn_inet_addr)     patch_iat_any(exe, "ws2_32.dll", NULL, 11, hook_inet_addr);
        if (!real_gethostbyname || !real_inet_addr) {
            g_net_on = 0;   /* half a hook would be worse than none */
            logline("network address: hook NOT installed (gethostbyname=%d inet_addr=%d) - OFF",
                    real_gethostbyname != 0, real_inet_addr != 0);
        } else {
            logline("network address: this PC is presented to the game as %s (MXHOOK_NET_IP)", g_net_ip);
        }
    }
    logline("hooks installed: CreateFileW=%d CreateFileA=%d CreateFileMappingA=%d OpenFileMappingA=%d DeviceIoControl=%d  IpRelease=%d IpRenew=%d  CreateProcessA=%d  gethostbyname=%d inet_addr=%d",
            real_CreateFileW != 0, real_CreateFileA != 0, real_CreateFileMappingA != 0,
            real_OpenFileMappingA != 0, real_DeviceIoControl != 0,
            real_IpReleaseAddress != 0, real_IpRenewAddress != 0, real_CreateProcessA != 0,
            g_net_on && real_gethostbyname != 0, g_net_on && real_inet_addr != 0);
}

/* ---- the kit's overlay (2026-10-09) -------------------------------------
 * WCCF_PANEL = the kit's overlay\wccfpanel.dll. play.py names it only for
 * seat 1 and the projector (never the server). 3 s after this game shows a
 * window - when play.py used to inject it - this process loads it itself, a
 * plain LoadLibrary. Before, overlay\inject.exe wrote the path into the game
 * and started a thread there (VirtualAllocEx + CreateRemoteThread), which
 * antivirus programs flag. No window in 120 s: not loaded, the game runs on. */

static char g_panel[MAX_PATH];

static BOOL CALLBACK panel_window(HWND h, LPARAM found)
{
    DWORD pid = 0;
    GetWindowThreadProcessId(h, &pid);
    if (pid == GetCurrentProcessId() && IsWindowVisible(h)) {
        *(int *)found = 1;
        return FALSE;
    }
    return TRUE;
}

static DWORD WINAPI panel_thread(LPVOID arg)
{
    int found = 0, tries;
    (void)arg;
    for (tries = 0; tries < 240 && !found; tries++) {
        Sleep(500);
        EnumWindows(panel_window, (LPARAM)&found);
    }
    if (!found) {
        logline("overlay: no window of this game in 120 s - %s not loaded", g_panel);
        return 0;
    }
    Sleep(3000);
    if (LoadLibraryA(g_panel))
        logline("overlay: %s loaded", g_panel);
    else
        logline("overlay: %s did NOT load (error %lu)", g_panel, GetLastError());
    return 0;
}

BOOL WINAPI DllMain(HINSTANCE inst, DWORD reason, LPVOID reserved)
{
    DWORD n;
    HANDLE t;
    (void)reserved;
    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(inst);
        InitializeCriticalSection(&g_lock);
        open_log();
        InterlockedExchange(&g_ready, 1);
        g_verbose = (GetEnvironmentVariableA("MXHOOK_VERBOSE", NULL, 0) > 0);
        install_hooks();
        /* the thread starts once the loader is done with every DLL: LoadLibrary is safe there, never here */
        n = GetEnvironmentVariableA("WCCF_PANEL", g_panel, MAX_PATH);
        if (n > 0 && n < MAX_PATH && (t = CreateThread(NULL, 0, panel_thread, NULL, 0, NULL)) != NULL)
            CloseHandle(t);
    }
    return TRUE;
}
