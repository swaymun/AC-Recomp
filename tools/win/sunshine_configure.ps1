# Bootstrap local-only UI credentials once. The DPAPI file never leaves this VM.
param([string]$UnitRoot='C:\acr\units\WIN-SETUP-001')
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Security
$secretDirectory=Join-Path $UnitRoot 'secrets'
New-Item -ItemType Directory -Force $secretDirectory | Out-Null
& icacls.exe $secretDirectory /inheritance:r /grant:r "${env:COMPUTERNAME}\admin:(OI)(CI)F" 'SYSTEM:(OI)(CI)F' | Out-Null
if ($LASTEXITCODE) { throw 'Cannot protect Sunshine credential directory' }
$credentialFile=Join-Path $secretDirectory 'sunshine-credential.bin'
$configDir='C:\Program Files\Sunshine\config'
if (!(Test-Path $credentialFile)) {
    $bytes=New-Object byte[] 36
    $rng=[Security.Cryptography.RandomNumberGenerator]::Create(); $rng.GetBytes($bytes); $rng.Dispose()
    $secret=[Convert]::ToBase64String($bytes)
    try {
        # Machine-scope DPAPI works with SSH public-key logons before user DPAPI exists.
        $plain=[Text.Encoding]::UTF8.GetBytes($secret)
        try { $encrypted=[Security.Cryptography.ProtectedData]::Protect($plain,$null,[Security.Cryptography.DataProtectionScope]::LocalMachine) }
        finally { [Array]::Clear($plain,0,$plain.Length) }
        [IO.File]::WriteAllBytes("$credentialFile.pending",$encrypted)
        Push-Location 'C:\Program Files\Sunshine'
        try { & '.\sunshine.exe' --creds admin $secret; if ($LASTEXITCODE) { throw 'Sunshine credential bootstrap failed' } }
        finally { Pop-Location }
        Move-Item "$credentialFile.pending" $credentialFile -Force
    } finally { $secret=$null; [Array]::Clear($bytes,0,$bytes.Length) }
}
$config=Join-Path $configDir 'sunshine.conf'
$desired=@{sunshine_name='ACR Windows L4'; origin_web_ui_allowed='pc'; audio_sink='CABLE Input (VB-Audio Virtual Cable)'}
$lines=if(Test-Path $config){ @(Get-Content $config) } else { @() }
$changed=$false
foreach($key in $desired.Keys){
    $entry="$key = $($desired[$key])"
    if($lines -notcontains $entry){ $lines=@($lines|Where-Object{$_ -notmatch "^\s*$key\s*="}) + $entry; $changed=$true }
}
if($changed){ New-Item -ItemType Directory -Force $configDir|Out-Null; $lines|Set-Content $config; Restart-Service SunshineService }
'Sunshine configured; UI restricted to localhost, pair via sunshine_pair.ps1'
