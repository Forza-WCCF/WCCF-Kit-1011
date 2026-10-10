/* test_wholemsg.c - wholemsg.h on its own (check.ps1 builds and runs it; no game, no network).
 *   cl /nologo /W3 test_wholemsg.c && test_wholemsg.exe */
#include <stdio.h>
#include <string.h>
#include "wholemsg.h"

static int g_fail = 0, g_n = 0;
#define CHECK(c, what) do { g_n++; if (!(c)) { g_fail++; printf("FAILED: %s (line %d)\n", what, __LINE__); } } while (0)

static void put32(unsigned char *p, unsigned v)
{
    p[0] = (unsigned char)v; p[1] = (unsigned char)(v >> 8); p[2] = (unsigned char)(v >> 16); p[3] = (unsigned char)(v >> 24);
}

/* a batch of records (id, body size) with bodies filled with b's: returns its size */
static unsigned batch(unsigned char *p, int count, const char *const *ids, const unsigned *sizes, unsigned char b)
{
    unsigned off = 8;
    int i;
    for (i = 0; i < count; i++) {
        memset(p + off, 0, 16);
        memcpy(p + off, ids[i], strlen(ids[i]) < 16 ? strlen(ids[i]) : 16);
        put32(p + off + 16, sizes[i]);
        memset(p + off + 20, b, sizes[i]);
        off += 20 + sizes[i];
    }
    put32(p, (unsigned)count);
    put32(p + 4, off);
    return off;
}

int main(void)
{
    static unsigned char a[200000], buf[400000];
    const char *ids[] = {"TO MATCH INI", "KEEP_ALIVE", "SIXTEEN_CHAR_ID!"};
    unsigned sizes[] = {8524, 0, 4}, one[] = {284};
    unsigned n1, n2, k, skip, bad;

    n1 = batch(a, 3, ids, sizes, 0x00);                 /* bodies of zeros, like real ones often are */
    CHECK(n1 == 8 + 20 * 3 + 8528, "batch size");
    CHECK(wm_check(a, n1) == (int)n1, "a whole batch");
    for (k = 0, bad = 0; k < n1; k++)                   /* every place TCP can split it */
        if (wm_check(a, k) != 0)
            bad++;
    CHECK(bad == 0, "every split of it: wait for the rest, never a fault");
    CHECK(wm_whole(a, n1 - 1, WM_MAX_BATCH, &skip) == 0 && skip == 0, "one byte short: nothing yet, nothing skipped");

    n2 = batch(a + n1, 1, ids, one, 0x41);
    CHECK(wm_whole(a, n1 + n2, WM_MAX_BATCH, &skip) == n1 + n2 && skip == 0, "two batches back to back: both");
    CHECK(wm_whole(a, n1 + n2, n1 + n2 - 1, &skip) == n1, "only what fits in the server's buffer");
    CHECK(wm_whole(a, n1 + 5, WM_MAX_BATCH, &skip) == n1, "a whole one and the start of the next: the whole one");

    memcpy(buf, a, n1);                                 /* an empty batch is a batch */
    put32(buf, 0); put32(buf + 4, 8);
    CHECK(wm_check(buf, 8) == 8, "count 0, total 8");

    memcpy(buf, a, n1); put32(buf + 4, 7);
    CHECK(wm_check(buf, n1) == -1, "total smaller than its own head");
    memcpy(buf, a, n1); put32(buf + 4, WM_MAX_BATCH + 1);
    CHECK(wm_check(buf, n1) == -1, "total bigger than the server's buffer");
    memcpy(buf, a, n1); put32(buf, 1000);
    CHECK(wm_check(buf, n1) == -1, "more records than fit");
    memcpy(buf, a, n1); put32(buf + 8 + 16, 8525);
    CHECK(wm_check(buf, n1) == -1, "a body size one too big: the records do not add up");
    memcpy(buf, a, n1); put32(buf + 8 + 16, 8523);
    CHECK(wm_check(buf, n1) == -1, "a body size one too small");
    memcpy(buf, a, n1); buf[8] = 0;
    CHECK(wm_check(buf, n1) == -1, "an empty id");
    memcpy(buf, a, n1); buf[10] = 0x07;
    CHECK(wm_check(buf, n1) == -1, "a control character in an id");
    memcpy(buf, a, n1); put32(buf + 4, 0x9F5406C1u);
    CHECK(wm_check(buf, 8) == -1, "the wild length seen in the crash: refused from its first 8 bytes");

    memset(buf, 0xEE, 37);                              /* garbage, then a good batch: skipped, not a disconnect */
    memcpy(buf + 37, a, n1);
    CHECK(wm_whole(buf, 37 + n1, WM_MAX_BATCH, &skip) == n1 && skip == 37, "garbage in front: skipped to the batch");
    CHECK(wm_whole(buf, 37 + 100, WM_MAX_BATCH, &skip) == 0 && skip == 37, "garbage, then a batch not all here");

    printf("wholemsg: %d of %d checks passed\n", g_n - g_fail, g_n);
    return g_fail != 0;
}
