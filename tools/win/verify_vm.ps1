# Real-machine acceptance probes. Evidence is private; never add it to Git.
[CmdletBinding()]
param([string]$UnitRoot='C:\acr\units\WIN-SETUP-001', [switch]$SkipCapture)
. "$PSScriptRoot\common.ps1"
$evidence=Join-Path $UnitRoot ('evidence-'+(Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Force $evidence | Out-Null
Start-Transcript "$evidence\verify.log" | Out-Null
function Wait-Interactive($Job,[int]$Seconds=120) {
    $deadline=(Get-Date).AddSeconds($Seconds)
    while(!(Test-Path $Job.ExitCodeFile) -and (Get-Date) -lt $deadline){ Start-Sleep -Milliseconds 200 }
    if(!(Test-Path $Job.ExitCodeFile)){ throw "No exit status for $($Job.JobDirectory)" }
    $code=[int](Get-Content $Job.ExitCodeFile)
    Unregister-ScheduledTask $Job.TaskName -Confirm:$false -ErrorAction SilentlyContinue
    return $code
}
try {
    foreach($file in Get-ChildItem "$PSScriptRoot\*.ps1") {
        $tokens=$null; $errors=$null
        [Management.Automation.Language.Parser]::ParseFile($file.FullName,[ref]$tokens,[ref]$errors)|Out-Null
        if($errors){ throw "$($file.Name): $errors" }
    }
    'PowerShell parse OK'
    foreach($tool in @(@('git','--version'),@('python','--version'),@('clang-cl','--version'),@('cmake','--version'),@('ninja','--version'),@('dotnet','--list-sdks'),@('ffmpeg','-version'))) {
        $result=& $tool[0] $tool[1]
        if($LASTEXITCODE){ throw "$($tool[0]) failed" }
        $result | Select-Object -First 3
    }
    $vulkan=& vulkaninfo --summary 2>&1 | Out-String
    $vulkan | Set-Content "$evidence\vulkan.txt"
    if($LASTEXITCODE -or $vulkan -notmatch 'NVIDIA L4'){ throw 'Vulkan L4 probe failed' }
    . "$PSScriptRoot\build_env.ps1"
    '#include <windows.h>
#include <stdio.h>
int main(){printf("SDK compile/link OK process=%lu\n",GetCurrentProcessId());return 0;}' | Set-Content "$evidence\sdk-probe.cpp"
    Push-Location $evidence
    try {
        & clang-cl /nologo sdk-probe.cpp /Fe:sdk-probe.exe
        if($LASTEXITCODE){ throw 'SDK compile/link failed' }
        & '.\sdk-probe.exe'
        if($LASTEXITCODE){ throw 'SDK executable failed' }
    } finally { Pop-Location }
    # Exercise the public launcher contract, including env, cwd, stderr and nonzero exit.
    '$ErrorActionPreference="Stop"; Write-Output "env=$env:ACR_HELPER_TEST cwd=$pwd session=$((Get-Process -Id $PID).SessionId)"; [Console]::Error.WriteLine("stderr-probe"); exit 7' | Set-Content "$evidence\launch-probe.ps1"
    $probe=& "$PSScriptRoot\run_interactive.ps1" -FilePath powershell.exe -Arguments "-NoProfile -File $evidence\launch-probe.ps1" -WorkingDirectory $evidence -Environment @{ACR_HELPER_TEST='present'} -LogDirectory "$evidence\jobs"
    $probe | ConvertTo-Json | Set-Content "$evidence\launch-result.json"
    $code=Wait-Interactive $probe
    $stdout=Get-Content $probe.Stdout -Raw; $stderr=Get-Content $probe.Stderr -Raw
    if($code -ne 7 -or $stdout -notmatch 'env=present' -or $stdout -notlike "*cwd=$evidence*" -or $stderr -notmatch 'stderr-probe' -or $probe.SessionId -eq 0){ throw "Launcher contract failed: exit=$code stdout=$stdout stderr=$stderr" }
    "Interactive launcher OK PID=$($probe.PID), session=$($probe.SessionId), exit=$code, env/cwd/stdout/stderr"
    & "$UnitRoot\pad-venv\Scripts\python.exe" "$PSScriptRoot\gamepad.py" --self-test | Tee-Object "$evidence\xinput.json"
    if($LASTEXITCODE){ throw 'Gamepad self-test failed' }
    '{"buttons":["A"],"ms":200}
{"buttons":[],"ms":100}' | Set-Content "$evidence\pad.jsonl"
    & "$UnitRoot\pad-venv\Scripts\python.exe" "$PSScriptRoot\gamepad.py" "$evidence\pad.jsonl" | Tee-Object "$evidence\scripted-pad.jsonl"
    if($LASTEXITCODE){ throw 'Scripted pad failed' }
    $pressed,$released=Get-Content "$evidence\scripted-pad.jsonl" | ForEach-Object { $_|ConvertFrom-Json }
    if(!($pressed.xinput.PSObject.Properties.Value.buttons -contains 4096) -or !($released.xinput.PSObject.Properties.Value.buttons -contains 0)){ throw 'Scripted XInput A transitions not observed' }
    $svc=Get-Service SunshineService
    if($svc.Status -ne 'Running'){ throw 'Sunshine stopped' }
    $listeners=Get-NetTCPConnection -State Listen | Where-Object LocalPort -in @(47984,47989,47990,48010)
    $listeners | Select-Object LocalAddress,LocalPort,OwningProcess | Format-Table
    if(!($listeners.LocalPort -contains 47990)){ throw 'Sunshine UI not listening' }
    & "$PSScriptRoot\sunshine_pair.ps1" -Check -CredentialFile "$UnitRoot\secrets\sunshine-credential.bin"
    if(!$SkipCapture){
        $null = & "$PSScriptRoot\build_audio_capture.ps1" -UnitRoot $UnitRoot
        & "$PSScriptRoot\audio_default.ps1" -UnitRoot $UnitRoot
        $toneFile = & "$PSScriptRoot\test_tone.ps1" -OutputDirectory "$evidence\tone" -Seconds 4 -PrepareOnly | Select-Object -Last 1
        $cubePath=& "$PSScriptRoot\install_vulkan_tools.ps1" -UnitRoot $UnitRoot | Select-Object -Last 1
        $cube=& "$PSScriptRoot\run_interactive.ps1" -FilePath $cubePath -LogDirectory "$evidence\jobs"
        try {
            Start-Sleep -Seconds 3
            if(!(Get-Process -Id $cube.PID -ErrorAction SilentlyContinue)){ throw 'vkcube exited before capture' }
            $captureArgs="-NoProfile -ExecutionPolicy Bypass -File `"$PSScriptRoot\capture_probe.ps1`" -Seconds 8 -OutputDirectory `"$evidence\capture`" -ToneFile `"$toneFile`" -WindowPID $($cube.PID)"
            $capture=& "$PSScriptRoot\run_interactive.ps1" -FilePath powershell.exe -Arguments $captureArgs -LogDirectory "$evidence\jobs"
            if((Wait-Interactive $capture) -ne 0){ throw "Capture failed; inspect $($capture.JobDirectory)" }
        } finally { Stop-Process -Id $cube.PID -ErrorAction SilentlyContinue; Unregister-ScheduledTask $cube.TaskName -Confirm:$false -ErrorAction SilentlyContinue }
        foreach ($media in 'desktop.mp4','audio.wav') {
            $probe = & ffprobe -v error -show_entries 'format=duration:stream=nb_frames,width,height' -of json "$evidence\capture\$media" | Out-String
            if ($LASTEXITCODE) { throw "ffprobe failed for $media" }
            $probe | Set-Content "$evidence\$media-probe.json"
            $metadata = $probe | ConvertFrom-Json
            if ([double]$metadata.format.duration -lt 7.5) { throw "Capture shorter than requested: $media duration=$($metadata.format.duration)" }
            if ($media -eq 'desktop.mp4' -and [int]$metadata.streams[0].nb_frames -lt 90) { throw 'Desktop capture produced fewer than 90 frames' }
        }
        Invoke-Checked ffmpeg @('-hide_banner','-y','-ss','3','-i',('"'+$evidence+'\capture\desktop.mp4"'),'-frames:v','1','-update','1',('"'+$evidence+'\frame.png"'))
        if (!(Test-Path "$evidence\frame.png")) { throw 'No Vulkan proof frame extracted' }
        $p=Start-Process ffmpeg -ArgumentList @('-hide_banner','-i',('"'+$evidence+'\capture\audio.wav"'),'-af','volumedetect','-f','null','NUL') -Wait -PassThru -RedirectStandardError "$evidence\volume.txt" -RedirectStandardOutput "$evidence\volume-stdout.txt"
        if($p.ExitCode){ throw 'Audio analysis failed' }
        $volume=Get-Content "$evidence\volume.txt" -Raw
        if($volume -notmatch 'max_volume: ([-\d.]+) dB' -or [double]$matches[1] -lt -40){ throw "Loopback audio silent: $volume" }
        ($volume -split "`n" | Where-Object {$_ -match 'mean_volume|max_volume'})
        $p=Start-Process ffmpeg -ArgumentList @('-hide_banner','-i',('"'+$evidence+'\capture\desktop.mp4"'),'-vf','signalstats,metadata=print','-an','-f','null','NUL') -Wait -PassThru -RedirectStandardError "$evidence\video-stats.txt" -RedirectStandardOutput "$evidence\video-stdout.txt"
        if($p.ExitCode){ throw 'Video analysis failed' }
        $luma=@(Get-Content "$evidence\video-stats.txt" | Where-Object {$_ -match 'lavfi.signalstats.YAVG=([\d.]+)'} | ForEach-Object {[double]$matches[1]})
        if(!$luma.Count -or ($luma|Measure-Object -Maximum).Maximum -le 20){ throw 'Desktop capture black or empty' }
        "Video frames=$($luma.Count), YAVG min/max=$(($luma|Measure-Object -Minimum).Minimum)/$(($luma|Measure-Object -Maximum).Maximum)"
    }
    "VERIFIED evidence=$evidence"
} finally { Stop-Transcript | Out-Null }
