# Run elevated. No reboot is performed automatically. Downloads/cache stay on this VM.
[CmdletBinding()]
param([string]$Root = 'C:\acr', [switch]$ConfigureConsole)
. "$PSScriptRoot\common.ps1"
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
if (!(New-Object Security.Principal.WindowsPrincipal($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Run setup from an elevated administrator shell' }
$mutex = New-Object Threading.Mutex($false,'Global\ACRSetupVm')
if (!$mutex.WaitOne(0)) { $mutex.Dispose(); throw 'Another setup_vm.ps1 is already running' }
$UnitRoot = Join-Path $Root 'units\WIN-SETUP-001'
$Cache = Join-Path $UnitRoot 'downloads'
New-Item -ItemType Directory -Force $Cache | Out-Null
$StatusFile = Join-Path $Root 'setup-status.txt'
$LogFile = Join-Path $Root 'setup.log'
$names = 'git','python','visual_studio','clang_cl','cmake','ninja','windows_sdk','dotnet','vulkan','ffmpeg','seven_zip','audio_service','vb_cable','audio_default','audio_capture','vigem','xinput_driver','gamepad_client','sunshine','sunshine_config','firewall','autologon','console','desktop'
$state = [ordered]@{}
foreach ($name in $names) { $state[$name] = 'PENDING' }
function Save-Status {
    $lines = foreach ($key in $state.Keys) { "$key=$($state[$key])" }
    [IO.File]::WriteAllLines("$StatusFile.tmp", [string[]]$lines)
    Move-Item "$StatusFile.tmp" $StatusFile -Force
}
function Capability([string]$Name, [scriptblock]$Action) {
    try { $detail = & $Action; $state[$Name] = 'OK ' + (($detail | Out-String).Trim() -replace '[\r\n]+','; '); Write-Host "$Name OK" }
    catch { $state[$Name] = 'FAIL ' + $_.Exception.Message; Write-Warning "$Name failed: $($_.Exception.Message)" }
    Save-Status
}
Start-Transcript -Path $LogFile -Append | Out-Null
try {
    Save-Status
    # Make tool commands available to subsequent SSH sessions as well as this script.
    $machinePath = [Environment]::GetEnvironmentVariable('Path','Machine')
    foreach ($entry in ($env:Path -split ';' | Where-Object { $_ -and $_ -notin ($machinePath -split ';') })) { $machinePath += ';' + $entry }
    if ($machinePath -ne [Environment]::GetEnvironmentVariable('Path','Machine')) { [Environment]::SetEnvironmentVariable('Path',$machinePath,'Machine') }
    Capability git {
        if (!(Get-Command git -ErrorAction SilentlyContinue)) {
            $installer = Get-GithubAsset 'git-for-windows/git' '^Git-.*-64-bit.exe$'
            Invoke-Checked $installer @('/VERYSILENT','/NORESTART','/SP-','/SUPPRESSMSGBOXES')
            Refresh-Path
        }
        git --version
        if ($LASTEXITCODE) { throw 'Git failed' }
    }
    Capability python {
        if (!(Test-Path 'C:\Program Files\Python312\python.exe')) {
            $installer = Get-Download 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe' 'python-3.12.10-amd64.exe'
            Invoke-Checked $installer @('/quiet','InstallAllUsers=1','PrependPath=1','Include_test=0','TargetDir="C:\Program Files\Python312"')
            Refresh-Path
        }
        python --version
        if ($LASTEXITCODE) { throw 'Python failed' }
    }
    $vs = 'C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools'
    Capability visual_studio {
        $sdkPresent = @(Get-ChildItem 'C:\Program Files (x86)\Windows Kits\10\Include' -Directory -ErrorAction SilentlyContinue | Where-Object { Test-Path "$($_.FullName)\um\Windows.h" }).Count -gt 0
        if (!(Test-Path "$vs\VC\Auxiliary\Build\vcvars64.bat") -or !(Test-Path "$vs\VC\Tools\Llvm\x64\bin\clang-cl.exe") -or !(Test-Path "$vs\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe") -or !(Test-Path "$vs\Common7\IDE\CommonExtensions\Microsoft\CMake\Ninja\ninja.exe") -or !$sdkPresent) {
            $installer = Get-Download 'https://aka.ms/vs/17/release/vs_BuildTools.exe' 'vs_BuildTools.exe'
            Invoke-Checked $installer @('--quiet','--wait','--norestart','--nocache','--installPath',('"'+$vs+'"'),'--add','Microsoft.VisualStudio.Workload.VCTools','--includeRecommended','--add','Microsoft.VisualStudio.Component.VC.Llvm.Clang','--add','Microsoft.VisualStudio.Component.VC.Llvm.ClangToolset','--add','Microsoft.VisualStudio.Component.VC.CMake.Project')
            Refresh-Path
        }
        if (!(Test-Path "$vs\VC\Auxiliary\Build\vcvars64.bat")) { throw 'vcvars64 missing' }
        $vs
    }
    Capability clang_cl { clang-cl --version; if ($LASTEXITCODE) { throw 'clang-cl failed' } }
    Capability cmake { cmake --version; if ($LASTEXITCODE) { throw 'cmake failed' } }
    Capability ninja { ninja --version; if ($LASTEXITCODE) { throw 'ninja failed' } }
    Capability windows_sdk {
        $sdk = @(Get-ChildItem 'C:\Program Files (x86)\Windows Kits\10\Include' -Directory | Where-Object { Test-Path "$($_.FullName)\um\Windows.h" })
        if (!$sdk.Count) { throw 'Windows.h missing' }; $sdk[-1].Name
    }
    Capability dotnet {
        if (!(Get-Command dotnet -ErrorAction SilentlyContinue) -or !(@(& dotnet --list-sdks) -match '^8\.')) {
            $installer = Get-Download 'https://builds.dotnet.microsoft.com/dotnet/scripts/v1/dotnet-install.ps1' 'dotnet-install.ps1'
            & $installer -Channel 8.0 -InstallDir 'C:\Program Files\dotnet' -NoPath
            $machine = [Environment]::GetEnvironmentVariable('Path','Machine')
            if ($machine -notlike '*C:\Program Files\dotnet*') { [Environment]::SetEnvironmentVariable('Path',"$machine;C:\Program Files\dotnet",'Machine') }
            Refresh-Path
        }
        dotnet --list-sdks
        if ($LASTEXITCODE -or !(@(& dotnet --list-sdks) -match '^8\.')) { throw '.NET SDK 8 missing or failed' }
    }
    Capability vulkan {
        $info = & vulkaninfo --summary 2>&1 | Out-String
        if ($LASTEXITCODE -or $info -notmatch 'NVIDIA L4') { throw 'Vulkan NVIDIA L4 unavailable; install the approved NVIDIA driver first' }
        ($info -split "`n" | Where-Object { $_ -match 'deviceName|apiVersion|driverInfo' }).Trim()
    }
    Capability ffmpeg { & "$PSScriptRoot\install_ffmpeg.ps1" -UnitRoot $UnitRoot }
    Capability seven_zip {
        if (!(Test-Path 'C:\Program Files\7-Zip\7z.exe')) {
            $installer = Get-GithubAsset 'ip7z/7zip' '^7z.*-x64.exe$'
            Invoke-Checked $installer @('/S')
        }
        & 'C:\Program Files\7-Zip\7z.exe' | Select-Object -First 3
    }
    Capability audio_service {
        foreach ($service in 'AudioEndpointBuilder','Audiosrv') { Set-Service $service -StartupType Automatic; Start-Service $service }
        (Get-Service Audiosrv).Status
    }
    Capability vb_cable {
        if (!(Get-PnpDevice -PresentOnly -Class MEDIA -ErrorAction SilentlyContinue | Where-Object FriendlyName -match 'VB-Audio Virtual Cable')) {
            $zip = Get-Download 'https://download.vb-audio.com/Download_CABLE/VBCABLE_Driver_Pack45.zip' 'VBCABLE_Driver_Pack45.zip'
            $target = Join-Path $UnitRoot 'vbcable'
            Expand-Archive $zip $target -Force
            # Vendor signed catalog must be trusted for unattended driver installation.
            $catalog = Get-ChildItem $target -Filter '*.cat' -Recurse | Select-Object -First 1
            $sig = Get-AuthenticodeSignature $catalog.FullName
            if ($sig.Status -ne 'Valid') { throw 'VB-Cable catalog signature invalid' }
            $store = New-Object Security.Cryptography.X509Certificates.X509Store('TrustedPublisher','LocalMachine')
            $store.Open('ReadWrite'); $store.Add($sig.SignerCertificate); $store.Close()
            Invoke-Checked (Join-Path $target 'VBCABLE_Setup_x64.exe') @('-i','-h') @(0,1,3010)
        }
        $device = Get-PnpDevice -PresentOnly -Class MEDIA -ErrorAction SilentlyContinue | Where-Object FriendlyName -match 'VB-Audio Virtual Cable'
        if (!$device -or $device.Status -ne 'OK') { throw 'VB-Cable device missing (reboot may be required)' }; $device | Select-Object FriendlyName,Status
    }
    Capability audio_default { & "$PSScriptRoot\audio_default.ps1" -UnitRoot $UnitRoot }
    Capability audio_capture {
        $client = & "$PSScriptRoot\build_audio_capture.ps1" -UnitRoot $UnitRoot | Select-Object -Last 1
        & dotnet $client --help
        if ($LASTEXITCODE) { throw 'WASAPI helper failed' }
    }
    Capability vigem {
        if (!(Get-PnpDevice -PresentOnly | Where-Object FriendlyName -match 'ViGEm|Virtual Gamepad Emulation Bus')) {
            $installer = Get-GithubAsset 'nefarius/ViGEmBus' '^ViGEmBus.*x64_x86(?:_arm64)?\.exe$'
            Invoke-Checked $installer @('/quiet','/norestart')
        }
        $device = Get-PnpDevice -PresentOnly | Where-Object FriendlyName -match 'ViGEm|Virtual Gamepad Emulation Bus'
        if (!$device -or $device.Status -ne 'OK') { throw 'ViGEm device missing' }; $device | Select-Object FriendlyName,Status
    }
    Capability xinput_driver { & "$PSScriptRoot\install_xinput_driver.ps1" -UnitRoot $UnitRoot }
    Capability gamepad_client {
        $venv = Join-Path $UnitRoot 'pad-venv'
        if (!(Test-Path "$venv\Scripts\python.exe")) { python -m venv $venv; if ($LASTEXITCODE) { throw 'venv failed' } }
        $probe = Start-Process "$venv\Scripts\python.exe" -ArgumentList @('-c','"import importlib.metadata; assert importlib.metadata.version(\"vgamepad\") == \"0.1.3\""') -Wait -PassThru -RedirectStandardError "$UnitRoot\pad-import.log" -RedirectStandardOutput "$UnitRoot\pad-import-stdout.log"
        if ($probe.ExitCode) {
            $env:VGAMEPAD_SKIP_VIGEMBUS_INSTALL='true'
            # PyPI 0.1.0 runs an old driver installer during wheel build. This pinned
            # upstream commit explicitly honors VGAMEPAD_SKIP_VIGEMBUS_INSTALL.
            $source = Get-Download 'https://codeload.github.com/yannbouteiller/vgamepad/zip/3f910aa8bbde49a576683db74ad5e4a0879f8a80' 'vgamepad-3f910aa8.zip'
            if ((Get-FileHash $source -Algorithm SHA256).Hash -ne '435b845c8deec33d964fb3e5a97f46ec84608348e7498385589568682cefe3f8') { throw 'vgamepad source checksum mismatch' }
            Invoke-Checked "$venv\Scripts\python.exe" @('-m','pip','install','--no-deps',$source)
        }
        & "$venv\Scripts\python.exe" "$PSScriptRoot\gamepad.py" --self-test
        if ($LASTEXITCODE) { throw 'XInput self-test failed' }
    }
    Capability sunshine {
        if (!(Test-Path 'C:\Program Files\Sunshine\sunshine.exe')) {
            $installer = Get-GithubAsset 'LizardByte/Sunshine' '^Sunshine-Windows-AMD64-installer\.msi$'
            Invoke-Checked msiexec.exe @('/i',('"'+$installer+'"'),'/qn','/norestart',('/l*v "'+$UnitRoot+'\sunshine-install.log"'))
        }
        $svc = Get-Service | Where-Object Name -match '^SunshineService$'
        if (!$svc) { & 'C:\Program Files\Sunshine\scripts\install-service.bat'; $svc = Get-Service SunshineService }
        Set-Service $svc.Name -StartupType Automatic; Start-Service $svc.Name
        $svc.Refresh(); $svc.Status
    }
    Capability sunshine_config {
        & "$PSScriptRoot\sunshine_configure.ps1" -UnitRoot $UnitRoot
        & "$PSScriptRoot\sunshine_pair.ps1" -Check -CredentialFile "$UnitRoot\secrets\sunshine-credential.bin"
    }
    Capability firewall {
        # GCP owner-IP allowlist is managed by the parent. Only host rules here.
        foreach ($rule in @(@('ACR Sunshine TCP','TCP','47984-47990,48010'),@('ACR Sunshine UDP','UDP','48010,47998-48000'))) {
            if (!(Get-NetFirewallRule -DisplayName $rule[0] -ErrorAction SilentlyContinue)) {
                New-NetFirewallRule -DisplayName $rule[0] -Direction Inbound -Action Allow -Protocol $rule[1] -LocalPort ($rule[2] -split ',') -Program 'C:\Program Files\Sunshine\sunshine.exe' | Out-Null
            }
        }
        'host streaming rules present; upstream owner-IP allowlist required'
    }
    if ($ConfigureConsole) { & "$PSScriptRoot\configure_console.ps1" -UnitRoot $UnitRoot; & "$PSScriptRoot\start_console.ps1" }
    Capability autologon {
        $key = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon' -Name AutoAdminLogon,DefaultUserName
        if ($key.AutoAdminLogon -ne '1' -or $key.DefaultUserName -ne 'admin') { throw 'Run once with -ConfigureConsole' }
        'configured for admin; password retained only as LSA secret'
    }
    Capability console {
        $consoleId = Get-ConsoleSessionId
        $explorer = Get-Process explorer -ErrorAction SilentlyContinue | Where-Object SessionId -eq $consoleId
        if (!$explorer) { throw 'No interactive explorer session; reboot after configuring autologon' }; "explorer session=$($explorer[0].SessionId)"
    }
    Capability desktop {
        $gpu = Get-CimInstance Win32_VideoController | Where-Object Name -match 'NVIDIA L4'
        if (!$gpu) { throw 'NVIDIA L4 unavailable' }
        if ($gpu.CurrentHorizontalResolution -ne 1920 -or $gpu.CurrentVerticalResolution -ne 1080) {
            $job = & "$PSScriptRoot\run_interactive.ps1" -FilePath powershell.exe -Arguments "-NoProfile -ExecutionPolicy Bypass -File `"$PSScriptRoot\display.ps1`"" -LogDirectory "$UnitRoot\interactive"
            $deadline = (Get-Date).AddSeconds(30)
            while (!(Test-Path $job.ExitCodeFile) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 250 }
            if (!(Test-Path $job.ExitCodeFile) -or [int](Get-Content $job.ExitCodeFile) -ne 0) { throw "Desktop mode failed; inspect $($job.JobDirectory)" }
            Unregister-ScheduledTask $job.TaskName -Confirm:$false
            $gpu = Get-CimInstance Win32_VideoController | Where-Object Name -match 'NVIDIA L4'
        }
        if ($gpu.CurrentHorizontalResolution -ne 1920 -or $gpu.CurrentVerticalResolution -ne 1080) { throw 'NVIDIA desktop is not 1920x1080' }
        "$($gpu.Name) $($gpu.CurrentHorizontalResolution)x$($gpu.CurrentVerticalResolution); capture proof in verify_vm.ps1"
    }
} finally { Stop-Transcript | Out-Null; $mutex.ReleaseMutex(); $mutex.Dispose() }
if (@($state.Values | Where-Object { $_ -notlike 'OK*' }).Count) { exit 1 }
