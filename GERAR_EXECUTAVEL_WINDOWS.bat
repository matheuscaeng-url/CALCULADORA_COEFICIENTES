@echo off
setlocal
cd /d "%~dp0"
title GERAR PROCESSO 3 PARA WINDOWS
set "P3_BUILD_PYTHON="
where py >nul 2>&1
if not errorlevel 1 set "P3_BUILD_PYTHON=py -3"
if defined P3_BUILD_PYTHON goto :prepare
where python >nul 2>&1
if not errorlevel 1 set "P3_BUILD_PYTHON=python"
if not defined P3_BUILD_PYTHON goto :failure

:prepare
%P3_BUILD_PYTHON% -c "import sys,tkinter;sys.exit(0 if sys.version_info >= (3,10) else 1)"
if errorlevel 1 goto :failure
if exist ".venv-build\Scripts\python.exe" goto :install
%P3_BUILD_PYTHON% -m venv .venv-build
if errorlevel 1 goto :failure

:install
".venv-build\Scripts\python.exe" -m pip install -r requirements.txt "pyinstaller>=6,<7"
if errorlevel 1 goto :failure
".venv-build\Scripts\python.exe" -m PyInstaller --noconfirm --clean --windowed --onedir --name Processo_3_Coeficientes --paths "dependencias" --hidden-import openpyxl --hidden-import et_xmlfile --add-data "data;data" --add-data "dependencias;dependencias" processo3.pyw
if errorlevel 1 goto :failure
echo.
echo Pronto: dist\Processo_3_Coeficientes\Processo_3_Coeficientes.exe
echo Copie a pasta inteira dist\Processo_3_Coeficientes para o computador de destino.
echo Essa versao inclui Python e as bibliotecas.
pause
exit /b 0

:failure
echo.
echo Nao foi possivel gerar o executavel. Confira as mensagens acima.
echo E necessario Python 3.10 ou superior, Tcl/Tk e internet para instalar as ferramentas.
pause
exit /b 1
