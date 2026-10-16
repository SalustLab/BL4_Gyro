# Installs or updates Native Gyro Aim in Borderlands 4. Needs oak2-mod-manager (bl-sdk): with -InstallModManager it is
# downloaded from its official GitHub release (pinned v0.3, SHA-256 checked) when it is missing; an existing install
# is never modified. Your gyro settings (sdk_mods\settings\NativeGyro.json) are never touched.
# Works from the release package (NativeGyro\ next to this script) or from the repo (after build.cmd).
# Run: powershell -ExecutionPolicy Bypass -File install.ps1 [-GameDir "<...>\Borderlands 4"] [-InstallModManager]
param([string]$GameDir, [switch]$InstallModManager, [string]$ModManagerZip)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'steam-game-dir.ps1')
if (-not $GameDir) { $GameDir = Find-GameDir }

$OAK2_URL = 'https://github.com/bl-sdk/oak2-mod-manager/releases/download/v0.3/oak2-sdk.zip'
$OAK2_SHA256 = '602675446ABED184169FA158BE3C8BC81777A71203581E4A248ECA8A3D00B5C7'

$packaged = Join-Path $PSScriptRoot 'NativeGyro'
if (Test-Path (Join-Path $packaged 'bl4gyro.dll')) {
    $modDir, $dll = $packaged, (Join-Path $packaged 'bl4gyro.dll')
} else {
    $repo = Split-Path $PSScriptRoot -Parent
    $modDir, $dll = (Join-Path $repo 'mod\NativeGyro'), (Join-Path $repo 'build\release\bl4gyro.dll')
}
$manifest = Join-Path $PSScriptRoot 'oak2-install-manifest.txt'  # release package; the repo keeps it in evidence\
if (-not (Test-Path $manifest)) { $manifest = Join-Path (Split-Path $PSScriptRoot -Parent) 'evidence\B-oak2-install-manifest.txt' }

if (-not (Test-Path (Join-Path $GameDir 'OakGame\Binaries\Win64'))) {
    throw "'$GameDir' is not a Borderlands 4 folder (OakGame\Binaries\Win64 is missing). Choose the folder that contains OakGame."
}
if (Get-Process Borderlands4 -ErrorAction SilentlyContinue) { throw 'Borderlands 4 is running. Close the game first.' }
if (-not (Test-Path $dll)) { throw "Build first (build.cmd): $dll is missing." }
try {
    $probe = Join-Path $GameDir ".nativegyro-write-test-$PID"
    [IO.File]::WriteAllText($probe, '')
    Remove-Item -Force $probe
} catch {
    throw "Cannot write to '$GameDir'. Move the game out of a protected folder or run the installer as administrator."
}

$pyunrealsdk = Join-Path $GameDir 'OakGame\Binaries\Win64\Plugins\pyunrealsdk.dll'
if (-not (Test-Path $pyunrealsdk)) {
    if (-not $InstallModManager) {
        throw "oak2-mod-manager not found in '$GameDir'. Install it first (https://github.com/bl-sdk/oak2-mod-manager/releases) or run with -InstallModManager."
    }
    # Never write over another loader or a partial install: those files may belong to something else.
    $paths = Get-Content $manifest | Where-Object { $_ -and -not $_.StartsWith('#') }
    $existing = @($paths | Where-Object { $_ -notlike 'sdk_mods/settings/*' -and (Test-Path (Join-Path $GameDir $_)) })
    if ($existing.Count) {
        throw "Found part of a mod manager install ($($existing[0]), ...). Not overwriting it: repair it with the official oak2-mod-manager release."
    }
    $tmp = Join-Path ([IO.Path]::GetTempPath()) "nativegyro-oak2-$PID"
    New-Item -ItemType Directory -Force $tmp | Out-Null
    try {
        $zip = Join-Path $tmp 'oak2-sdk.zip'
        if ($ModManagerZip) {
            Copy-Item $ModManagerZip $zip  # tests: a local file instead of the download
        } else {
            Write-Host "Downloading oak2-mod-manager v0.3 from $OAK2_URL"
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            try { Invoke-WebRequest -UseBasicParsing -Uri $OAK2_URL -OutFile $zip }
            catch { throw "Download failed ($($_.Exception.Message)). Check your connection, or install oak2-mod-manager v0.3 by hand." }
        }
        $hash = (Get-FileHash -Algorithm SHA256 $zip).Hash
        if ($hash -ne $OAK2_SHA256) { throw "The downloaded oak2-mod-manager does not match the expected v0.3 file (SHA-256 $hash). Nothing was installed." }
        Expand-Archive $zip (Join-Path $tmp 'x')
        Copy-Item (Join-Path $tmp 'x\*') $GameDir -Recurse
        Write-Host 'Installed oak2-mod-manager v0.3.'
    } finally {
        Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
    }
} else {
    $toml = Join-Path $GameDir 'OakGame\Binaries\Win64\Plugins\unrealsdk.toml'
    $version = if (Test-Path $toml) { [regex]::Match("$(Get-Content -Raw $toml)", 'display_version\s*=\s*"([^"]+)"').Groups[1].Value }
    if ($version -and $version -notlike '0.3*') { Write-Warning "oak2-mod-manager $version found; Native Gyro was tested with 0.3." }
}

$target = Join-Path $GameDir 'sdk_mods\NativeGyro'
$update = Test-Path (Join-Path $target '__init__.py')
New-Item -ItemType Directory -Force $target | Out-Null
Copy-Item (Join-Path $modDir '*.py') $target -Force
Copy-Item $dll, (Join-Path (Split-Path $dll) 'SDL3.dll') $target -Force

# The Phase B probe binds keys that move the camera; it is a development tool only.
$probeMod = Join-Path $GameDir 'sdk_mods\NativeGyroProbe'
if (Test-Path $probeMod) { Remove-Item -Recurse -Force $probeMod; Write-Host 'Removed development probe (NativeGyroProbe).' }

Write-Host "$(if ($update) { 'Updated' } else { 'Installed' }) Native Gyro in $target (your settings are kept)."
Write-Host 'Start the game: gyro is on. Hold L3 + R3 (or press F8) to open the gyro panel.'
