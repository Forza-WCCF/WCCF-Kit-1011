/* test_pictures.c - pictures.h on its own (check.ps1 builds and runs it; no game): the fingerprint as english.py
 * computes it (FNV-1a 64's published values), file names, a folder read, and only Sega's exact bytes swapped.
 *   cl /nologo /W3 test_pictures.c && test_pictures.exe */
#include "pictures.h"

static int g_fail = 0, g_n = 0;
#define CHECK(c, what) do { g_n++; if (!(c)) { g_fail++; printf("FAILED: %s (line %d)\n", what, __LINE__); } } while (0)

static void put_file(const char *dir, const char *name, const char *text)
{
    char path[MAX_PATH];
    FILE *f;
    sprintf(path, "%s\\%s", dir, name);
    f = fopen(path, "wb");
    if (f) {
        fwrite(text, 1, strlen(text), f);
        fclose(f);
    }
}

int main(void)
{
    static const unsigned char sega[] = "Sega's picture, as the game hands it over";
    static char english[200];
    char dir[MAX_PATH], name[64], tmp[MAX_PATH];
    pic_t pics[PIC_MAX];
    DWORD size = 0;
    unsigned __int64 fnv = 0;
    const pic_t *p;
    int n;

    /* the fingerprint: FNV-1a 64's published values (english.py's fnv64 is checked against the same two) */
    CHECK(pic_fnv((const unsigned char *)"", 0) == 0xCBF29CE484222325ULL, "FNV-1a 64 of nothing");
    CHECK(pic_fnv((const unsigned char *)"a", 1) == 0xAF63DC4C8601EC8CULL, "FNV-1a 64 of \"a\"");

    /* names */
    CHECK(pic_name("8320-41F664A8F473DADB.dds", &size, &fnv) && size == 8320 && fnv == 0x41F664A8F473DADBULL,
          "english.py's name: size and fingerprint read");
    CHECK(!pic_name("8320-41F664A8F473DADB.dds.tmp", &size, &fnv), "a half-written file (.tmp) is not ours");
    CHECK(!pic_name("8320-41f664a8f473dadb.dds", &size, &fnv), "lower-case: not as english.py writes it");
    CHECK(!pic_name("8320-41F664A8F473DAD.dds", &size, &fnv), "15 hex digits: not ours");
    CHECK(!pic_name("SCM_Foot_Wait.dds", &size, &fnv), "a picture's own name: not ours");
    CHECK(!pic_name("0-41F664A8F473DADB.dds", &size, &fnv), "size 0: not ours");

    /* a folder: one good picture, one with a bad name, one that is no DDS, one half written */
    GetTempPathA(sizeof tmp, tmp);
    sprintf(dir, "%swccf_test_pictures_%lu", tmp, GetCurrentProcessId());
    CreateDirectoryA(dir, NULL);
    memset(english, 'E', sizeof english - 1);
    memcpy(english, "DDS ", 4);
    sprintf(name, "%u-%016I64X.dds", (unsigned)(sizeof sega - 1), pic_fnv(sega, sizeof sega - 1));
    put_file(dir, name, english);
    put_file(dir, "SCM_Foot_Wait.dds", english);
    sprintf(name, "%u-%016I64X.dds", 300u, 0x1234ULL);
    put_file(dir, name, "not a DDS file at all, though its name is right .................................................................................................................");
    sprintf(name, "%u-%016I64X.dds.tmp", 300u, 0x1234ULL);
    put_file(dir, name, english);
    n = pic_load(dir, pics, PIC_MAX);
    CHECK(n == 1, "the folder: only the good picture is loaded");
    CHECK(n == 1 && pics[0].size == sizeof sega - 1 && pics[0].eng_size == sizeof english - 1 &&
          memcmp(pics[0].eng, "DDS ", 4) == 0, "... with Sega's size and the English file's bytes");
    CHECK(pic_load(dir, pics, 0) == 0, "no room: nothing loaded");
    CHECK(pic_load("C:\\no\\such\\folder", pics, PIC_MAX) == 0, "no folder: nothing loaded");

    /* the swap: only Sega's exact bytes */
    n = pic_load(dir, pics, PIC_MAX);
    p = pic_find(pics, n, sega, sizeof sega - 1);
    CHECK(p == &pics[0], "Sega's bytes: the English picture is given");
    {
        unsigned char other[sizeof sega - 1];
        memcpy(other, sega, sizeof other);
        other[0] ^= 1;
        CHECK(pic_find(pics, n, other, sizeof other) == NULL, "the same size, one bit different: left alone");
    }
    CHECK(pic_find(pics, n, sega, sizeof sega - 2) == NULL, "another size: left alone");
    CHECK(pic_find(pics, n, NULL, sizeof sega - 1) == NULL, "no bytes: left alone");
    CHECK(pic_find(pics, 0, sega, sizeof sega - 1) == NULL, "no pictures (Japanese): left alone");

    sprintf(tmp, "%s\\*", dir);
    {
        WIN32_FIND_DATAA fd;
        HANDLE h = FindFirstFileA(tmp, &fd);
        if (h != INVALID_HANDLE_VALUE) {
            do {
                if (!(fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY)) {
                    sprintf(tmp, "%s\\%s", dir, fd.cFileName);
                    DeleteFileA(tmp);
                }
            } while (FindNextFileA(h, &fd));
            FindClose(h);
        }
    }
    RemoveDirectoryA(dir);
    printf("pictures: %d of %d checks passed\n", g_n - g_fail, g_n);
    return g_fail ? 1 : 0;
}
