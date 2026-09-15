@echo off
chcp 65001 >nul
cd /d "%~dp0.."
if not exist ".venv\Scripts\activate.bat" ( echo 먼저 설치.bat 를 실행하세요. & pause & exit /b 1 )
call ".venv\Scripts\activate.bat"

echo === aist.exe 만들기 (PyInstaller) ===
echo   ( .bat 로도 충분히 쓸 수 있어요. 진짜 exe 파일이 필요할 때만 쓰세요. )
REM  --collect-all tzdata : 윈도우에는 시간대 데이터가 없어서 이걸 안 넣으면
REM  exe 안에서 timezone 설정(Asia/Seoul)이 조용히 무시되고 PC 로컬 시간으로 돈다.
pip install pyinstaller >nul
pyinstaller --onefile --name aist ^
  --collect-submodules aist ^
  --collect-all tzdata ^
  run_aist.py
if errorlevel 1 ( echo [오류] 빌드 실패 & pause & exit /b 1 )

echo.
echo dist\aist.exe 생성됨.
echo 사용: dist\aist.exe --config config.yaml --persona persona.yaml check
echo (참고) exe 는 우리 자동화 레이어일 뿐입니다. 방송 코어(Open-LLM-VTuber)와
echo        OBS 는 따로 실행돼 있어야 실제 방송이 됩니다.
pause
