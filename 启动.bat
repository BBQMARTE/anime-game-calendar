@echo off
chcp 65001 >nul
cd /d %~dp0
rem 优先级:环境变量 YCAL_PY > 本机专用 Python > py 启动器 > 系统 python
set "PY=%YCAL_PY%"
if not defined PY set "PY=C:\Users\BBQMARTE\.workbuddy\binaries\python\versions\3.14.3\python.exe"
if exist "%PY%" (
  "%PY%" app.py
  goto :end
)
py -X utf8 app.py
if errorlevel 1 python app.py
:end
pause
