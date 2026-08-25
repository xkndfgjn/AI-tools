@echo off
REM WeChat RPA Skill - Service Launcher
REM Must be run in the user's interactive desktop session (NOT from a service/sandbox)
cd /d "%~dp0\.."
python src\main.py
pause
