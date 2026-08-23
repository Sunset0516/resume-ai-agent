@echo off
chcp 65001 >nul
cd /d D:\resume-ai-agent
echo ============================================
echo   Resume AI Agent Starting...
echo   http://127.0.0.1:8000/
echo   http://127.0.0.1:8000/admin
echo ============================================
echo.
D:\resume-ai-agent\venv\Scripts\python.exe run.py --port 8000
pause
