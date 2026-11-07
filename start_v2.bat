@echo off
cd /d "%~dp0"
if exist "dist\PokerHelperV2\PokerHelperV2.exe" (
    start "" "dist\PokerHelperV2\PokerHelperV2.exe"
) else (
    python main_hud.py
    if errorlevel 1 pause
)
