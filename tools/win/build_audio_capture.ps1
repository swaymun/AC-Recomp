param([string]$UnitRoot='C:\acr\units\WIN-SETUP-001')
. "$PSScriptRoot\common.ps1"
$env:DOTNET_CLI_TELEMETRY_OPTOUT='1'
$env:DOTNET_GENERATE_ASPNET_CERTIFICATE='false'
$source=Join-Path $PSScriptRoot 'audio_capture'
$target=Join-Path $UnitRoot 'audio-capture'
$hash=(@(Get-FileHash "$source\AudioCapture.csproj","$source\Program.cs" -Algorithm SHA256).Hash -join ':')
$marker=Join-Path $target 'source-hash.txt'
if (!(Test-Path "$target\AudioCapture.dll") -or !(Test-Path $marker) -or (Get-Content $marker -Raw).Trim() -ne $hash) {
    New-Item -ItemType Directory -Force $target | Out-Null
    Invoke-Checked dotnet @('publish',('"'+$source+'\AudioCapture.csproj"'),'-c','Release','-o',('"'+$target+'"'),'--nologo','-v','minimal')
    if (!(Test-Path "$target\AudioCapture.dll")) { throw 'WASAPI helper did not build' }
    Set-Content $marker $hash
}
"$target\AudioCapture.dll"
