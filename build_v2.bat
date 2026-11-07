@echo off
cd /d "%~dp0"
python -m unittest discover -s tests -v
if errorlevel 1 exit /b 1
python -m PyInstaller --noconfirm PokerHelperV2.spec
if errorlevel 1 pause
