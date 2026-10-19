@echo off
chcp 65001 >nul
title 打包 - 天地图 ArcMap 加载工具
echo.
echo ================================================
echo   天地图 ArcMap 加载工具 - PyInstaller 打包脚本
echo ================================================
echo.

REM 检查 Python
where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.8 或更高版本。
    echo        安装时务必勾选 "Add Python to PATH"。
    pause
    exit /b 1
)

echo [1/3] 安装 PyInstaller（若已安装会自动跳过）...
pip install pyinstaller -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 (
    echo [警告] 使用清华镜像安装失败，改用默认源重试...
    pip install pyinstaller
)

echo.
echo [2/3] 开始打包（单文件、无控制台窗口）...

REM 如果目录下存在图标文件，自动作为程序/托盘图标
set ICON_OPT=
if exist "app.ico"  set ICON_OPT=--icon app.ico
if not defined ICON_OPT if exist "icon.ico" set ICON_OPT=--icon icon.ico
if defined ICON_OPT echo       使用图标：%ICON_OPT%

pyinstaller --noconfirm --clean --onefile --windowed %ICON_OPT% ^
    --name "天地图加载工具" ^
    tianditu_gui.py

if errorlevel 1 (
    echo.
    echo [错误] 打包失败，请检查上方日志。
    pause
    exit /b 1
)

echo.
echo [3/3] 打包完成！
echo.
echo   生成的程序：dist\天地图加载工具.exe
echo   本程序无第三方依赖，托盘用 Windows 原生 API 实现，exe 体积较小。
echo   把该 exe 单独拷给他人即可使用（config.json 和 cache 目录会在 exe 旁边自动生成）。
echo.
pause
