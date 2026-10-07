// inject.exe (32-bit) - load wccfpanel.dll into a running 32-bit process (seat 1's client_Release.exe).
//   inject.exe <pid> <full\path\to\wccfpanel.dll>
// 32-bit so its kernel32!LoadLibraryA address matches the 32-bit target.
#include <windows.h>
#include <stdio.h>

int main(int argc, char **argv)
{
    if (argc < 3) { printf("usage: inject <pid> <dllpath>\n"); return 2; }
    DWORD pid = (DWORD)atoi(argv[1]);
    HANDLE p = OpenProcess(PROCESS_CREATE_THREAD | PROCESS_VM_OPERATION | PROCESS_VM_WRITE | PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, FALSE, pid);
    if (!p) { printf("OpenProcess(%lu) failed err=%lu\n", pid, GetLastError()); return 1; }
    size_t len = strlen(argv[2]) + 1;
    void *rem = VirtualAllocEx(p, NULL, len, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    if (!rem) { printf("VirtualAllocEx failed err=%lu\n", GetLastError()); CloseHandle(p); return 1; }
    SIZE_T wr = 0;
    if (!WriteProcessMemory(p, rem, argv[2], len, &wr)) { printf("WriteProcessMemory failed err=%lu\n", GetLastError()); CloseHandle(p); return 1; }
    FARPROC ll = GetProcAddress(GetModuleHandleA("kernel32.dll"), "LoadLibraryA");
    HANDLE t = CreateRemoteThread(p, NULL, 0, (LPTHREAD_START_ROUTINE)ll, rem, 0, NULL);
    if (!t) { printf("CreateRemoteThread failed err=%lu\n", GetLastError()); CloseHandle(p); return 1; }
    WaitForSingleObject(t, 6000);
    DWORD ec = 0; GetExitCodeThread(t, &ec);
    printf("injected into pid %lu; LoadLibraryA returned module 0x%08lX%s\n", pid, ec, ec ? "" : " (0 = FAILED to load)");
    CloseHandle(t); CloseHandle(p);
    return ec ? 0 : 1;
}
