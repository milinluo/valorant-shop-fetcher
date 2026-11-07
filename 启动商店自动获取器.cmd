@echo off
chcp 65001 >nul
title 无畏契约商店自动获取器
cd /d "%~dp0"

REM 检查 Python 是否可用
python --version >nul 2>nul
if errorlevel 1 (
  echo.
  echo [错误] 未检测到 Python。
  echo 请先安装 Python 并勾选 "Add python.exe to PATH"，
  echo 安装完成后重新运行本脚本。
  echo.
  pause
  exit /b 1
)

REM 探测本地服务状态：退出码 0=运行中且已登录  2=运行中但未登录  1=未运行
python -c "import json,urllib.request,sys;d=json.loads(urllib.request.urlopen('http://localhost:4175/api/status',timeout=2).read().decode('utf-8'));sys.exit(0 if d.get('auth') else 2)" 2>nul
if errorlevel 2 goto relogin
if errorlevel 1 goto launch
echo.
echo 自动获取器已在后台运行且登录正常，无需重复启动。
echo 若网页里仍提示未登录，请关闭本窗口后重新双击本脚本扫码。
timeout /t 3 >nul
exit /b 0

:relogin
echo.
echo 检测到自动获取器在运行但未登录（登录凭证缺失或已失效）。
echo 正在重启服务并重新弹出扫码窗口…
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-NetTCPConnection -LocalPort 4175 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"
timeout /t 2 >nul
goto launch

:launch
python val_shop_fetcher.py
if errorlevel 1 (
  echo.
  echo [错误] 自动获取器启动失败，请将上方报错截图反馈给作者。
  echo.
)
pause
