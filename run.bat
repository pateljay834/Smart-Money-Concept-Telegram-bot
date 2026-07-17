@echo off
REM Set these once, or better: set them as permanent user environment variables
REM so you don't have to edit this file / risk committing your token.
REM setx TELEGRAM_BOT_TOKEN "your-token-here"
REM setx TELEGRAM_CHAT_ID "your-chat-id-here"

if "%TELEGRAM_BOT_TOKEN%"=="" (
    echo TELEGRAM_BOT_TOKEN is not set. Run: setx TELEGRAM_BOT_TOKEN "your-token"
    pause
    exit /b 1
)

pip install -r requirements.txt
python bot.py
pause
