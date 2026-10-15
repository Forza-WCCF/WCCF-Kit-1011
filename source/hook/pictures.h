/* pictures.h - English pictures handed to the game as it loads Sega's (2026-10-15), on their own so test_pictures.c
 * can run them without the game.
 *
 * code\english.py (SETUP's ENGLISH / ITALIANO) redraws languages\english\pictures.tsv's "memory" pictures - the bar's
 * "please wait for the next match" - into data\english_pictures\, each file named by Sega's picture:
 * "<size>-<FNV-1a 64, 16 hex digits>.dds". play.py names that folder to seat 1's hook (WCCF_PICTURES_DIR).
 * The game makes every sbscene picture into a texture with D3DXCreateTextureFromFileInMemoryEx (FUN_00762ac0), handing
 * over the file's bytes: when they are one of those Sega pictures (the same size, the same fingerprint) the hook hands
 * over the English file instead. The game's files are never changed - the redrawn pictures that were ADDED to the
 * archive (english.py PICTURES) made the game give club cards straight back, 2026-10-11. */
#ifndef WCCF_PICTURES_H
#define WCCF_PICTURES_H
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define PIC_MAX 32
#define PIC_BIGGEST (16u << 20)        /* a file larger than this is no picture of ours */

typedef struct {
    DWORD                size;         /* Sega's picture: its size */
    unsigned __int64     fnv;          /*                 its fingerprint */
    const unsigned char *eng;          /* the English one */
    DWORD                eng_size;
    char                 name[48];
} pic_t;

static unsigned __int64 pic_fnv(const unsigned char *p, DWORD n)
{
    unsigned __int64 h = 0xCBF29CE484222325ULL;
    while (n--) {
        h ^= *p++;
        h *= 0x100000001B3ULL;
    }
    return h;
}

/* a file name as english.py makes it -> Sega's size and fingerprint; 0 = not one of ours */
static int pic_name(const char *name, DWORD *size, unsigned __int64 *fnv)
{
    char hex[17], tail[8];
    unsigned long sz;
    if (sscanf(name, "%lu-%16[0-9A-F]%7s", &sz, hex, tail) != 3 || strlen(hex) != 16 || lstrcmpiA(tail, ".dds") != 0 ||
        sz == 0 || sz > PIC_BIGGEST)
        return 0;
    *size = (DWORD)sz;
    *fnv = _strtoui64(hex, NULL, 16);
    return 1;
}

/* every "<size>-<fnv>.dds" in dir that is a DDS file, read into memory: how many (at most max) */
static int pic_load(const char *dir, pic_t *pics, int max)
{
    char pat[MAX_PATH], path[MAX_PATH];
    WIN32_FIND_DATAA fd;
    HANDLE h, f;
    int n = 0;
    if (_snprintf(pat, sizeof pat, "%s\\*.dds", dir) < 0 || (h = FindFirstFileA(pat, &fd)) == INVALID_HANDLE_VALUE)
        return 0;
    do {
        unsigned char *buf;
        DWORD got = 0;
        if (n >= max || (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) || fd.nFileSizeHigh ||
            fd.nFileSizeLow < 128 || fd.nFileSizeLow > PIC_BIGGEST || !pic_name(fd.cFileName, &pics[n].size, &pics[n].fnv) ||
            _snprintf(path, sizeof path, "%s\\%s", dir, fd.cFileName) < 0)
            continue;
        f = CreateFileA(path, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, 0, NULL);
        if (f == INVALID_HANDLE_VALUE)
            continue;
        buf = (unsigned char *)HeapAlloc(GetProcessHeap(), 0, fd.nFileSizeLow);
        if (buf && ReadFile(f, buf, fd.nFileSizeLow, &got, NULL) && got == fd.nFileSizeLow && memcmp(buf, "DDS ", 4) == 0) {
            pics[n].eng = buf;
            pics[n].eng_size = got;
            lstrcpynA(pics[n].name, fd.cFileName, sizeof pics[n].name);
            n++;
        } else if (buf) {
            HeapFree(GetProcessHeap(), 0, buf);
        }
        CloseHandle(f);
    } while (FindNextFileA(h, &fd));
    FindClose(h);
    return n;
}

/* the English picture for the bytes the game hands over, or NULL - fingerprinted only when the size is one of ours */
static const pic_t *pic_find(const pic_t *pics, int n, const void *data, DWORD size)
{
    unsigned __int64 h = 0;
    int i, done = 0;
    if (!data)
        return NULL;
    for (i = 0; i < n; i++) {
        if (pics[i].size != size)
            continue;
        if (!done) {
            h = pic_fnv((const unsigned char *)data, size);
            done = 1;
        }
        if (pics[i].fnv == h)
            return &pics[i];
    }
    return NULL;
}
#endif
