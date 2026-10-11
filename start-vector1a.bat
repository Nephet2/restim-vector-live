@echo off
setlocal
cd /d "%~dp0"
set "LOCALAPPDATA=%~dp0profile"
python -m vector1a
if errorlevel 1 pause
