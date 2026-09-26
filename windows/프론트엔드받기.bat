@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0.."

REM ============================================================
REM  코어 웹UI(프론트엔드) 받기
REM  frontend\ 는 컴파일 산출물(wasm/onnx ~44MB)이라 저장소에 없다.
REM  이걸 안 받으면 코어가 떠도 화면이 안 나온다.
REM
REM  받는 방법을 두 가지 준비한다:
REM    1) curl + tar  — 윈도우 10 1803 이상에만 있다
REM    2) PowerShell  — 윈도우 7 이상 어디에나 있다 (zip 으로 받는다)
REM  (리눅스/맥은 scripts/fetch_frontend.sh 와 같은 일을 한다)
REM ============================================================

set "DEST=Open-LLM-VTuber\frontend"
set "REPO=Open-LLM-VTuber/Open-LLM-VTuber-Web"
REM codeload 가 막힌 망(사내 프록시 등)이 있어 github.com 경유도 시도한다.
set "URL1=https://codeload.github.com/%REPO%/tar.gz/refs/heads/build"
set "URL2=https://github.com/%REPO%/archive/refs/heads/build.tar.gz"
set "ZIPURL=https://github.com/%REPO%/archive/refs/heads/build.zip"

if exist "%DEST%\index.html" (
  echo 이미 받아져 있습니다: %DEST%\index.html
  echo 다시 받으려면 %DEST% 안의 파일을 지우고 실행하세요.
  goto patch_only
)

set "TMP_DIR=%TEMP%\aist_frontend"
if exist "%TMP_DIR%" rmdir /s /q "%TMP_DIR%"
mkdir "%TMP_DIR%"
if not exist "%DEST%" mkdir "%DEST%"

REM ---------- 1) curl + tar ----------
where curl >nul 2>nul && where tar >nul 2>nul && goto try_curl
echo curl/tar 이 없습니다. PowerShell 로 받습니다.
goto try_powershell

:try_curl
echo ==^> 다운로드 ^(curl^)...
curl -fsSL --max-time 300 -o "%TMP_DIR%\web.tar.gz" "%URL1%"
if errorlevel 1 (
  echo     다른 주소로 다시 시도합니다.
  curl -fsSL --max-time 300 -o "%TMP_DIR%\web.tar.gz" "%URL2%"
)
if errorlevel 1 (
  echo     curl 로는 못 받았습니다. PowerShell 로 다시 시도합니다.
  goto try_powershell
)

echo ==^> 압축 해제 ^(tar^)...
tar -xzf "%TMP_DIR%\web.tar.gz" -C "%TMP_DIR%"
if errorlevel 1 goto try_powershell
goto place

REM ---------- 2) PowerShell (zip) ----------
:try_powershell
echo ==^> 다운로드 ^(PowerShell^)...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop';" ^
  "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12;" ^
  "Invoke-WebRequest -Uri '%ZIPURL%' -OutFile '%TMP_DIR%\web.zip' -UseBasicParsing;" ^
  "Expand-Archive -Path '%TMP_DIR%\web.zip' -DestinationPath '%TMP_DIR%' -Force"
if errorlevel 1 goto failed

:place
echo ==^> 파일 배치...
for /d %%D in ("%TMP_DIR%\Open-LLM-VTuber-Web-*") do (
  xcopy /E /I /Y /Q "%%D\*" "%DEST%\" >nul
)
rmdir /s /q "%TMP_DIR%" 2>nul

if not exist "%DEST%\index.html" goto failed

REM 웹UI 가 /proxy-ws 에 붙게 한다. 안 하면 웹UI 는 /client-ws 로 붙는데,
REM 그 경로는 채팅을 넣은 쪽에만 결과를 돌려줘서 화면에 아무것도 안 나온다.
:patch_only
REM 받는 건 건너뛰어도 설정은 다시 넣는다. 예전 버전으로 넣어둔 설정에는
REM 매니저 귓속말이 화면에 뜨지 않게 하는 필터가 없다.
set PATCH_FAILED=0
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m aist.frontend_patch "%DEST%"
  if errorlevel 1 set PATCH_FAILED=1
) else (
  echo     [건너뜀] .venv 가 없어 웹UI 주소 설정을 못 넣었습니다.
  echo            설치.bat 를 먼저 실행한 뒤 이 파일을 다시 실행하세요.
)
if "%PATCH_FAILED%"=="1" (
  echo.
  echo     [경고] 웹UI 주소 설정을 못 넣었습니다.
  echo            이대로 두면 웹UI 가 /client-ws 로 붙어서, AI 가 말을 해도
  echo            OBS 화면에는 아무것도 안 나옵니다 ^(무음 방송^).
  echo            웹UI 설정 화면에서 WebSocket URL 을 /proxy-ws 로 바꾸세요.
  echo            점검.bat 의 '웹UI 접속경로' 항목으로 확인할 수 있습니다.
  echo.
)
echo ==^> 완료. %DEST% 에 index.html 이 들어왔습니다.
pause & exit /b 0

:failed
rmdir /s /q "%TMP_DIR%" 2>nul
echo.
echo [오류] 프론트엔드를 받지 못했습니다. ^(네트워크/프록시/방화벽 차단일 수 있습니다^)
echo.
echo   이걸 안 받으면 코어가 떠도 화면이 안 나옵니다. 손으로 받으려면:
echo.
echo     1^) 브라우저로 https://github.com/%REPO%/tree/build 접속
echo     2^) Code - Download ZIP 으로 내려받기
echo     3^) 압축을 풀어 안의 내용물^(index.html, assets, libs ...^)을
echo        %DEST%\ 에 그대로 복사
echo.
echo   받은 뒤 확인:  점검.bat   ^('코어 웹UI : OK' 가 떠야 합니다^)
echo.
pause & exit /b 1
