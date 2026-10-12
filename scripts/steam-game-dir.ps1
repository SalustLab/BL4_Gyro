# Finds the Borderlands 4 folder in any Steam library. Dot-source it, then call Find-GameDir.
function Find-GameDir([string]$SteamPath) {
    if (-not $SteamPath) {
        foreach ($key in 'HKCU:\Software\Valve\Steam|SteamPath', 'HKLM:\SOFTWARE\WOW6432Node\Valve\Steam|InstallPath') {
            $k, $name = $key -split '\|'
            $SteamPath = (Get-ItemProperty $k -Name $name -ErrorAction SilentlyContinue).$name
            if ($SteamPath) { break }
        }
    }
    if (-not $SteamPath) { throw 'Steam not found. Pass the game folder: -GameDir "<...>\Borderlands 4"' }

    $libraries = @([IO.Path]::GetFullPath($SteamPath))
    $vdf = Join-Path $SteamPath 'steamapps\libraryfolders.vdf'
    if (Test-Path $vdf) {
        $libraries += [regex]::Matches((Get-Content -Raw $vdf), '"path"\s+"([^"]+)"') | ForEach-Object { $_.Groups[1].Value -replace '\\\\', '\' }
    }
    foreach ($lib in $libraries) {
        # Join-Path throws for a library on a drive that is not connected; Combine does not.
        $acf = [IO.Path]::Combine($lib, 'steamapps\appmanifest_1285190.acf')
        if (-not (Test-Path -LiteralPath $acf)) { continue }
        $match = [regex]::Match((Get-Content -Raw -LiteralPath $acf), '"installdir"\s+"([^"]+)"')
        if ($match.Success) { return [IO.Path]::Combine($lib, "steamapps\common\$($match.Groups[1].Value)") }
    }
    throw "Borderlands 4 not found in the Steam libraries ($($libraries -join '; ')). Pass the game folder: -GameDir `"<...>\Borderlands 4`""
}
