# Installs Native Gyro Aim into Borderlands 4. Requires oak2-mod-manager (bl-sdk) already installed.
# Run: powershell -ExecutionPolicy Bypass -File scripts\install.ps1 [-GameDir "<...>\Borderlands 4"]
param([string]$GameDir = 'F:\SteamLibrary\steamapps\common\Borderlands 4')
$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
$dll = Join-Path $repo 'build\release\bl4gyro.dll'

if (Get-Process Borderlands4 -ErrorAction SilentlyContinue) { throw 'Close Borderlands 4 first.' }
if (-not (Test-Path (Join-Path $GameDir 'OakGame\Binaries\Win64\Plugins\pyunrealsdk.dll'))) {
    throw "oak2-mod-manager not found in '$GameDir'. Install it first: https://github.com/bl-sdk/oak2-mod-manager/releases"
}
if (-not (Test-Path $dll)) { throw "Build first (build.cmd): $dll is missing." }

$target = Join-Path $GameDir 'sdk_mods\NativeGyro'
New-Item -ItemType Directory -Force $target | Out-Null
Copy-Item (Join-Path $repo 'mod\NativeGyro\__init__.py') $target -Force
Copy-Item $dll $target -Force

# The Phase B probe binds keys that move the camera; it is a development tool only.
$probe = Join-Path $GameDir 'sdk_mods\NativeGyroProbe'
if (Test-Path $probe) { Remove-Item -Recurse -Force $probe; Write-Host 'Removed development probe (NativeGyroProbe).' }

Write-Host "Installed to $target"
Write-Host 'In game: open the console (F6 or your console key), type  mods , select Native Gyro Aim and enable it.'
