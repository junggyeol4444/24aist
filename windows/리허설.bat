@echo off
chcp 65001 >nul
cd /d "%~dp0.."
if not exist ".venv\Scripts\activate.bat" ( echo 먼저 설치.bat 를 실행하세요. & pause & exit /b 1 )
call ".venv\Scripts\activate.bat"

echo === 리허설 (플랫폼/키/OBS 없이 흐름만) ===
echo   가짜 채팅으로 여는 인사 - 채팅 반응 - 혼잣말 - 마무리 인사를 확인합니다.
echo   송출도 공지도 나가지 않습니다. 코어실행.bat 이 먼저 떠 있어야 합니다.
echo   중간에 끄려면 중단.bat 을 더블클릭하세요 ^(다른 창에서^).
echo.
aist --config config.yaml --persona persona.yaml rehearse --minutes 3
pause
