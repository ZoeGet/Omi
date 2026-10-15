param([string]$Python = "python", [string]$Name = "OmiPet")
$ErrorActionPreference = "Stop"
if ($Name -notmatch '^[A-Za-z0-9-]+$') { throw "Invalid build name" }
$desktopDirectory = $PSScriptRoot
$toolsDirectory = Split-Path -Parent $desktopDirectory
$licenseData = (Join-Path $desktopDirectory "licenses") + ";licenses"
& $Python -m PyInstaller --noconfirm --windowed --onedir --name $Name `
    --distpath (Join-Path $desktopDirectory "dist") `
    --workpath (Join-Path $desktopDirectory "build") `
    --specpath (Join-Path $desktopDirectory "build") `
    --paths $desktopDirectory `
    --paths (Join-Path $toolsDirectory "DeviceBridge") `
    --paths (Join-Path $toolsDirectory "CodexMonitor") `
    --collect-data customtkinter `
    --copy-metadata customtkinter `
    --copy-metadata darkdetect `
    --copy-metadata pillow `
    --copy-metadata packaging `
    --add-data $licenseData `
    (Join-Path $desktopDirectory "app.py")
if ($LASTEXITCODE -ne 0) { throw "OmiPet packaging failed" }
$outputDirectory = Join-Path (Join-Path $desktopDirectory "dist") $Name
Copy-Item -LiteralPath (Join-Path $desktopDirectory "README.md") -Destination $outputDirectory
Copy-Item -LiteralPath (Join-Path $desktopDirectory "THIRD_PARTY_NOTICES.md") -Destination $outputDirectory
