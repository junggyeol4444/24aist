@echo off
chcp 65001 >nul
cd /d "%~dp0.."
if not exist ".venv\Scripts\activate.bat" ( echo 먼저 설치.bat 를 실행하세요. & pause & exit /b 1 )
call ".venv\Scripts\activate.bat"
echo === 완전 자동 운영 (스케줄러가 켜고 끔) ===
echo   창을 닫으면 멈춥니다.
echo   24시간 무인 운영은 자동시작등록.bat 을 쓰세요 ^(작업 스케줄러 등록^).
aist --config config.yaml --persona persona.yaml run
pause
