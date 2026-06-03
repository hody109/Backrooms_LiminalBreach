@echo off
setlocal
cd /d "%~dp0"

set "CODEX_PY=C:\Users\a.hodan\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if exist "%CODEX_PY%" (
  "%CODEX_PY%" "%~dp0backrooms_liminal_breach.py"
  exit /b %ERRORLEVEL%
)

where py >nul 2>nul
if not errorlevel 1 (
  py -3 "%~dp0backrooms_liminal_breach.py"
  exit /b %ERRORLEVEL%
)

where python >nul 2>nul
if not errorlevel 1 (
  python "%~dp0backrooms_liminal_breach.py"
  exit /b %ERRORLEVEL%
)

echo Python was not found. Install Python 3.12+ or run this from Codex where the bundled runtime exists.
pause
