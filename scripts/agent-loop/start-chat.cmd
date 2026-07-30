@echo off
cd /d "%~dp0\..\.."
python scripts\agent-loop\chat_server.py --open
pause
