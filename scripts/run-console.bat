@echo off
rem Ajani konsol penceresinde (loglari gorerek) calistirir. Kurulumdan sonra
rem sorun gidermek icin: once Gorev Zamanlayici'daki "RemoteAgent" gorevini durdurun.
setlocal
set "APP=%ProgramFiles%\RemoteAgent"
set "CFG=%ProgramData%\RemoteAgent"
cd /d "%APP%" || (echo Kurulum bulunamadi: %APP% & pause & exit /b 1)
"%APP%\.venv\Scripts\python.exe" -m remote_agent --config-dir "%CFG%" %*
pause
