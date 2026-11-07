@echo off
chcp 65001 >nul
title 注册网页一键启动
cd /d "%~dp0"
reg add "HKCU\Software\Classes\valstarts" /ve /t REG_SZ /d "URL:valstarts Protocol" /f >nul
reg add "HKCU\Software\Classes\valstarts" /v "URL Protocol" /t REG_SZ /d "" /f >nul
reg add "HKCU\Software\Classes\valstarts\shell\open\command" /ve /t REG_SZ /d "C:\Windows\System32\wscript.exe \"%~dp0启动后台.vbs\"" /f
echo.
echo 注册完成！现在在网页里点「自动获取今日商店」时，
echo 自动获取器会在后台静默启动，不会弹出窗口。
echo.
pause
