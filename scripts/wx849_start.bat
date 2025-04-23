@echo off
chcp 65001 > nul
title WX849 Protocol Service Starter

echo.
echo +------------------------------------------------+
echo ^|         WX849 Protocol Service Starter         ^|
echo +------------------------------------------------+
echo.

:: 设置路径
set SCRIPT_DIR=%~dp0
set PROJECT_ROOT=%SCRIPT_DIR%..
set PROJECT_ROOT=%PROJECT_ROOT:"=%

:: 第一步：启动Redis服务
echo [1/3] 正在启动Redis服务...
cd /d "%PROJECT_ROOT%\lib\wx849\849\redis"
start "" redis-server.exe redis.conf
echo Redis服务已启动
timeout /t 2 > nul

:: 第二步：启动PAD服务
echo [2/3] 正在启动 PAD 服务...

:: 读取配置文件中的协议版本（简化版，实际需要更复杂的解析）
set PROTOCOL_VERSION=849
for /f "tokens=2 delims=:, " %%a in ('findstr "wx849_protocol_version" "%PROJECT_ROOT%\config.json"') do (
  set PROTOCOL_VERSION=%%~a
  set PROTOCOL_VERSION=!PROTOCOL_VERSION:"=!
)

echo 使用协议版本: %PROTOCOL_VERSION%

:: 根据协议版本选择不同的PAD目录
if "%PROTOCOL_VERSION%"=="855" (
  set PAD_DIR="%PROJECT_ROOT%\lib\wx849\849\pad2"
  echo 使用855协议 (pad2)
) else if "%PROTOCOL_VERSION%"=="ipad" (
  set PAD_DIR="%PROJECT_ROOT%\lib\wx849\849\pad3"
  echo 使用iPad协议 (pad3)
) else (
  set PAD_DIR="%PROJECT_ROOT%\lib\wx849\849\pad"
  echo 使用849协议 (pad)
)

:: 检查PAD目录是否存在
if not exist %PAD_DIR% (
  echo PAD目录 %PAD_DIR% 不存在!
  echo 正在关闭Redis服务...
  taskkill /f /im redis-server.exe > nul 2>&1
  goto end
)

:: 启动PAD服务
cd /d %PAD_DIR%
if exist linuxService.exe (
  start "" linuxService.exe
  echo PAD服务已启动
) else (
  echo 找不到PAD服务可执行文件!
  echo 正在关闭Redis服务...
  taskkill /f /im redis-server.exe > nul 2>&1
  goto end
)

timeout /t 3 > nul

:: 第三步：配置并启动主程序
echo [3/3] 配置完成，请扫描二维码登录微信...
echo WX849 协议服务已全部启动!
echo.
echo 现在可以运行主程序，请确保在配置文件中设置:
echo   "channel_type": "wx849",
echo   "wx849_protocol_version": "%PROTOCOL_VERSION%",
echo   "wx849_api_host": "127.0.0.1",
echo   "wx849_api_port": "9000"
echo.
echo 提示: 如需停止WX849服务，请关闭本窗口后运行 wx849_stop.bat 脚本
echo +------------------------------------------------+

:end
pause 