@echo off
chcp 65001 >nul
cd /d "%~dp0.."
if not exist ".venv\Scripts\activate.bat" ( echo 먼저 설치.bat 를 실행하세요. & pause & exit /b 1 )
call ".venv\Scripts\activate.bat"
echo === 지금 한 방송만 (시작 수동, 종료는 자동) ===
echo.
echo   끄려면 : 중단.bat 을 더블클릭하세요 ^(다른 창에서^). 이게 가장 안전합니다.
echo   이 창을 X 로 닫으면 OBS 스트림이 켜진 채 남습니다.
echo   ^(Ctrl+C 는 cmd 가 "끝내시겠습니까 (Y/N)?" 를 먼저 물어서,
echo     Y 를 누르면 정리 중간에 끊길 수 있습니다^)
echo.
aist --config config.yaml --persona persona.yaml broadcast-now
pause
