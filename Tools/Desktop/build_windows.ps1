param([string]$Python = "python")
$ErrorActionPreference = "Stop"
$toolsDirectory = Split-Path -Parent $PSScriptRoot
$buildDirectory = Join-Path $PSScriptRoot "build"
$helperDirectory = Join-Path $buildDirectory "helper/omi-device"
& $Python -m PyInstaller --noconfirm --console --onedir --name omi-device `
    --distpath (Join-Path $buildDirectory "helper") --workpath (Join-Path $buildDirectory "pyinstaller") `
    --specpath $buildDirectory --paths $PSScriptRoot `
    --paths (Join-Path $toolsDirectory "DeviceBridge") --paths (Join-Path $toolsDirectory "CodexMonitor") `
    --copy-metadata pyserial (Join-Path $PSScriptRoot "backend.py")
if ($LASTEXITCODE -ne 0) { throw "Device backend packaging failed" }
Push-Location $PSScriptRoot
try {
    & npm.cmd run tauri -- build --no-bundle
    if ($LASTEXITCODE -ne 0) { throw "Tauri build failed" }
    $releaseDirectory = Join-Path $PSScriptRoot "release/OmiPet"
    New-Item -ItemType Directory -Path $releaseDirectory -Force | Out-Null
    Copy-Item -LiteralPath $helperDirectory -Destination $releaseDirectory -Recurse -Force
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot "src-tauri/target/release/omipet-ui-pilot.exe") `
        -Destination (Join-Path $releaseDirectory "OmiPet.exe") -Force
    Copy-Item -LiteralPath $helperDirectory -Destination (Join-Path $PSScriptRoot "src-tauri/target/release") -Recurse -Force
    foreach ($name in @("README.md", "THIRD_PARTY_NOTICES.md")) {
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Destination $releaseDirectory -Force
    }
    & $Python (Join-Path $PSScriptRoot "collect_licenses.py") --output $releaseDirectory
    if ($LASTEXITCODE -ne 0) { throw "Dependency license collection failed" }
    Compress-Archive -LiteralPath $releaseDirectory -DestinationPath (Join-Path $PSScriptRoot "release/OmiPet-Windows-0.2.0.zip") -Force
    Write-Output $releaseDirectory
} finally {
    Pop-Location
}
