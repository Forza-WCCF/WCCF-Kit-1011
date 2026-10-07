@echo off
rem WCCF 2010-11 kit - the game in English, built from your own game files (Sega's are kept in data\english_backup).
rem "ENGLISH.bat off" puts Sega's Japanese files back; "ENGLISH.bat check" only says what it would do.
"%~dp0python\python.exe" "%~dp0scripts\english.py" %*
echo.
pause
