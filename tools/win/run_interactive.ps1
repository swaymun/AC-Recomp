# Launch a native executable in admin's existing interactive console, never session 0.
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$FilePath,
    [string]$Arguments = '',
    [string]$WorkingDirectory = 'C:\acr\units\WIN-SETUP-001',
    [hashtable]$Environment = @{},
    [string]$LogDirectory = 'C:\acr\units\WIN-SETUP-001\interactive',
    [int]$StartTimeoutSeconds = 30
)
$ErrorActionPreference = 'Stop'
if (!('AcrConsole' -as [type])) {
    Add-Type 'using System.Runtime.InteropServices; public static class AcrConsole { [DllImport("kernel32.dll")] public static extern uint WTSGetActiveConsoleSessionId(); }'
}
$consoleId = [AcrConsole]::WTSGetActiveConsoleSessionId()
$session = Get-Process explorer -ErrorAction SilentlyContinue | Where-Object SessionId -eq $consoleId | Select-Object -First 1
if (!$session) { throw 'No logged-in console desktop. Configure autologon and reboot first.' }
$id = [Guid]::NewGuid().ToString('N')
$jobDir = Join-Path $LogDirectory $id
New-Item -ItemType Directory -Force $jobDir | Out-Null
@{ FilePath=$FilePath; Arguments=$Arguments; WorkingDirectory=$WorkingDirectory; Environment=$Environment; JobDirectory=$jobDir } | ConvertTo-Json -Depth 5 | Set-Content "$jobDir\request.json" -Encoding UTF8
Copy-Item "$PSScriptRoot\interactive_worker.ps1" "$jobDir\worker.ps1"
$name = "ACR-interactive-$id"
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$jobDir\worker.ps1`""
$principal = New-ScheduledTaskPrincipal -UserId "$env:COMPUTERNAME\admin" -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 12) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $name -Action $action -Principal $principal -Settings $settings -Force | Out-Null
Start-ScheduledTask $name
$deadline = (Get-Date).AddSeconds($StartTimeoutSeconds)
while (!(Test-Path "$jobDir\pid.txt") -and (Get-Date) -lt $deadline) {
    if (Test-Path "$jobDir\error.txt") { throw (Get-Content "$jobDir\error.txt" -Raw) }
    Start-Sleep -Milliseconds 200
}
if (!(Test-Path "$jobDir\pid.txt")) { throw "Interactive start timed out; inspect $jobDir and task $name" }
$childId = [int](Get-Content "$jobDir\pid.txt")
$taskSession = [int](Get-Content "$jobDir\session-id.txt")
if ($taskSession -ne $consoleId) {
    Stop-Process -Id $childId -ErrorAction SilentlyContinue
    throw "Task ran in session $taskSession, expected console $consoleId; inspect $jobDir"
}
$child = Get-Process -Id $childId -ErrorAction SilentlyContinue
if ($child -and $child.SessionId -ne $consoleId) {
    Stop-Process -Id $childId -ErrorAction SilentlyContinue
    throw "Task launched in session $($child.SessionId), expected console $consoleId; inspect $jobDir"
}
[pscustomobject]@{ PID=$childId; SessionId=$consoleId; TaskName=$name; JobDirectory=$jobDir; Stdout="$jobDir\stdout.log"; Stderr="$jobDir\stderr.log"; ExitCodeFile="$jobDir\exit-code.txt" }
