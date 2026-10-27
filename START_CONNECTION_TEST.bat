@echo off
setlocal
cd /d "%~dp0"
python -I "%~dp0connection_preview.py"
if errorlevel 1 pause
