@echo off
setlocal
cd /d "%~dp0"
python -I "%~dp0standalone_entry.py"
if errorlevel 1 pause
