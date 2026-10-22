$ErrorActionPreference = 'Stop'
try {
    $request = Get-Content "$PSScriptRoot\request.json" -Raw | ConvertFrom-Json
    foreach ($property in $request.Environment.PSObject.Properties) { [Environment]::SetEnvironmentVariable($property.Name,[string]$property.Value,'Process') }
    $options = @{ FilePath=$request.FilePath; WorkingDirectory=$request.WorkingDirectory; RedirectStandardOutput="$PSScriptRoot\stdout.log"; RedirectStandardError="$PSScriptRoot\stderr.log"; PassThru=$true; NoNewWindow=$true }
    if ($request.Arguments) { $options.ArgumentList = $request.Arguments }
    $child = Start-Process @options
    $null = $child.Handle # Retain the handle so Windows PowerShell preserves ExitCode.
    Set-Content "$PSScriptRoot\session-id.txt" (Get-Process -Id $PID).SessionId
    Set-Content "$PSScriptRoot\pid.txt" $child.Id
    $child.WaitForExit()
    Set-Content "$PSScriptRoot\exit-code.txt" $child.ExitCode
} catch { $_ | Out-String | Set-Content "$PSScriptRoot\error.txt"; exit 1 }
