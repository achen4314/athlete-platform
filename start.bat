@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
setlocal enabledelayedexpansion

echo.
echo   ╔══════════════════════════════════════════╗
echo   ║   🏃  运动员数据分析平台  ║
echo   ║      运动员数据分析平台                   ║
echo   ╚══════════════════════════════════════════╝
echo.

:: ============================================================
::  步骤 1 — 检查 Python
:: ============================================================
echo [1/3] 检查环境...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 Python，请先安装 Python 3.10+
    echo.
    pause
    exit /b 1
)
echo        Python 已就绪

:: ============================================================
::  步骤 2 — 安装依赖（静默）
:: ============================================================
echo [2/3] 安装依赖...
pip install flask flask-sqlalchemy requests werkzeug openai python-dotenv numpy scipy opencv-python mediapipe -q 2>nul
if %errorlevel% gtr 1 (
    echo [警告] 部分依赖安装失败，尝试继续...
)
echo        依赖已就绪

:: ============================================================
::  步骤 3 — 关闭旧进程
:: ============================================================
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5000" 2^>nul') do (
    taskkill /F /PID %%a >nul 2>&1
)
echo        端口 5000 已释放

:: ============================================================
::  步骤 4 — 启动服务器
:: ============================================================
echo [3/3] 启动服务器...

:: 使用 start /b 在同一个窗口中后台运行
start "AthleteServer" /B python app.py >nul 2>&1

:: 等待端口就绪
echo        等待服务启动...
set COUNT=0
:wait_loop
timeout /t 1 /nobreak >nul
set /a COUNT+=1

:: 使用 powershell 检测端口（兼容性更好）
powershell -Command "try { $c=New-Object Net.Sockets.TcpClient; $c.Connect('127.0.0.1',5000); $c.Close(); exit 0 } catch { exit 1 }" >nul 2>&1
if !errorlevel! equ 0 goto server_ready

if !COUNT! geq 30 (
    echo [错误] 服务器启动超时
    echo        请手动运行 python app.py 查看错误信息
    pause
    exit /b 1
)
goto wait_loop

:server_ready
echo        服务器已就绪 ✓

:: ============================================================
::  步骤 5 — 打开浏览器
:: ============================================================
echo.
echo   正在打开浏览器...
start http://localhost:5000/login

echo.
echo   ┌─────────────────────────────────────────┐
echo   │   🏃 平台已启动                          │
echo   │   🔗 地址: http://localhost:5000         │
echo   │   👤 账户: admin / admin123              │
echo   │                                         │
echo   │   按任意键停止服务器并退出                │
echo   └─────────────────────────────────────────┘
echo.

pause >nul

:: ============================================================
::  清理：停止服务器
:: ============================================================
echo.
echo   正在停止服务器...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5000" 2^>nul') do (
    taskkill /F /PID %%a >nul 2>&1
)
echo   服务器已停止。
echo.
exit /b 0
