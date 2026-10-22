# Run this inside the interactive session (via run_interactive.ps1 over SSH).
[CmdletBinding()]
param(
    [ValidateRange(1,3600)][int]$Seconds = 5,
    [Parameter(Mandatory)][string]$OutputDirectory,
    [ValidateSet('Both','Desktop','Audio')][string]$Mode = 'Both',
    [string]$AudioDevice = 'CABLE Output (VB-Audio Virtual Cable)',
    [ValidateSet('Wasapi','Dshow')][string]$AudioBackend = 'Wasapi',
    [ValidateSet('Ddagrab','Gdigrab')][string]$DesktopBackend = 'Ddagrab',
    [string]$UnitRoot = 'C:\acr\units\WIN-SETUP-001',
    [ValidateRange(1,60)][int]$FrameRate = 15
)
. "$PSScriptRoot\common.ps1"
if ((Get-Process -Id $PID).SessionId -eq 0) { throw 'Capture requires an interactive session; use run_interactive.ps1' }
New-Item -ItemType Directory -Force $OutputDirectory | Out-Null
$jobs = @()
if ($Mode -in 'Both','Desktop') {
    if ($DesktopBackend -eq 'Ddagrab') {
        $args = @('-hide_banner','-nostdin','-y','-f','lavfi','-i',"ddagrab=framerate=$FrameRate",'-t',$Seconds,'-an','-c:v','h264_nvenc','-preset','p1','-b:v','5M',('"'+(Join-Path $OutputDirectory 'desktop.mp4')+'"'))
    } else {
        $args = @('-hide_banner','-nostdin','-y','-f','gdigrab','-framerate',$FrameRate,'-i','desktop','-t',$Seconds,'-an','-c:v','libx264','-preset','ultrafast','-crf','20','-pix_fmt','yuv420p',('"'+(Join-Path $OutputDirectory 'desktop.mp4')+'"'))
    }
    $desktop = Start-Process ffmpeg -ArgumentList $args -PassThru -NoNewWindow -RedirectStandardError "$OutputDirectory\desktop-ffmpeg.log" -RedirectStandardOutput "$OutputDirectory\desktop-stdout.log"
    $null=$desktop.Handle
    $jobs += $desktop
}
if ($Mode -in 'Both','Audio') {
    if ($AudioBackend -eq 'Wasapi') {
        $client = Join-Path $UnitRoot 'audio-capture\AudioCapture.dll'
        if (!(Test-Path $client)) { throw 'Run build_audio_capture.ps1 before capture' }
        $args = @(('"'+$client+'"'),$Seconds,('"'+(Join-Path $OutputDirectory 'audio.wav')+'"'))
        $audio = Start-Process dotnet -ArgumentList $args -PassThru -NoNewWindow -RedirectStandardError "$OutputDirectory\audio-stderr.log" -RedirectStandardOutput "$OutputDirectory\audio-stdout.log"
    } else {
        $args = @('-hide_banner','-y','-f','dshow','-i',('audio="'+$AudioDevice+'"'),'-t',$Seconds,'-vn','-c:a','pcm_s16le',('"'+(Join-Path $OutputDirectory 'audio.wav')+'"'))
        $audio = Start-Process ffmpeg -ArgumentList $args -PassThru -NoNewWindow -RedirectStandardError "$OutputDirectory\audio-stderr.log" -RedirectStandardOutput "$OutputDirectory\audio-stdout.log"
    }
    $null=$audio.Handle
    $jobs += $audio
}
$failed = @()
foreach ($job in $jobs) {
    if (!$job.WaitForExit(($Seconds+30)*1000)) { Stop-Process -Id $job.Id -ErrorAction SilentlyContinue; $failed += "PID=$($job.Id) timeout"; continue }
    if ($null -eq $job.ExitCode -or $job.ExitCode -ne 0) { $failed += "PID=$($job.Id) exit=$($job.ExitCode)" }
}
if ($failed.Count) { throw "Capture failed ($failed); inspect ffmpeg logs in $OutputDirectory" }
foreach ($media in @(@('Desktop','desktop.mp4'),@('Audio','audio.wav'))) {
    if ($Mode -eq 'Both' -or $Mode -eq $media[0]) {
        $metadata = & ffprobe -v error -show_entries format=duration -of json (Join-Path $OutputDirectory $media[1]) | Out-String
        if ($LASTEXITCODE) { throw "Cannot probe $($media[1])" }
        if ([double](($metadata | ConvertFrom-Json).format.duration) -lt $Seconds-0.3) { throw "$($media[1]) is shorter than requested" }
    }
}
Get-ChildItem $OutputDirectory | Select-Object Name,Length
