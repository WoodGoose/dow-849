@echo off
chcp 65001 > nul
title WX849 Protocol Service Stopper

echo.
echo +------------------------------------------------+
echo ^|         WX849 Protocol Service Stopper         ^|
echo +------------------------------------------------+
echo.

:: 停止PAD服务
echo [1/2] 正在停止PAD服务...
taskkill /f /im linuxService.exe > nul 2>&1
if %errorlevel% equ 0 (
  echo PAD服务已停止
) else (
  echo 未发现运行中的PAD服务进程
)

:: 停止Redis服务
echo [2/2] 正在停止Redis服务...
taskkill /f /im redis-server.exe > nul 2>&1
if %errorlevel% equ 0 (
  echo Redis服务已停止
) else (
  echo 未发现运行中的Redis服务进程
)

echo.
echo 所有WX849服务已停止!
echo +------------------------------------------------+

pause 