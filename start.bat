@echo off
cd /d "%~dp0"

rem If the server is already running, just open the web page.
powershell -NoProfile -Command "$c=New-Object Net.Sockets.TcpClient; try{$c.Connect('127.0.0.1',8765); exit 0}catch{exit 1}finally{$c.Close()}" >nul 2>nul
if %errorlevel%==0 (
  start "" http://127.0.0.1:8765
  exit /b
)

start "" cmd /c "timeout /t 2 >nul & start http://127.0.0.1:8765"
.venv\Scripts\python.exe run.py
