$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')
    $extra = @('C:\Program Files\Git\cmd','C:\Program Files\Python312','C:\Program Files\Python312\Scripts','C:\Program Files\dotnet','C:\Program Files\7-Zip','C:\ProgramData\chocolatey\bin')
    $vs = 'C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools'
    $extra += "$vs\VC\Tools\Llvm\x64\bin", "$vs\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin", "$vs\Common7\IDE\CommonExtensions\Microsoft\CMake\Ninja"
    $env:Path = ($extra -join ';') + ';' + $env:Path
}
function Invoke-Checked([string]$File, [string[]]$Arguments, [int[]]$SuccessCodes = @(0,3010)) {
    Write-Host "invoke-checked: $File"
    $p = Start-Process -FilePath $File -ArgumentList $Arguments -PassThru -Wait -NoNewWindow
    if ($p.ExitCode -notin $SuccessCodes) { throw "$File failed: exit $($p.ExitCode)" }
}
function Get-Download([string]$Url, [string]$Name) {
    $dest = Join-Path $Cache $Name
    if (!(Test-Path $dest)) {
        Write-Host "download: $Name"
        Invoke-WebRequest -Uri $Url -OutFile "$dest.partial" -UseBasicParsing
        Move-Item "$dest.partial" $dest -Force
    }
    return $dest
}
function Get-GithubAsset([string]$Repository, [string]$Pattern) {
    $release = Invoke-RestMethod "https://api.github.com/repos/$Repository/releases/latest"
    $asset = @($release.assets | Where-Object name -match $Pattern)
    if ($asset.Count -ne 1) { throw "Expected one asset for $Repository / $Pattern; found $($asset.Count)" }
    Get-Download $asset[0].browser_download_url $asset[0].name
}
Refresh-Path

function Get-ConsoleSessionId {
    if (!('AcrConsole' -as [type])) {
        Add-Type 'using System.Runtime.InteropServices; public static class AcrConsole { [DllImport("kernel32.dll")] public static extern uint WTSGetActiveConsoleSessionId(); }'
    }
    [AcrConsole]::WTSGetActiveConsoleSessionId()
}
