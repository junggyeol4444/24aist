@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0.."

echo ============================================
echo   AI 방송인 (aist) 설치
echo ============================================
echo.

REM 파이썬 확인 (py 런처 우선, 없으면 python)
set "PY=py"
where py >nul 2>nul || set "PY=python"
%PY% --version >nul 2>nul
if errorlevel 1 (
  echo [오류] 파이썬이 없습니다. https://www.python.org 에서 3.10 이상 설치 후
  echo        설치 시 "Add Python to PATH" 를 체크하세요.
  pause & exit /b 1
)

REM 가상환경 생성
if not exist ".venv\Scripts\activate.bat" (
  echo [1/4] 가상환경 .venv 생성...
  %PY% -m venv .venv || ( echo [오류] venv 생성 실패 & pause & exit /b 1 )
)

call ".venv\Scripts\activate.bat"

echo [2/4] aist 설치 (방송/공지/플랫폼/LLM)...
python -m pip install -U pip >nul
pip install -e ".[vtuber,obs,discord,platforms,naver,llm]"
if errorlevel 1 ( echo [오류] 설치 실패 & pause & exit /b 1 )
echo     ( chroma 기억 / 셀레늄 / 게임은 필요할 때: pip install -e ".[all]" )

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
echo   2) 방송 코어는 코어실행.bat 로 (Open-LLM-VTuber)
echo   3) 점검.bat -^> 테스트방송.bat -^> 방송시작.bat
echo ============================================
pause
