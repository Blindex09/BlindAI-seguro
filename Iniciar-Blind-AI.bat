@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "ELECTRON_RUN_AS_NODE="
if exist "%~dp0node_modules\electron\dist\electron.exe" (
  start "" /D "%~dp0" "%~dp0node_modules\electron\dist\electron.exe" "%~dp0."
  exit /b 0
)
echo Iniciando Blind AI via npm...
call npm start
if errorlevel 1 (
  echo.
  echo Nao foi possivel iniciar o Blind AI. Verifique se o Node.js e as dependencias estao instalados.
  pause
)
