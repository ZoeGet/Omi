param([string]$Python = "python", [string]$Name = "OmiPet")
$ErrorActionPreference = "Stop"
if ($Name -notmatch '^[A-Za-z0-9-]+$') { throw "Invalid build name" }
$desktopDirectory = $PSScriptRoot
$toolsDirectory = Split-Path -Parent $desktopDirectory
& $Python -m PyInstaller --noconfirm --windowed --onedir --name $Name `
    --distpath (Join-Path $desktopDirectory "dist") `
    --workpath (Join-Path $desktopDirectory "build") `
    --specpath (Join-Path $desktopDirectory "build") `
    --paths $desktopDirectory `
    --paths (Join-Path $toolsDirectory "DeviceBridge") `
    --paths (Join-Path $toolsDirectory "CodexMonitor") `
    (Join-Path $desktopDirectory "app.py")
if ($LASTEXITCODE -ne 0) { throw "OmiPet packaging failed" }
