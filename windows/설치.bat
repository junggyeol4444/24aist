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
  echo [오류] 파이썬이 없습니다. https://www.python.org 에서 3.12 를 설치하고
  echo        설치 시 "Add Python to PATH" 를 체크하세요.
  pause & exit /b 1
)

REM 방송 코어는 파이썬 3.10~3.12 만 지원한다(Open-LLM-VTuber/pyproject.toml).
REM python.org 에서 '최신'을 받으면 그 범위 밖이라, aist 는 깔리는데
REM 코어만 설치에 실패한다 — 왜 실패했는지 알기 어려운 자리라 먼저 막는다.
for /f "tokens=2 delims= " %%V in ('%PY% --version 2^>^&1') do set "PYVER=%%V"
for /f "tokens=1,2 delims=." %%A in ("%PYVER%") do (
  set "PYMAJ=%%A"
  set "PYMIN=%%B"
)
if not "%PYMAJ%"=="3" goto badpy
if %PYMIN% LSS 10 goto badpy
if %PYMIN% GEQ 13 goto badpy
echo     파이썬 %PYVER% 확인
goto pyok

:badpy
echo [오류] 파이썬 %PYVER% 는 방송 코어가 지원하지 않습니다.
echo        코어는 3.10 ~ 3.12 만 됩니다. 3.12 를 설치하세요:
echo          https://www.python.org/downloads/release/python-3120/
echo        ^(설치 시 "Add Python to PATH" 체크. 이미 있는 .venv 폴더는 지우고 다시 실행^)
pause & exit /b 1

:pyok

REM 가상환경 생성
if not exist ".venv\Scripts\activate.bat" (
  echo [1/5] 가상환경(.venv) 생성...
  %PY% -m venv .venv || ( echo [오류] venv 생성 실패 & pause & exit /b 1 )
)

call ".venv\Scripts\activate.bat"

echo [2/5] aist 설치 (방송/공지/플랫폼/LLM)...
python -m pip install -U pip >nul
pip install -e ".[vtuber,obs,discord,platforms,naver,llm]"
if errorlevel 1 ( echo [오류] 설치 실패 & pause & exit /b 1 )
echo     ( chroma 기억 / 셀레늄 / 게임은 필요할 때: pip install -e ".[all]" )

echo [3/5] 설정 파일 준비...
if not exist "config.yaml"  copy "config\config.example.yaml"  "config.yaml"  >nul
if not exist "persona.yaml" copy "config\persona.example.yaml" "persona.yaml" >nul
if not exist ".env"         copy ".env.example"                 ".env"         >nul

echo [4/5] 방송 코어 준비(웹UI + 의존성 + conf.yaml)...
echo     시간이 좀 걸립니다. 새 창이 뜨면 끝날 때까지 두세요.
call "windows\코어준비.bat" <nul

echo [5/5] 설정 점검...
echo.
aist --config config.yaml --persona persona.yaml check

echo.
echo ============================================
echo  설치 끝. 이제 할 일:
echo   1) config.yaml / persona.yaml / .env 를 메모장으로 열어 채우기
echo   2) 방송 코어는 코어실행.bat 로 (Open-LLM-VTuber)
echo   3) 점검.bat -^> 테스트방송.bat -^> 방송시작.bat
echo.
echo  위 [5/5] 점검이 "지금 상태로는 방송이 안 됩니다" 라고 했다면
echo  거기 적힌 것부터 해결해야 합니다.
echo ============================================
pause
