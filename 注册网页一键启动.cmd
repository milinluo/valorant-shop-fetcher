@echo off
chcp 65001 >nul
title 注册网页一键启动
cd /d "%~dp0"
reg add "HKCU\Software\Classes\valstarts" /ve /t REG_SZ /d "URL:valstarts Protocol" /f >nul
reg add "HKCU\Software\Classes\valstarts\shell\open\command" /ve /t REG_SZ /d "\"%~dp0启动商店自动获取器.cmd\" \"%%1\"" /f
echo.
echo 注册完成！现在在网页里点「自动获取今日商店」时，
echo 浏览器会弹出确认窗口，点「打开」即可自动启动自动获取器。
echo.
pause