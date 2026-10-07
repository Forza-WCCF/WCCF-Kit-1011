@echo off
rem WCCF 2010-11 kit - set up your copy of the game (once; run it again to check and repair).
rem Drag the game's "extracted" folder onto this file, or double-click it and answer the question.
rem "SETUP.bat undo" puts the game folder back the way the download had it.
"%~dp0python\python.exe" "%~dp0scripts\setup.py" %*
echo.
pause
