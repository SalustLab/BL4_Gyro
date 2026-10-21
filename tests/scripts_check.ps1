# Checks the release zip (never the real game): exact entries, all under sdk_mods/BL4Gyro/ with '/' separators
# (players extract it into the game root with any tool), and that extracting it over an older install updates the mod
# while keeping every mod's settings.
# Run: powershell -NoProfile -ExecutionPolicy Bypass -File tests\scripts_check.ps1   (needs build\release\bl4gyro.dll)
$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
$tmp = Join-Path ([IO.Path]::GetTempPath()) "bl4gyro-scripts-$PID"
function Check([bool]$ok, [string]$what) { if (-not $ok) { throw "CHECK failed: $what" } }
Add-Type -AssemblyName System.IO.Compression.FileSystem

try {
    $out = Join-Path $tmp 'dist'
    & (Join-Path $repo 'scripts\package.ps1') -OutDir $out | Out-Null
    $zip = @(Get-ChildItem $out -Filter 'bl4-gyro_*.zip')
    Check ($zip.Count -eq 1) 'one zip produced'

    $archive = [IO.Compression.ZipFile]::OpenRead($zip[0].FullName)
    try { $entries = @($archive.Entries | ForEach-Object { $_.FullName }) } finally { $archive.Dispose() }
    $expected = '__init__.py', 'panel.py', 'state.py', 'bl4gyro.dll', 'SDL3.dll', 'README.md', 'LICENSE' |
                ForEach-Object { "sdk_mods/BL4Gyro/$_" }
    Check ($null -eq (Compare-Object ($expected | Sort-Object) ($entries | Sort-Object))) "zip entries: $($entries -join ', ')"

    # Fake game root with an older install, its settings and another mod's settings.
    $game = Join-Path $tmp 'Borderlands 4'
    $mod = Join-Path $game 'sdk_mods\BL4Gyro'
    New-Item -ItemType Directory -Force $mod, (Join-Path $game 'sdk_mods\settings') | Out-Null
    Set-Content (Join-Path $mod '__init__.py') 'old'
    $settings = Join-Path $game 'sdk_mods\settings\BL4Gyro.json'
    $saved = '{"options": {"Horizontal sensitivity": 3.0, "Gyro enabled": false}, "enabled": false}'
    Set-Content $settings $saved
    $other = Join-Path $game 'sdk_mods\settings\OtherMod.json'
    Set-Content $other '{"enabled": true}'

    Expand-Archive $zip[0].FullName $game -Force
    $sources = @{
        '__init__.py' = 'mod\BL4Gyro\__init__.py'; 'panel.py' = 'mod\BL4Gyro\panel.py'; 'state.py' = 'mod\BL4Gyro\state.py'
        'bl4gyro.dll' = 'build\release\bl4gyro.dll'; 'SDL3.dll' = 'build\release\SDL3.dll'; 'README.md' = 'README.md'; 'LICENSE' = 'LICENSE'
    }
    foreach ($f in $sources.Keys) {
        $a = Join-Path $mod $f
        Check ((Test-Path $a) -and (Get-FileHash $a).Hash -eq (Get-FileHash (Join-Path $repo $sources[$f])).Hash) "extracted $f"
    }
    Check ((Get-Content -Raw $settings).Trim() -eq $saved) 'extracting over an install keeps the settings'
    Check ((Get-Content -Raw $other).Trim() -eq '{"enabled": true}') "another mod's settings kept"

    Write-Host 'scripts_check: all checks passed'
} finally {
    if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
}
