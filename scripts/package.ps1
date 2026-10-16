# Builds the release zip players download: NativeGyro\ (mod + DLL + SDL3.dll), Install.cmd + installer window, install/uninstall
# scripts, oak2 manifest, README, LICENSE.
# No .pdb, dev tools or LGPL files. Run after build.cmd: powershell -ExecutionPolicy Bypass -File scripts\package.ps1 [-OutDir dist]
param([string]$OutDir)
$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
if (-not $OutDir) { $OutDir = Join-Path $repo 'dist' }
$dll = Join-Path $repo 'build\release\bl4gyro.dll'
if (-not (Test-Path $dll)) { throw "Build first (build.cmd): $dll is missing." }
$sdl = Join-Path $repo 'build\release\SDL3.dll' # zlib license; bl4gyro.dll needs it
$init = Join-Path $repo 'mod\NativeGyro\__init__.py'
$version = [regex]::Match((Get-Content -Raw $init), '__version__ = "([^"]+)"').Groups[1].Value
if (-not $version) { throw "__version__ not found in $init" }

$name = "NativeGyro-$version"
$stage = Join-Path $OutDir $name
if (Test-Path $stage) { Remove-Item -Recurse -Force $stage }
New-Item -ItemType Directory -Force (Join-Path $stage 'NativeGyro') | Out-Null
Copy-Item (Join-Path $repo 'mod\NativeGyro\*.py'), $dll, $sdl (Join-Path $stage 'NativeGyro')
Copy-Item (Join-Path $PSScriptRoot 'Install.cmd'), (Join-Path $PSScriptRoot 'installer.ps1'), (Join-Path $PSScriptRoot 'install.ps1'),
          (Join-Path $PSScriptRoot 'uninstall.ps1'), (Join-Path $PSScriptRoot 'steam-game-dir.ps1'),
          (Join-Path $repo 'README.md'), (Join-Path $repo 'LICENSE') $stage
Copy-Item (Join-Path $repo 'evidence\B-oak2-install-manifest.txt') (Join-Path $stage 'oak2-install-manifest.txt')

$zip = Join-Path $OutDir "$name.zip"
if (Test-Path $zip) { Remove-Item -Force $zip }
Compress-Archive $stage $zip
Remove-Item -Recurse -Force $stage
Write-Host $zip
Write-Host "SHA-256 zip:            $((Get-FileHash $zip).Hash)"
Write-Host "SHA-256 bl4gyro.dll:    $((Get-FileHash $dll).Hash)"
