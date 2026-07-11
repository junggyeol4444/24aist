@echo off
chcp 65001 >nul
cd /d "%~dp0.."
if not exist ".venv\Scripts\activate.bat" ( echo 먼저 설치.bat 를 실행하세요. & pause & exit /b 1 )
call ".venv\Scripts\activate.bat"
echo === 직전 방송 리포트 (누가 왔는지 / 단골 / AI 발화 전문) ===
aist --config config.yaml --persona persona.yaml report
echo.
echo === 컨텐츠 팩 (하이라이트 후보 / 다시보기 제목) ===
aist --config config.yaml --persona persona.yaml content
pause
