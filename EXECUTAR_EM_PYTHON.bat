@echo off
setlocal
cd /d "%~dp0"
title PROCESSO 3 - CALCULADORAS DE COEFICIENTES
set "P3_PYTHON="
if exist ".venv\Scripts\python.exe" (
    set P3_PYTHON=".venv\Scripts\python.exe"
    goto :check_python
)
where py >nul 2>&1
if not errorlevel 1 set "P3_PYTHON=py -3"
if defined P3_PYTHON goto :check_python
where python >nul 2>&1
if not errorlevel 1 set "P3_PYTHON=python"
if not defined P3_PYTHON goto :missing

:check_python
%P3_PYTHON% -c "import sys,tkinter;sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
if errorlevel 1 goto :missing
%P3_PYTHON% -c "import dependencias_runtime,openpyxl,et_xmlfile" >nul 2>&1
if errorlevel 1 goto :dependencies_error
%P3_PYTHON% processo3.pyw
if errorlevel 1 goto :failure
exit /b 0

:missing
echo.
echo E necessario Python 3.10 ou superior, com Tcl/Tk instalado.
echo Se a pasta .venv veio de outro computador, remova somente essa pasta e tente novamente.
echo Instale o Python pelo site https://www.python.org/downloads/windows/
echo Na instalacao, mantenha Tcl/Tk e marque Add Python to PATH.
pause
exit /b 1

:dependencies_error
echo.
echo Nao foi possivel carregar as bibliotecas de Excel incluidas no pacote.
echo Extraia todo o ZIP, incluindo a pasta dependencias, e mantenha os arquivos juntos.
echo Nao e necessario instalar openpyxl nem ter internet para usar este pacote.
pause
exit /b 1

:failure
echo.
echo O programa nao conseguiu iniciar. Confira a mensagem acima.
echo Extraia todo o ZIP para uma pasta gravavel; nao execute dentro do ZIP.
pause
exit /b 1
