@echo off
rem Wrapper for `launch_ui.bat` used by the Startup-folder shortcut
rem (login-time auto-launch). Differences vs the interactive launcher:
rem
rem  - AUTO_OPEN=0  no browser tab pops at every login. The dashboard
rem                 quietly listens on 127.0.0.1:18080; you reach it
rem                 yourself via the bookmarked Tailscale URL
rem                 (https://<host>.<tailnet>.ts.net/portfolio/...)
rem                 or by typing http://127.0.0.1:18080/portfolio.
rem
rem Override at the shortcut level by setting `AUTO_OPEN=1` in the
rem shortcut's command line if you want the popup back. The shortcut
rem typically runs minimized; the cmd window stays open as long as the
rem dashboard runs (closing the window kills the dashboard, which is
rem usually what you want).

setlocal
set "AUTO_OPEN=0"
call "%~dp0launch_ui.bat"
endlocal & exit /b %ERRORLEVEL%
