@echo off
title DeepSeek4Free - Claude Code Launcher
chcp 65001 >nul

echo ==========================================
echo   Claude Code + DeepSeek Bridge Launcher
echo ==========================================
echo.

:: Kill any old process on port 8000
echo [1/4] Killing old processes on port 8000...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000 " 2^>nul') do (
    taskkill /PID %%a /F >nul 2>&1
)

:: Start bridge in background (minimized window)
echo [2/4] Starting bridge.py...
start /min "DeepSeek Bridge" python "%~dp0bridge.py"
echo       Waiting for bridge to start...
timeout /t 5 /nobreak >nul

:: Verify bridge is running
echo [3/4] Verifying bridge health...
powershell -Command "try { $r = Invoke-RestMethod -Uri http://localhost:8000/health -TimeoutSec 5; Write-Host '       Bridge is HEALTHY' } catch { Write-Host '       WARNING: Bridge may not be ready yet. Proceeding anyway...' }"

:: Set environment variables for THIS session
echo [4/4] Configuring Claude Code environment...
set ANTHROPIC_BASE_URL=http://localhost:8000
set ANTHROPIC_API_KEY=sk-ant-api03-fakekey-for-bridge-00000000000000000000000000000000000000000000000000000000000000000000
set DISABLE_AUTOUPDATE=1

echo.
echo ==========================================
echo   CONFIGURATION SUMMARY
echo ==========================================
echo.
echo   Bridge URL  : http://localhost:8000
echo   Health      : http://localhost:8000/health
echo   API Docs    : http://localhost:8000/docs
echo   Model       : DeepSeek (free, via cloud)
echo   API Key     : Not needed (fake key set)
echo   Local LLM   : Not needed
echo.
echo   Features:
echo     [+] Deep Think    : ALWAYS ON
echo     [+] Web Search    : ALWAYS ON
echo     [+] All Tools     : ENABLED
echo     [+] Session Pool  : Pre-warmed
echo.
echo ==========================================
echo.

:: Navigate to project folder (pass folder as argument, or use current dir)
if "%1"=="" (
    echo Launching Claude Code in current directory...
    echo   %CD%
) else (
    echo Launching Claude Code in: %1
    cd /d "%1"
)

echo.
echo Type 'exit' or press Ctrl+C to quit Claude Code.
echo ==========================================
echo.

claude
