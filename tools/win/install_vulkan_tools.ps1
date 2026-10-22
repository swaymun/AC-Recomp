# Optional SDK for the real-window vkcube probe; NVIDIA driver provides the runtime.
param([string]$UnitRoot='C:\acr\units\WIN-SETUP-001')
. "$PSScriptRoot\common.ps1"
$Cache=Join-Path $UnitRoot 'downloads'
New-Item -ItemType Directory -Force $Cache | Out-Null
$target=Join-Path $UnitRoot 'vulkan-sdk'
if (!(Test-Path "$target\Bin\vkcube.exe")) {
    $installer=Get-Download 'https://vulkan.lunarg.com/sdk/download/1.4.363.0/windows/vulkansdk-windows-X64-1.4.363.0.exe' 'vulkansdk-windows-X64-1.4.363.0.exe'
    if ((Get-FileHash $installer -Algorithm SHA256).Hash -ne '94a82d378f7a5e3e54c9db7d2fb7016af136e14ac0a18dbf0f2f67a36352d141') { throw 'SDK checksum mismatch' }
    Invoke-Checked $installer @('--root', $target, '--accept-licenses','--default-answer','--confirm-command','install')
}
if (!(Test-Path "$target\Bin\vkcube.exe")) { throw 'vkcube missing after SDK installation' }
"$target\Bin\vkcube.exe"
