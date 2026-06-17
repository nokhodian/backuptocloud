@echo off
echo Building BackupSystem.exe...
pyinstaller BackupSystem.spec --clean
echo.
echo Done. Find BackupSystem.exe in dist\
pause
