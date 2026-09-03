@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0.."

REM ============================================================
REM  방송 코어(Open-LLM-VTuber) 준비 — 한 번만 하면 됩니다.
REM   1) 웹UI(화면)  2) 코어 의존성  3) conf.yaml(한국어 설정)
REM  (리눅스/맥의 scripts/setup_openllm_vtuber.sh 와 같은 일)
REM ============================================================

if not exist "Open-LLM-VTuber" (
  echo [오류] Open-LLM-VTuber 폴더가 없습니다. 저장소를 다시 받으세요.
  pause & exit /b 1
)

echo [1/3] 웹UI(화면) 확인...
if exist "Open-LLM-VTuber\frontend\index.html" (
  echo     이미 받아져 있음
) else (
  call "windows\프론트엔드받기.bat" <nul
  if not exist "Open-LLM-VTuber\frontend\index.html" (
    echo     [경고] 웹UI 를 못 받았습니다. 위 안내대로 손으로 받은 뒤 다시 실행하세요.
  )
)

echo.
echo [2/3] 코어 의존성 설치...
pushd "Open-LLM-VTuber"
where uv >nul 2>nul
if %errorlevel%==0 (
  echo     uv 로 설치합니다 ^(권장^)...
  uv sync
  if errorlevel 1 echo     [경고] uv sync 실패 — 아래 pip 방식으로 다시 시도해보세요.
) else (
  echo     uv 가 없습니다. pip 으로 설치합니다.
  echo     ^(권장: https://docs.astral.sh/uv/ 설치 후 이 파일을 다시 실행^)
  if exist "..\.venv\Scripts\activate.bat" call "..\.venv\Scripts\activate.bat"
  python -m pip install -U pip >nul
  pip install -r requirements.txt
  if errorlevel 1 (
    echo     [오류] 코어 의존성 설치 실패.
    echo            파이썬 3.10~3.12 인지 확인하고, 오류 메시지를 그대로 보고하세요.
    popd & pause & exit /b 1
  )
)
popd

echo.
echo [3/3] 코어 설정 conf.yaml 준비...
if exist "Open-LLM-VTuber\conf.yaml" (
  echo     이미 있음 ^(덮어쓰지 않음^)
) else (
  if exist "Open-LLM-VTuber\conf.korean.yaml" (
    copy "Open-LLM-VTuber\conf.korean.yaml" "Open-LLM-VTuber\conf.yaml" >nul
    echo     conf.korean.yaml -^> conf.yaml 적용 ^(한국어/페르소나^)
  ) else (
    echo     [경고] conf.korean.yaml 이 없습니다. 저장소를 확인하세요.
  )
)

echo.
echo ============================================
echo  코어 준비 끝. 이제 점검.bat 을 실행해서
echo  '코어 웹UI / conf.yaml / 코어 의존성' 이 모두 OK 인지 보세요.
echo ============================================
pause
