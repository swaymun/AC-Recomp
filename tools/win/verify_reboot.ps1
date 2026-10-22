# Explicitly authorized reboot gate. Call -Reboot, reconnect, then call without it.
[CmdletBinding()]
param([switch]$Reboot,[string]$UnitRoot='C:\acr\units\WIN-SETUP-001')
. "$PSScriptRoot\common.ps1"
$before=Join-Path $UnitRoot 'reboot-before.json'
$boot=(Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToUniversalTime().ToString('o')
if($Reboot){
    if(!(Test-Path 'C:\acr\data\UPLOAD_OK')){throw 'Upload incomplete; refusing to reboot'}
    @{BootTime=$boot;RequestedAt=[DateTime]::UtcNow.ToString('o')}|ConvertTo-Json|Set-Content $before
    Restart-Computer -Force
    return
}
if(!(Test-Path $before)){throw 'No pre-reboot baseline recorded'}
$baseline=Get-Content $before -Raw|ConvertFrom-Json
if($baseline.BootTime -eq $boot){throw 'Boot time has not changed'}
$deadline=(Get-Date).AddSeconds(60)
do {
    $console=Get-ConsoleSessionId
    $explorer=Get-Process explorer -ErrorAction SilentlyContinue|Where-Object SessionId -eq $console
    if(!$explorer){Start-Sleep -Seconds 1}
} while(!$explorer -and (Get-Date) -lt $deadline)
if(!$explorer){throw 'No console explorer after reboot'}
$result=[pscustomobject]@{Before=$baseline.BootTime;After=$boot;ConsoleSession=$console;ExplorerPID=$explorer[0].Id;Result='OK'}
$result|ConvertTo-Json|Set-Content (Join-Path $UnitRoot 'reboot-proof.json')
$result
