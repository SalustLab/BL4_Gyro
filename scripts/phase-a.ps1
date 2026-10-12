# Guided Phase A hardware matrix for the GuliKit TT Max. Evidence goes to <repo>\evidence
# (ttmax-diag also appends to evidence\live.log so a run can be watched while it happens).
# Run: powershell -ExecutionPolicy Bypass -File F:\Projetos\bl4-native-gyro\scripts\phase-a.ps1 [-BluetoothOnly]
param([switch]$BluetoothOnly)
$repo = Split-Path $PSScriptRoot -Parent
$diag = Join-Path $repo 'build\release\ttmax-diag.exe'
Set-Location $repo

$cases = @(
    @{ id = 'switch-usb';   bt = $false; steam = $false; text = 'SWITCH mode over USB CABLE. Steam fully CLOSED (tray too).' },
    @{ id = 'switch-bt';    bt = $true;  steam = $false; text = 'SWITCH mode over BLUETOOTH. Steam fully CLOSED (tray too).' },
    @{ id = 'pc-usb';       bt = $false; steam = $false; text = 'PC (XInput) mode over USB CABLE. Turn on Motion Aim Assist (hold Settings+L).' },
    @{ id = 'pc-bt';        bt = $true;  steam = $false; text = 'PC (XInput) mode over BLUETOOTH. Turn on Motion Aim Assist (hold Settings+L). Steam closed.' },
    @{ id = 'pc-24g';       bt = $false; steam = $false; text = 'PC mode over the 2.4 GHz DONGLE.' },
    @{ id = 'switch-steam'; bt = $true;  steam = $true;  text = 'SWITCH mode, Steam OPEN with "Nintendo Switch" enabled in Steam > Settings > Controller.' }
)

foreach ($c in $cases) {
    if ($BluetoothOnly -and -not $c.bt) { continue }
    Write-Host "`n=== $($c.id): $($c.text)" -ForegroundColor Cyan
    if ((Read-Host 'Enter to start, S to skip') -eq 'S') { continue }
    & $diag hid --label "$($c.id)-hid" | Out-Null
    & $diag sdl --label $c.id
    if ($c.steam) {
        Write-Host "`n--- same mode, now read through the Steam Input API (as Borderlands 4)" -ForegroundColor Cyan
        & $diag steam --label "$($c.id)-api"
    }
}

Write-Host "`n=== drift: SWITCH mode + Steam open, controller STILL on the desk for 5 minutes" -ForegroundColor Cyan
if ((Read-Host 'Enter to start, S to skip') -ne 'S') { & $diag steam --rest 300 --label drift-steam }

Write-Host "`nEvidence in $repo\evidence" -ForegroundColor Green
