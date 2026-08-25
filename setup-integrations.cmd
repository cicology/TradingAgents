@echo off
REM From repo root OR from integrations\binance-bridge
cd /d "%~dp0"
cd integrations\binance-bridge
call npm run setup
