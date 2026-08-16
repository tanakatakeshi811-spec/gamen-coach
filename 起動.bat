@echo off
rem NOTE(for future edits): This file must be saved as Shift_JIS(CP932) with
rem CRLF line endings, NOT UTF-8/LF. cmd.exe's batch parser has a known bug
rem where chcp 65001 (UTF-8 mode) + LF-only line endings can silently
rem corrupt lines containing Japanese text (see voice-input-tool notes).
rem CP932 is the native codepage on Japanese Windows, so no chcp is needed.
rem If you edit this file with a tool that saves as UTF-8, convert it back
rem with (from the project folder, e.g. Git Bash):
rem   iconv -f UTF-8 -t CP932 file.utf8.bat | sed 's/$/\r/' > 起動.bat
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================
echo   画面コーチを起動します
echo ============================================
echo.

rem --- 使えるPythonを探す(python優先、なければpyランチャー) ---
set "PYTHON_CMD="

python --version >nul 2>nul
if not errorlevel 1 set "PYTHON_CMD=python"
if defined PYTHON_CMD goto :python_found

py --version >nul 2>nul
if not errorlevel 1 set "PYTHON_CMD=py"
if defined PYTHON_CMD goto :python_found

goto :python_not_found

:python_not_found
echo [エラー] このパソコンでPythonが見つかりませんでした。
echo.
echo 考えられる原因:
echo   ・Pythonがインストールされていない
echo   ・インストール時に「Add python.exe to PATH」にチェックしていなかった
echo   ・Microsoft Storeの「アプリ実行エイリアス」が邪魔している
echo.
echo 対処方法:
echo   1. 設定 → アプリ → 詳細なアプリ設定 → アプリ実行エイリアス を開き、
echo      「python.exe」「python3.exe」がオンになっていたら一度オフにする
echo   2. それでも直らない場合、Python公式サイトから入れ直す
echo      https://www.python.org/downloads/
echo      インストール画面で「Add python.exe to PATH」に必ずチェック
echo.
echo このウィンドウは閉じずに、上の内容を撮影するか、または山田くんに
echo 伝えてください。
pause
exit /b 1

:python_found
echo 使用するPython: %PYTHON_CMD%
%PYTHON_CMD% --version
echo.

echo 必要なライブラリを確認しています…
%PYTHON_CMD% -m pip show opencv-python >nul 2>nul
if errorlevel 1 goto :install_libs
%PYTHON_CMD% -m pip show mss >nul 2>nul
if errorlevel 1 goto :install_libs
%PYTHON_CMD% -m pip show keyboard >nul 2>nul
if errorlevel 1 goto :install_libs
goto :run_app

:install_libs
echo 必要なライブラリが入っていないようなので、自動でインストールします。
echo 初回のみ数分かかることがあります。ネット接続が必要です
echo.
%PYTHON_CMD% -m pip install -r requirements.txt
if errorlevel 1 goto :install_failed
echo.
goto :run_app

:install_failed
echo.
echo [エラー] ライブラリのインストールに失敗しました。
echo 上に表示されているメッセージを確認するか、
echo 撮影されるか、または山田くんに伝えてください。
pause
exit /b 1

:run_app
echo アプリを起動しています…
echo 使い終わったらアプリのウィンドウを閉じてください
echo.
%PYTHON_CMD% main.py
set "EXITCODE=%errorlevel%"

echo.
if "%EXITCODE%"=="0" goto :normal_exit

echo [エラー] アプリが異常終了しました。終了コード: %EXITCODE%
echo 上に表示されているメッセージを確認するか、
echo 撮影されるか、または山田くんに伝えてください。
goto :end

:normal_exit
echo アプリを終了しました。

:end
pause
