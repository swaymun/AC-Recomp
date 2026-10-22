# SoundVolumeView changes endpoint roles without embedding undocumented COM interfaces.
[CmdletBinding()]
param([string]$UnitRoot = 'C:\acr\units\WIN-SETUP-001')
. "$PSScriptRoot\common.ps1"
$Cache = Join-Path $UnitRoot 'downloads'
New-Item -ItemType Directory -Force $Cache | Out-Null
$exe = Join-Path $UnitRoot 'soundvolumeview\SoundVolumeView.exe'
if (!(Test-Path $exe)) {
    $zip = Get-Download 'https://www.nirsoft.net/utils/soundvolumeview-x64.zip' 'soundvolumeview-x64.zip'
    Expand-Archive $zip (Split-Path $exe) -Force
}
& $exe /SetDefault 'CABLE Input' all
& $exe /Unmute 'CABLE Input'
& $exe /SetVolume 'CABLE Input' 100
& $exe /Unmute 'CABLE Output'
& $exe /SetVolume 'CABLE Output' 100
& $exe /scomma "$UnitRoot\audio-endpoints.csv"
Start-Sleep -Milliseconds 500
$devices = Import-Csv "$UnitRoot\audio-endpoints.csv"
$playback = $devices | Where-Object { $_.Name -eq 'CABLE Input' -and $_.Direction -eq 'Render' }
if (!$playback -or $playback.Default -notmatch 'Render') {
    # Version-specific column values are preserved for inspection rather than inferred OK.
    $playback | Format-List | Out-String | Write-Output
    throw "Default playback not confirmed; inspect $UnitRoot\audio-endpoints.csv"
}
$playback | Select-Object Name,Default,'Default Multimedia','Default Communications'
