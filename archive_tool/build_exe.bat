@echo off
REM Simple wrapper to run the PowerShell build script
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_exe.ps1" %*
