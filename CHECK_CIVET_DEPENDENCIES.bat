@echo off
setlocal
cd /d "%~dp0"
python -I "%~dp0check_bluetooth_dependencies.py"
pause
