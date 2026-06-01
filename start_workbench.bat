@echo off
cd /d "%~dp0"
py -3 scripts\launch_workbench.py
if errorlevel 1 python scripts\launch_workbench.py
pause

