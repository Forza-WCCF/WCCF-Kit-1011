/* The kit's hook (wccfk.dll) forwards ONLY the three timer functions the game imports - timeGetTime,
   timeBeginPeriod, timeEndPeriod - to the REAL winmm (Windows' own, in System32). The hook no longer impersonates
   winmm.dll: SETUP renames the game's import from WINMM.dll to the kit's own name (code\patch_hook_import.py), so
   there is no system-named side-loading DLL for Windows Defender to flag, and no winmm_orig.dll beside the game. */
#pragma comment(linker, "/export:timeGetTime=winmm.timeGetTime")
#pragma comment(linker, "/export:timeBeginPeriod=winmm.timeBeginPeriod")
#pragma comment(linker, "/export:timeEndPeriod=winmm.timeEndPeriod")
