@echo off
chcp 65001 >nul
rem 二游活动聚合 · 一键打开日历(服务没起就先静默拉起服务)
curl -s -o nul -m 2 http://127.0.0.1:5000/api/events >nul 2>&1
if errorlevel 1 (
  echo 正在启动本地服务...
  cd /d "%~dp0"
  set "PY=C:\Users\BBQMARTE\.workbuddy\binaries\python\versions\3.14.3\python.exe"
  if exist "%PY%" (start "ycal-server" /min "%PY%" app.py) else (start "ycal-server" /min py -X utf8 app.py)
  timeout /t 6 /nobreak >nul
)
start "" http://127.0.0.1:5000
exit
