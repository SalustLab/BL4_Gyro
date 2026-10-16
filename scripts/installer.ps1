# Native Gyro installer window (Windows Forms, built into Windows: nothing to download). Double-click Install.cmd.
# All the work is done by install.ps1 / uninstall.ps1 next to it; this window only collects the choices.
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
[Windows.Forms.Application]::EnableVisualStyles()
. (Join-Path $PSScriptRoot 'steam-game-dir.ps1')

$form = New-Object Windows.Forms.Form -Property @{
    Text = 'Native Gyro Aim - installer'; Size = New-Object Drawing.Size(640, 470); StartPosition = 'CenterScreen'
    FormBorderStyle = 'FixedDialog'; MaximizeBox = $false; Font = New-Object Drawing.Font('Segoe UI', 10)
}
function Add([Windows.Forms.Control]$c, [int]$x, [int]$y, [int]$w, [int]$h) {
    $c.Location = New-Object Drawing.Point($x, $y); $c.Size = New-Object Drawing.Size($w, $h); $form.Controls.Add($c); $c
}
Add (New-Object Windows.Forms.Label -Property @{ Text = 'Borderlands 4 folder' }) 16 14 300 22 | Out-Null
$dir = Add (New-Object Windows.Forms.TextBox) 16 38 488 26
$browse = Add (New-Object Windows.Forms.Button -Property @{ Text = 'Browse...' }) 512 36 100 30
$checks = Add (New-Object Windows.Forms.Label) 16 74 596 70
$install = Add (New-Object Windows.Forms.Button -Property @{ Text = 'Install / Update' }) 16 150 160 36
$uninstall = Add (New-Object Windows.Forms.Button -Property @{ Text = 'Uninstall' }) 184 150 120 36
$removeSettings = Add (New-Object Windows.Forms.CheckBox -Property @{ Text = 'also delete my gyro settings' }) 312 156 300 26
$removeOak2 = Add (New-Object Windows.Forms.LinkLabel -Property @{ Text = 'Remove oak2-mod-manager (affects every mod)...' }) 16 194 400 22
$log = Add (New-Object Windows.Forms.TextBox -Property @{ Multiline = $true; ReadOnly = $true; ScrollBars = 'Vertical' }) 16 222 596 196

function Say([string]$text) { $log.AppendText("$text`r`n"); $form.Refresh() }

function Check-Folder {
    $g = $dir.Text
    $lines = @()
    $valid = $g -and (Test-Path (Join-Path $g 'OakGame\Binaries\Win64'))
    $lines += if ($valid) { '[ok] Borderlands 4 folder' } else { '[!!] Not a Borderlands 4 folder (it must contain OakGame)' }
    $toml = Join-Path $g 'OakGame\Binaries\Win64\Plugins\unrealsdk.toml'
    $oak2 = $valid -and (Test-Path (Join-Path $g 'OakGame\Binaries\Win64\Plugins\pyunrealsdk.dll'))
    $version = if ($oak2 -and (Test-Path $toml)) { [regex]::Match("$(Get-Content -Raw $toml)", 'display_version\s*=\s*"([^"]+)"').Groups[1].Value }
    $lines += if ($oak2) { "[ok] oak2-mod-manager $version" } else { '[--] oak2-mod-manager not installed (Install will offer to download v0.3)' }
    $mod = $valid -and (Test-Path (Join-Path $g 'sdk_mods\NativeGyro\__init__.py'))
    $lines += if ($mod) { '[ok] Native Gyro installed (Install updates it, settings kept)' } else { '[--] Native Gyro not installed yet' }
    if (Get-Process Borderlands4 -ErrorAction SilentlyContinue) { $lines += '[!!] The game is running: close it before installing' }
    $checks.Text = $lines -join "`r`n"
    $install.Enabled = $uninstall.Enabled = $valid
    return @{ Valid = $valid; Oak2 = $oak2; Mod = $mod }
}

function Run([string]$script, [hashtable]$params) {
    try {
        & (Join-Path $PSScriptRoot $script) @params *>&1 | ForEach-Object { Say "$_" }
        return $true
    } catch {
        Say "ERROR: $($_.Exception.Message)"
        [Windows.Forms.MessageBox]::Show($form, $_.Exception.Message, 'Native Gyro', 'OK', 'Error') | Out-Null
        return $false
    } finally {
        Check-Folder | Out-Null
    }
}

$browse.Add_Click({
    $pick = New-Object Windows.Forms.FolderBrowserDialog -Property @{ Description = 'Choose the Borderlands 4 folder (it contains OakGame)' }
    if ($pick.ShowDialog($form) -eq 'OK') { $dir.Text = $pick.SelectedPath }
})
$dir.Add_TextChanged({ Check-Folder | Out-Null })

$install.Add_Click({
    $state = Check-Folder
    $params = @{ GameDir = $dir.Text }
    if (-not $state.Oak2) {
        $answer = [Windows.Forms.MessageBox]::Show($form,
            "Native Gyro needs oak2-mod-manager (the Borderlands 4 mod loader by bl-sdk).`n`n" +
            "Download oak2-mod-manager v0.3 from its official GitHub release and install it into the game folder?`n" +
            "The file is checked against a known SHA-256 before anything is copied.",
            'Native Gyro', 'YesNo', 'Question')
        if ($answer -ne 'Yes') { Say 'Cancelled: oak2-mod-manager is required.'; return }
        $params.InstallModManager = $true
    }
    Say '--- installing'
    if (Run 'install.ps1' $params) {
        [Windows.Forms.MessageBox]::Show($form, "Done. Start Borderlands 4: gyro is on.`nHold L3 + R3 (or press F8) in game to open the gyro panel.",
            'Native Gyro', 'OK', 'Information') | Out-Null
    }
})

$uninstall.Add_Click({
    Say '--- uninstalling'
    Run 'uninstall.ps1' @{ GameDir = $dir.Text; RemoveSettings = $removeSettings.Checked } | Out-Null
})

$removeOak2.Add_Click({
    $answer = [Windows.Forms.MessageBox]::Show($form,
        "This removes oak2-mod-manager itself. Every Borderlands 4 mod that uses it stops working (their own files are kept).`n`nContinue?",
        'Native Gyro', 'YesNo', 'Warning')
    if ($answer -eq 'Yes') {
        Say '--- removing oak2-mod-manager'
        Run 'uninstall.ps1' @{ GameDir = $dir.Text; RemoveSettings = $removeSettings.Checked; RemoveModManager = $true } | Out-Null
    }
})

try { $dir.Text = Find-GameDir; Say "Found Borderlands 4 through Steam: $($dir.Text)" }
catch { Say 'Borderlands 4 was not found through Steam. Use Browse to choose its folder.'; Check-Folder | Out-Null }
[void]$form.ShowDialog()
