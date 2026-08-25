@echo off
REM WeChat RPA Skill - Dependency Installer
cd /d "%~dp0\.."
echo Installing Python dependencies...
pip install -r requirements.txt
echo.
echo Done. Run scripts\start.bat to start the service.
pause
