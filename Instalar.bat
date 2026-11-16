@echo off
chcp 65001 >nul
title Instalar o Coletor de Jurisprudência do STF
cd /d "%~dp0"

echo.
echo  Instalando o Coletor de Jurisprudência do STF.
echo  Isso só precisa ser feito uma vez e pode levar alguns minutos.
echo.

rem O instalador do Python coloca o "py" aqui; a janela atual ainda não conhece o novo PATH.
set "PATH=%PATH%;%LOCALAPPDATA%\Programs\Python\Launcher"

where py >nul 2>nul
if not errorlevel 1 goto verificar_versao

echo  [1/3] O Python não foi encontrado. Instalando o Python 3.12...
winget install --exact --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
where py >nul 2>nul
if errorlevel 1 goto sem_python

:verificar_versao
py -3 -c "import sys; sys.exit(sys.version_info < (3, 12))" >nul 2>nul
if errorlevel 1 goto python_antigo
echo  [1/3] Python encontrado.

echo  [2/3] Preparando a pasta do programa...
if not exist ".venv\Scripts\python.exe" py -3 -m venv .venv
if not exist ".venv\Scripts\python.exe" goto erro

echo  [3/3] Baixando os componentes do programa...
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet --disable-pip-version-check
if errorlevel 1 goto erro
".venv\Scripts\python.exe" -m pip install -r requirements.txt --quiet --disable-pip-version-check
if errorlevel 1 goto erro

echo.
echo  Pronto! Agora dê dois cliques em "Abrir Coletor.bat" para usar o programa.
echo.
pause
exit /b 0

:sem_python
echo.
echo  Não foi possível instalar o Python automaticamente.
echo  Instale o Python 3.12 ou mais recente pelo site https://www.python.org/downloads/
echo  (marque a opção "Add python.exe to PATH") e rode este arquivo de novo.
echo.
pause
exit /b 1

:python_antigo
echo.
echo  O Python instalado é antigo. Este programa precisa da versão 3.12 ou mais recente.
echo  Instale uma versão nova pelo site https://www.python.org/downloads/ e rode este arquivo de novo.
echo.
pause
exit /b 1

:erro
echo.
echo  A instalação não terminou. Confira se o computador está conectado à internet
echo  e rode este arquivo de novo. Se o erro continuar, apague a pasta ".venv" e tente outra vez.
echo.
pause
exit /b 1
