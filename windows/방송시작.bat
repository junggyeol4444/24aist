@echo off
chcp 65001 >nul
cd /d "%~dp0.."
if not exist ".venv\Scripts\activate.bat" ( echo 먼저 설치.bat 를 실행하세요. & pause & exit /b 1 )
call ".venv\Scripts\activate.bat"
echo === 완전 자동 운영 (스케줄러가 켜고 끔) ===
echo   창을 닫으면 멈춥니다. 24시간 무인 운영은 배포(install.sh/서비스)를 쓰세요.
aist --config config.yaml --persona persona.yaml run
pause
