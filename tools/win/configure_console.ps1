# Creates a fresh VM-only password. Never echoes or serializes it to disk.
[CmdletBinding()]
param([string]$UnitRoot = 'C:\acr\units\WIN-SETUP-001')
$ErrorActionPreference = 'Stop'
$marker = Join-Path $UnitRoot 'autologon-configured'
if (Test-Path $marker) { return }
Add-Type -Path "$PSScriptRoot\lsa.cs"
$bytes = New-Object byte[] 48
$rng = [Security.Cryptography.RandomNumberGenerator]::Create()
$rng.GetBytes($bytes); $rng.Dispose()
$password = [Convert]::ToBase64String($bytes) + 'aA1!'
try {
    Set-LocalUser -Name admin -Password (ConvertTo-SecureString $password -AsPlainText -Force) -PasswordNeverExpires $true
    [AcrLsa]::Store('DefaultPassword', $password)
    $key = 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon'
    New-ItemProperty $key -Name AutoAdminLogon -Value '1' -PropertyType String -Force | Out-Null
    New-ItemProperty $key -Name DefaultUserName -Value 'admin' -PropertyType String -Force | Out-Null
    New-ItemProperty $key -Name DefaultDomainName -Value $env:COMPUTERNAME -PropertyType String -Force | Out-Null
    Remove-ItemProperty $key -Name DefaultPassword -ErrorAction SilentlyContinue
    # Server legal notices can suppress autologon; do not alter domain policy.
    Set-Content $marker 'admin autologon configured via LSA; reboot required'
} finally { $password = $null; [Array]::Clear($bytes,0,$bytes.Length) }
