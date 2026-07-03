<#
.SYNOPSIS
  ImADHD one-line installer (Windows PowerShell).

.DESCRIPTION
  Run inside the cloned repo. Runs `pip install -e .` (deps + package) then
  `python -m imadhd install` which auto-configures all four steps:
    1. pm2 + reboot survival
    2. Telegram command menu (merged, not overwritten)
    3. Claude Code hooks (idempotent, existing hooks preserved)
    4. Telegram pin (created + pinned)

  One-line:
    git clone https://github.com/<owner>/ImADHD.git; cd ImADHD; ./scripts/install.ps1

.PARAMETER Token
  Telegram bot token (@BotFather). If omitted, install prompts or reads .env.

.PARAMETER Chat
  Your Telegram user id (@userinfobot). Required for fail-closed security.

.PARAMETER MaxSlots
  Max terminal slots (default 6).

.PARAMETER SkipPm2
  Skip Step 1 (pm2 already set up).

.PARAMETER SkipPin
  Skip Step 4 (pin creation).
#>
param(
    [string]$Token,
    [string]$Chat,
    [int]$MaxSlots = 6,
    [switch]$SkipPm2,
    [switch]$SkipPin
)

$ErrorActionPreference = 'Stop'

# Repo root = parent of this script (<repo>/scripts/install.ps1)
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Repo = Split-Path -Parent $ScriptDir
if (-not (Test-Path "$Repo\imadhd\cli.py")) {
    Write-Error "Repo root not found (imadhd\cli.py missing). Clone first, then cd ImADHD and re-run."
    exit 1
}
Set-Location $Repo

# Python check — skip the Windows Store stub (WindowsApps\python.exe) and verify.
$py = $null
$paths = @()
$paths += @(where.exe python  2>$null)
$paths += @(where.exe python3 2>$null)
foreach ($c in $paths) {
    $c = "$c".Trim()
    if (-not $c) { continue }
    if ($c -match 'WindowsApps') { continue }   # Store alias stub
    try {
        $null = & $c -c "import sys" 2>&1
        if ($LASTEXITCODE -eq 0) { $py = $c; break }
    } catch { }
}
if (-not $py) {
    Write-Error "Python not found (or only the Windows Store stub). Install real Python from https://python.org and re-run."
    exit 1
}
Write-Host "python: $py" -ForegroundColor Cyan

# Node check (needed for Step 1) - install.py checks in more detail
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Write-Warning "Node.js not found - Step 1 (pm2) will fail. Install from https://nodejs.org then re-run."
}

# Deps + package
Write-Host "pip install -e ." -ForegroundColor Cyan
& $py -m pip install -e .
if ($LASTEXITCODE -ne 0) {
    Write-Error "pip install failed."
    exit 1
}

# Build install args
$instArgs = @('install', '--max-slots', $MaxSlots)
if ($Token)  { $instArgs += @('--token', $Token) }
if ($Chat)   { $instArgs += @('--chat', $Chat) }
if ($SkipPm2) { $instArgs += '--skip-pm2' }
if ($SkipPin) { $instArgs += '--skip-pin' }

Write-Host "python -m imadhd $($instArgs -join ' ')" -ForegroundColor Cyan
& $py -X utf8 -m imadhd.cli @instArgs
exit $LASTEXITCODE
