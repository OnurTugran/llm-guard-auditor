@echo off
chcp 65001 >nul
title OWASP LLM Guvenlik Denetim Araci
cd /d "%~dp0"

python -c "import customtkinter, httpx, pydantic, litellm" 2>nul
if %errorlevel% neq 0 (
    echo [Bilgi] Gerekli kutuphaneler kontrol ediliyor ve yukleniyor...
    pip install -r requirements.txt
)

start "" pythonw launcher.py
exit
