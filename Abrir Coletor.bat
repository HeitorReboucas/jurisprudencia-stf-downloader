@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "ENDERECO=http://127.0.0.1:8000"
if "%~1"=="esperar" goto esperar

title Coletor de Jurisprudência do STF
if not exist ".venv\Scripts\python.exe" goto nao_instalado

rem Se o programa já estiver aberto, só mostra a página de novo.
curl -s -f -o nul "%ENDERECO%/api/health" && goto abrir_pagina

echo.
echo  Abrindo o Coletor de Jurisprudência do STF...
echo  Deixe esta janela aberta enquanto usar o programa. Para encerrar, feche esta janela.
echo.
rem Esta mesma janela abre o navegador assim que o programa responder.
start "" /b cmd /c ""%~f0" esperar"
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level warning

echo.
echo  O programa foi encerrado. Se apareceu um erro acima, a porta 8000 pode estar
echo  em uso por outro programa: feche-o e abra este arquivo de novo.
echo.
pause
exit /b 1

:esperar
for /l %%i in (1,1,60) do (
    timeout /t 1 /nobreak >nul
    curl -s -f -o nul "%ENDERECO%/api/health" && goto abrir_pagina
)
exit /b 1

:abrir_pagina
start "" "%ENDERECO%"
echo  Programa aberto no navegador: %ENDERECO%
exit /b 0

:nao_instalado
echo.
echo  O programa ainda não foi instalado.
echo  Dê dois cliques em "Instalar.bat" primeiro e depois abra este arquivo de novo.
echo.
pause
exit /b 1
