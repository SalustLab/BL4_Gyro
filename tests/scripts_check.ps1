# End-to-end check of the release scripts against a fake Steam install in a temp folder (never the real game):
# game folder detection, package contents, install from the extracted package, uninstall with and without -RemoveModManager.
# Run: powershell -NoProfile -ExecutionPolicy Bypass -File tests\scripts_check.ps1   (needs build\release\bl4gyro.dll)
$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
$tmp = Join-Path ([IO.Path]::GetTempPath()) "bl4gyro-scripts-$PID"
function Check([bool]$ok, [string]$what) { if (-not $ok) { throw "CHECK failed: $what" } }
function Throws([scriptblock]$block) { try { & $block; return $false } catch { return $true } }
function Touch([string]$path) { New-Item -ItemType File -Force $path | Out-Null }

try {
    . (Join-Path $repo 'scripts\steam-game-dir.ps1')

    # Fake Steam: an unplugged-drive library, then the game in a library whose path has spaces.
    $missing = [char[]](90..68) | Where-Object { -not (Test-Path "${_}:\") } | Select-Object -First 1
    Check ($missing -ne $null) 'a free drive letter for the unplugged library'
    $steam = Join-Path $tmp 'Steam'
    $lib = Join-Path $tmp 'Steam Library 2'
    New-Item -ItemType Directory -Force (Join-Path $steam 'steamapps'), (Join-Path $lib 'steamapps') | Out-Null
    $vdf = "`"libraryfolders`"`n{`n`t`"0`"`n`t{`n`t`t`"path`"`t`t`"$($steam -replace '\\', '\\')`"`n`t}`n" +
           "`t`"1`"`n`t{`n`t`t`"path`"`t`t`"${missing}:\\SteamLibrary`"`n`t}`n" +
           "`t`"2`"`n`t{`n`t`t`"path`"`t`t`"$($lib -replace '\\', '\\')`"`n`t}`n}`n"
    Set-Content -Encoding ascii (Join-Path $steam 'steamapps\libraryfolders.vdf') $vdf
    Check (Throws { Find-GameDir -SteamPath $steam }) 'no appmanifest -> throws'

    Set-Content -Encoding ascii (Join-Path $lib 'steamapps\appmanifest_1285190.acf') "`"AppState`"`n{`n`t`"appid`"`t`t`"1285190`"`n`t`"installdir`"`t`t`"Borderlands 4`"`n}`n"
    $game = Join-Path $lib 'steamapps\common\Borderlands 4'
    Check ((Find-GameDir -SteamPath $steam) -eq $game) "detected game dir ($(Find-GameDir -SteamPath $steam))"

    # Package, then use only what is inside the zip from here on.
    $out = Join-Path $tmp 'dist'
    & (Join-Path $repo 'scripts\package.ps1') -OutDir $out | Out-Null
    $zip = @(Get-ChildItem $out -Filter 'NativeGyro-*.zip')
    Check ($zip.Count -eq 1) 'one zip produced'
    $pkg = Join-Path $tmp 'pkg'
    Expand-Archive $zip[0].FullName $pkg
    $root = (Get-ChildItem $pkg -Directory)[0].FullName
    $files = Get-ChildItem $root -Recurse -File | ForEach-Object { $_.FullName.Substring($root.Length + 1) } | Sort-Object
    $expected = 'LICENSE', 'NativeGyro\__init__.py', 'NativeGyro\bl4gyro.dll', 'NativeGyro\SDL3.dll', 'README.md', 'install.ps1',
                'oak2-install-manifest.txt', 'steam-game-dir.ps1', 'uninstall.ps1' | Sort-Object
    Check ((Compare-Object $expected $files) -eq $null) "package contents: $($files -join ', ')"

    # Fake game with oak2-mod-manager (every file of its manifest), a game file and another mod.
    $manifest = Get-Content (Join-Path $root 'oak2-install-manifest.txt') | Where-Object { $_ -and -not $_.StartsWith('#') }
    $manifest | ForEach-Object { Touch (Join-Path $game $_) }
    Touch (Join-Path $game 'OakGame\Binaries\Win64\Borderlands4.exe')
    Touch (Join-Path $game 'sdk_mods\OtherMod\__init__.py')

    & (Join-Path $root 'install.ps1') -GameDir $game | Out-Null
    foreach ($f in '__init__.py', 'bl4gyro.dll', 'SDL3.dll') {
        $a = Join-Path $game "sdk_mods\NativeGyro\$f"
        Check ((Test-Path $a) -and (Get-FileHash $a).Hash -eq (Get-FileHash (Join-Path $root "NativeGyro\$f")).Hash) "installed $f"
    }

    & (Join-Path $root 'uninstall.ps1') -GameDir $game | Out-Null
    Check (-not (Test-Path (Join-Path $game 'sdk_mods\NativeGyro'))) 'mod removed'
    Check (Test-Path (Join-Path $game 'OakGame\Binaries\Win64\Plugins\pyunrealsdk.dll')) 'oak2 kept without -RemoveModManager'

    & (Join-Path $root 'uninstall.ps1') -GameDir $game -RemoveModManager | Out-Null
    $left = @($manifest | Where-Object { Test-Path (Join-Path $game $_) })
    Check ($left.Count -eq 0) "oak2 files removed (left: $($left -join ', '))"
    Check (Test-Path (Join-Path $game 'OakGame\Binaries\Win64\Borderlands4.exe')) 'game file kept'
    Check (Test-Path (Join-Path $game 'sdk_mods\OtherMod\__init__.py')) 'other mod kept'

    Write-Host 'scripts_check: all checks passed'
} finally {
    if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
}
