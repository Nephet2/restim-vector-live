@echo off
setlocal
cd /d "%~dp0"
python -I "%~dp0preview_ui.py" --curves
if errorlevel 1 pause
