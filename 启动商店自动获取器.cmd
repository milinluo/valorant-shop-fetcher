@echo off
chcp 65001 >nul
title 无畏契约商店自动获取器
cd /d "%~dp0"
curl -s -o NUL -m 2 http://localhost:4175/api/shop
if %errorlevel%==0 (
  echo 自动获取器已在运行，无需重复启动。
  timeout /t 1 >nul
  exit /b
)
python val_shop_fetcher.py
pause