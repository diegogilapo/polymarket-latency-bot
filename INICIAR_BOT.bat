@echo off
title Polymarket Quantitative Market Maker Bot - LIVE
color 0A
cd /d "%~dp0"
echo ===================================================================
echo   INICIANDO POLYMARKET QUANTITATIVE MARKET MAKER v2.0 (LIVE)
echo ===================================================================
echo.
python main.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo -------------------------------------------------------------------
    echo Ha ocurrido un error o se detuvo el bot.
    echo -------------------------------------------------------------------
)
pause
