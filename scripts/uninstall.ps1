# Removes Native Gyro Aim. Your gyro settings are kept unless -RemoveSettings. With -RemoveModManager it also removes
# every file the oak2-mod-manager install added (oak2-install-manifest.txt) - other mods then stop working too.
# Never touches game files or other mods' files.
# Run: powershell -ExecutionPolicy Bypass -File uninstall.ps1 [-GameDir "<...>"] [-RemoveSettings] [-RemoveModManager]
param([string]$GameDir, [switch]$RemoveSettings, [switch]$RemoveModManager)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'steam-game-dir.ps1')
if (-not $GameDir) { $GameDir = Find-GameDir }

if (Get-Process Borderlands4 -ErrorAction SilentlyContinue) { throw 'Borderlands 4 is running. Close the game first.' }

$paths = 'sdk_mods\NativeGyro', 'sdk_mods\NativeGyroProbe', 'sdk_mods\settings\NativeGyroProbe.json'
if ($RemoveSettings) { $paths += 'sdk_mods\settings\NativeGyro.json' }
foreach ($p in $paths) {
    $full = Join-Path $GameDir $p
    if (Test-Path $full) { Remove-Item -Recurse -Force $full; Write-Host "removed $p" }
}
if (-not $RemoveSettings -and (Test-Path (Join-Path $GameDir 'sdk_mods\settings\NativeGyro.json'))) {
    Write-Host 'kept your gyro settings (sdk_mods\settings\NativeGyro.json)'
}

if ($RemoveModManager) {
    $manifest = Join-Path $PSScriptRoot 'oak2-install-manifest.txt'  # release package; the repo keeps it in evidence\
    if (-not (Test-Path $manifest)) { $manifest = Join-Path (Split-Path $PSScriptRoot -Parent) 'evidence\B-oak2-install-manifest.txt' }
    Get-Content $manifest | Where-Object { $_ -and -not $_.StartsWith('#') } | ForEach-Object {
        $full = Join-Path $GameDir $_
        if (Test-Path $full -PathType Leaf) { Remove-Item -Force $full }
    }
    # Folders the mod manager created, removed only if nothing else was left in them.
    foreach ($dir in 'OakGame\Binaries\Win64\Plugins\DLLs', 'OakGame\Binaries\Win64\Plugins', 'sdk_mods\.stubs', 'sdk_mods\keybinds', 'sdk_mods\settings', 'sdk_mods') {
        $full = Join-Path $GameDir $dir
        if (Test-Path $full) {
            Get-ChildItem $full -Recurse -Directory | Sort-Object FullName -Descending |
                Where-Object { -not (Get-ChildItem $_.FullName -Force) } | Remove-Item -Force
            if (-not (Get-ChildItem $full -Recurse -File -Force)) { Remove-Item -Recurse -Force $full }
        }
    }
    Write-Host 'oak2-mod-manager files removed (logs and caches it created, if any, are left for you to inspect).'
}
