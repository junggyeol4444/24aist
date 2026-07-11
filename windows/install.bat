@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0.."

echo ============================================
echo   AI 방송인 설치 (install)
echo ============================================
echo.

set "PY=py"
where py >nul 2>nul || set "PY=python"
%PY% --version >nul 2>nul
if errorlevel 1 (
  echo [오류] 파이썬이 없습니다. https://www.python.org 에서 3.10 이상 설치 후
  echo        설치 시 "Add Python to PATH" 를 체크하세요.
  pause & exit /b 1
)

if not exist ".venv\Scripts\activate.bat" (
  echo [1/4] 가상환경 .venv 생성...
  %PY% -m venv .venv || ( echo [오류] venv 생성 실패 & pause & exit /b 1 )
)

call ".venv\Scripts\activate.bat"

echo [2/4] aist 설치 ...
python -m pip install -U pip >nul
pip install -e ".[vtuber,obs,discord,platforms,naver,llm]"
if errorlevel 1 ( echo [오류] 설치 실패 & pause & exit /b 1 )
echo     chroma 기억 / 셀레늄 / 게임은 필요할 때: pip install -e ".[all]"

echo [3/4] 설정 파일 준비...
if not exist "config.yaml"  copy "config\config.example.yaml"  "config.yaml"  >nul
if not exist "persona.yaml" copy "config\persona.example.yaml" "persona.yaml" >nul
if not exist ".env"         copy ".env.example"                 ".env"         >nul

echo [4/4] 설정 점검...
echo.
aist --config config.yaml --persona persona.yaml check

echo.
echo ============================================
echo  설치 끝. 이제 할 일:
echo   1) config.yaml / persona.yaml / .env 를 메모장으로 열어 채우기
echo   2) 방송 코어는 core.bat 로 실행
echo   3) doctor.bat  -^>  test-broadcast.bat  -^>  run.bat
echo ============================================
pause
