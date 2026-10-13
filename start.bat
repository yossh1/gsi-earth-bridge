@echo off
cd /d "%~dp0"
if exist "%~dp0gsi-earth-overlay.exe" goto run_executable
set "PY_LAUNCHER=%LocalAppData%\Programs\Python\Launcher\py.exe"
if exist "%PY_LAUNCHER%" (
  "%PY_LAUNCHER%" -3 app.py %*
) else (
  python app.py %*
)
if errorlevel 1 pause
exit /b %errorlevel%

:run_executable
"%~dp0gsi-earth-overlay.exe" %*
exit /b %errorlevel%
