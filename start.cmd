@echo off
rem Alert System launcher - convenience wrapper around start.ps1 (bypasses execution policy)
rem Usage: start.cmd [start^|stop^|restart^|status^|logs^|setup]   (default: start)
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
endlocal
