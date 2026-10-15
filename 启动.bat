@echo off
chcp 65001 >nul
cd /d %~dp0
rem 手动启动:允许服务自动打开页面(后台/自动化启动不会设置该变量,避免弹窗盖住用户屏幕)
set "YCAL_OPEN=1"
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
