# ─────────────────────────────────────────────
# PhoneSurgeon — Advanced ADB Toolkit Launcher
# PowerShell Edition
# ─────────────────────────────────────────────

$Host.UI.RawUI.WindowTitle = "PhoneSurgeon - Advanced ADB Toolkit"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host ""
Write-Host "    ╔══════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "    ║   PhoneSurgeon - Advanced ADB Toolkit        ║" -ForegroundColor Cyan
Write-Host "    ╚══════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# Check Python
$python = $null
if (Get-Command python -ErrorAction SilentlyContinue) {
    $python = "python"
} elseif (Get-Command python3 -ErrorAction SilentlyContinue) {
    $python = "python3"
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $python = "py"
}

if (-not $python) {
    Write-Host "  [ERROR] Python is not installed!" -ForegroundColor Red
    Write-Host "  Download from: https://www.python.org/downloads/" -ForegroundColor Yellow
    Write-Host ""
    Read-Host "  Press Enter to exit"
    exit 1
}

$ver = & $python --version 2>&1
Write-Host "  [OK] $ver found" -ForegroundColor Green
Write-Host "  [*] Launching PhoneSurgeon..." -ForegroundColor Cyan
Write-Host ""

& $python "$scriptDir\phonesurgeon.py"
