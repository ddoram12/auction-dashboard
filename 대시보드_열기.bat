@echo off
chcp 65001 > nul
echo ===================================================
echo  온비드 · 신탁사 · 법원경매 통합 대시보드를 실행합니다...
echo ===================================================

cd /d "%~dp0"

netstat -ano | findstr 8501 > nul
if %errorlevel% neq 0 (
    echo [안내] 대시보드 서버를 백그라운드에서 시작하는 중입니다...
    start /min python -m streamlit run "app.py" --server.port 8501 --server.headless false
    timeout /t 3 > nul
)

start http://localhost:8501
exit
