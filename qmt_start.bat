@echo off
set PATH=C:\Users\ceicei\AppData\Local\Programs\Python\Python312\;%PATH%
cd /d %~dp0

start "HTTP" cmd /k "python -m http.server 7654 & pause"
start "GRADIO" cmd /k "python gradio_demo.py & pause"

start "" "http://127.0.0.1:7861/"
start "" "http://127.0.0.1:7654/index.html"

echo 所有服务已启动!
pause