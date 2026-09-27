@echo off
cd /d "%~dp0..\.."
powershell -ExecutionPolicy Bypass -File "scripts\start\start-all.ps1" %*
pause
