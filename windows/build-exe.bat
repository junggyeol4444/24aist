@echo off
chcp 65001 >nul
cd /d "%~dp0.."
if not exist ".venv\Scripts\activate.bat" ( echo 먼저 install.bat 를 실행하세요. & pause & exit /b 1 )
call ".venv\Scripts\activate.bat"

echo === aist.exe 만들기 [PyInstaller] ===
echo   .bat 로도 충분합니다. 진짜 exe 파일이 필요할 때만 쓰세요.
pip install pyinstaller >nul
pyinstaller --onefile --name aist --collect-submodules aist run_aist.py
if errorlevel 1 ( echo [오류] 빌드 실패 & pause & exit /b 1 )

echo.
echo dist\aist.exe 생성됨.
echo 사용: dist\aist.exe --config config.yaml --persona persona.yaml check
echo 참고: exe 는 자동화 레이어일 뿐. 방송 코어와 OBS 는 따로 실행돼 있어야 합니다.
pause
