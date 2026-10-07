@echo off
rem WCCF 2010-11 kit - start the server, the projector and seat 1 (with the overlay and the key driver).
rem "PLAY.bat debug" keeps full logs in data\logs (large) and leaves every window open, this one too.
rem After a good start this window closes by itself; after a problem it stays, so the message can be read.
"%~dp0python\python.exe" "%~dp0scripts\play.py" %*
if errorlevel 1 goto stay
echo %* | find /i "debug" >nul && goto stay
echo.
echo This window closes by itself in 30 seconds (any key closes it now).
timeout /t 30 >nul
exit /b 0
:stay
echo.
pause
