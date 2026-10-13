@echo off
cd /d "%~dp0"
set "PY_LAUNCHER=%LocalAppData%\Programs\Python\Launcher\py.exe"
if exist "%PY_LAUNCHER%" (
  "%PY_LAUNCHER%" -3 app.py %*
) else (
  python app.py %*
)
if errorlevel 1 pause
