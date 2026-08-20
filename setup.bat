@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File setup.ps1
pause
