# Builds the release zip players download and extract into the Borderlands 4 folder: every entry is under
# sdk_mods/BL4Gyro/ (mod, DLL, SDL3.dll, README, LICENSE). No settings, so extracting over an install keeps them.
# No .pdb, dev tools or LGPL files. Run after build.cmd: powershell -ExecutionPolicy Bypass -File scripts\package.ps1 [-OutDir dist]
param([string]$OutDir)
$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
if (-not $OutDir) { $OutDir = Join-Path $repo 'dist' }
$dll = Join-Path $repo 'build\release\bl4gyro.dll'
if (-not (Test-Path $dll)) { throw "Build first (build.cmd): $dll is missing." }
$sdl = Join-Path $repo 'build\release\SDL3.dll' # zlib license; bl4gyro.dll needs it
$init = Join-Path $repo 'mod\BL4Gyro\__init__.py'
$version = [regex]::Match((Get-Content -Raw $init), '__version__ = "([^"]+)"').Groups[1].Value
if (-not $version) { throw "__version__ not found in $init" }

$files = @(Get-ChildItem (Join-Path $repo 'mod\BL4Gyro\*.py') | ForEach-Object FullName) +
         $dll, $sdl, (Join-Path $repo 'README.md'), (Join-Path $repo 'LICENSE')
New-Item -ItemType Directory -Force $OutDir | Out-Null
$zip = Join-Path $OutDir "bl4-gyro_$version.zip"
if (Test-Path $zip) { Remove-Item -Force $zip }
# Not Compress-Archive: on PowerShell 5.1 it writes '\' in entry names, which other extractors mishandle.
Add-Type -AssemblyName System.IO.Compression, System.IO.Compression.FileSystem
$archive = [IO.Compression.ZipFile]::Open($zip, 'Create')
try {
    foreach ($f in $files) {
        [IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive, $f, "sdk_mods/BL4Gyro/$(Split-Path $f -Leaf)") | Out-Null
    }
} finally {
    $archive.Dispose()
}
Write-Host $zip
Write-Host "SHA-256 zip:            $((Get-FileHash $zip).Hash)"
Write-Host "SHA-256 bl4gyro.dll:    $((Get-FileHash $dll).Hash)"
