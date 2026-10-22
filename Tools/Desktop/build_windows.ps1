param([string]$Python = "python", [string]$MbedTlsSource = "")
$ErrorActionPreference = "Stop"
$toolsDirectory = Split-Path -Parent $PSScriptRoot
$buildDirectory = Join-Path $PSScriptRoot "build"
$helperDirectory = Join-Path $buildDirectory "helper/omi-device"
$cryptoArguments = @()
if ($MbedTlsSource) { $cryptoArguments = @("--source", $MbedTlsSource) }
& $Python (Join-Path $toolsDirectory "DeviceBridge/native/build_windows.py") @cryptoArguments
if ($LASTEXITCODE -ne 0) { throw "Pairing crypto build failed" }
& $Python -m PyInstaller --noconfirm --console --onedir --name omi-device `
    --distpath (Join-Path $buildDirectory "helper") --workpath (Join-Path $buildDirectory "pyinstaller") `
    --specpath $buildDirectory --paths $PSScriptRoot `
    --paths (Join-Path $toolsDirectory "DeviceBridge") --paths (Join-Path $toolsDirectory "CodexMonitor") `
    --add-binary "$(Join-Path $buildDirectory 'crypto/omi_pake.dll');." `
    --copy-metadata websocket-client --copy-metadata pyserial (Join-Path $PSScriptRoot "backend.py")
if ($LASTEXITCODE -ne 0) { throw "Device backend packaging failed" }
Push-Location $PSScriptRoot
try {
    & npm.cmd run tauri -- build --no-bundle
    if ($LASTEXITCODE -ne 0) { throw "Tauri build failed" }
    $releaseDirectory = Join-Path $PSScriptRoot "release/Omi"
    New-Item -ItemType Directory -Path $releaseDirectory -Force | Out-Null
    Copy-Item -LiteralPath $helperDirectory -Destination $releaseDirectory -Recurse -Force
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot "src-tauri/target/release/omipet-ui-pilot.exe") `
        -Destination (Join-Path $releaseDirectory "Omi.exe") -Force
    $legacyExecutable = Join-Path $releaseDirectory "OmiPet.exe"
    if (Test-Path -LiteralPath $legacyExecutable) { Remove-Item -LiteralPath $legacyExecutable -Force }
    Copy-Item -LiteralPath $helperDirectory -Destination (Join-Path $PSScriptRoot "src-tauri/target/release") -Recurse -Force
    foreach ($name in @("QUICK_START.md", "README.md", "RELEASE_NOTES_V1.0.1.md", "RELEASE_NOTES_V1.0.md", "THIRD_PARTY_NOTICES.md")) {
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Destination $releaseDirectory -Force
    }
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot "src-tauri/icons/README.md") -Destination (Join-Path $releaseDirectory "APP_ICON_SOURCE.md") -Force
    Copy-Item -LiteralPath (Join-Path $toolsDirectory "../LICENSE") -Destination (Join-Path $releaseDirectory "LICENSE.txt") -Force
    $sourceCommit = & git -C $toolsDirectory rev-parse HEAD
    if ($LASTEXITCODE -ne 0) { throw "Cannot identify source commit" }
    $sourceChanges = & git -C $toolsDirectory status --porcelain --untracked-files=normal
    if ($LASTEXITCODE -ne 0) { throw "Cannot inspect source worktree" }
    @(
        "Repository: https://github.com/ZoeGet/Omi"
        "Baseline commit: $sourceCommit"
        "Baseline source: https://github.com/ZoeGet/Omi/tree/$sourceCommit"
        "Working tree modified: $([bool]$sourceChanges)"
        "A modified worktree requires additional source changes to reproduce this package."
    ) | Set-Content -LiteralPath (Join-Path $releaseDirectory "SOURCE_VERSION.txt") -Encoding UTF8
    & $Python (Join-Path $PSScriptRoot "collect_licenses.py") --output $releaseDirectory
    if ($LASTEXITCODE -ne 0) { throw "Dependency license collection failed" }
    Compress-Archive -LiteralPath $releaseDirectory -DestinationPath (Join-Path $PSScriptRoot "release/Omi-Windows-1.0.1.zip") -Force
    Write-Output $releaseDirectory
} finally {
    Pop-Location
}
