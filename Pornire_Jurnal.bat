@echo off
title Jurnal Trading Kraken
cd /d "%~dp0"
call .venv\Scripts\activate
streamlit run app.py
pause