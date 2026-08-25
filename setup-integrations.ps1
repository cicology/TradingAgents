# Run from the TradingAgents repo root.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
git submodule update --init --recursive
Set-Location (Join-Path $root "integrations\binance-bridge")
npm run setup
Write-Host "Done. From trading_desk: python -m trading_desk binance ping"
