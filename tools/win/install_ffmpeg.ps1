# FFmpeg 8 uses NVENC API 13.0, supported by the supplied GRID 596.86 driver.
param([string]$UnitRoot='C:\acr\units\WIN-SETUP-001')
. "$PSScriptRoot\common.ps1"
$Cache=Join-Path $UnitRoot 'downloads'
$target=Join-Path $UnitRoot 'ffmpeg8'
$bin=Join-Path $target 'ffmpeg-8.0.1-essentials_build\bin'
if(!(Test-Path "$bin\ffmpeg.exe")){
    $zip=Get-Download 'https://github.com/GyanD/codexffmpeg/releases/download/8.0.1/ffmpeg-8.0.1-essentials_build.zip' 'ffmpeg-8.0.1-essentials.zip'
    if((Get-FileHash $zip -Algorithm SHA256).Hash -ne 'e2aaeaa0fdbc397d4794828086424d4aaa2102cef1fb6874f6ffd29c0b88b673'){throw 'FFmpeg checksum mismatch'}
    Expand-Archive $zip $target -Force
}
$machine=[Environment]::GetEnvironmentVariable('Path','Machine')
if($bin -notin ($machine -split ';')){[Environment]::SetEnvironmentVariable('Path',"$bin;$machine",'Machine')}
Refresh-Path
$version=& "$bin\ffmpeg.exe" -version
if($LASTEXITCODE){throw 'FFmpeg 8 failed'}
$version | Select-Object -First 1
