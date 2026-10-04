@echo off
setlocal
title Brutal OP25 - Windows + WSL
set "taskMode="
if /i "%~1"=="--check" set "taskMode=-CheckOnly"
if /i "%~1"=="--prepare-only" set "taskMode=-PrepareOnly"
if /i "%~1"=="--update-image" set "taskMode=-UpdateImage"
if /i "%~1"=="--rollback-image" set "taskMode=-RollbackImage"
if /i "%~1"=="--backup" set "taskMode=-BackupProfiles"
if /i "%~1"=="--restore" goto restore
if not "%~1"=="" if not defined taskMode (
    echo Unknown option: %~1
    exit /b 2
)
rem Windows PowerShell is built into Windows. Bypass applies only to this
rem process; the user's machine-wide execution policy is not changed.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install\install-brutal-wsl.ps1" %taskMode%
set "taskExit=%ERRORLEVEL%"
if defined taskMode exit /b %taskExit%
pause
exit /b %taskExit%
:restore
if "%~2"=="" (
    echo Supply the full path to a Brutal OP25 backup ZIP.
    exit /b 2
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install\install-brutal-wsl.ps1" -RestoreProfilesPath "%~2"
exit /b %ERRORLEVEL%
