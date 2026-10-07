@echo off
rem WCCF 2010-11 kit - stop everything PLAY.bat started. It waits for your club card to be out of the reader;
rem "STOP.bat force" stops anyway.
"%~dp0python\python.exe" "%~dp0scripts\play.py" stop %*
echo.
pause
