# Run locally on the VM as admin. Pair a PIN displayed by the owner's Moonlight.
[CmdletBinding(DefaultParameterSetName='Pair')]
param([Parameter(Mandatory,ParameterSetName='Pair')][ValidatePattern('^\d{4}$')][string]$Pin,
      [Parameter(Mandatory,ParameterSetName='Check')][switch]$Check,
      [string]$Name='Owner Moonlight',
      [string]$CredentialFile='C:\acr\units\WIN-SETUP-001\secrets\sunshine-credential.bin')
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Security
$plain=[Security.Cryptography.ProtectedData]::Unprotect([IO.File]::ReadAllBytes($CredentialFile),$null,[Security.Cryptography.DataProtectionScope]::LocalMachine)
try { $password=[Text.Encoding]::UTF8.GetString($plain) }
finally { [Array]::Clear($plain,0,$plain.Length) }
if (!('AcrSunshineTls' -as [type])) {
    Add-Type 'using System.Net.Security; public static class AcrSunshineTls { public static readonly RemoteCertificateValidationCallback Callback = delegate { return true; }; }'
}
$previous=[Net.ServicePointManager]::ServerCertificateValidationCallback
$previousProtocol=[Net.ServicePointManager]::SecurityProtocol
try {
    [Net.ServicePointManager]::ServerCertificateValidationCallback = [AcrSunshineTls]::Callback
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $basic = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes('admin:'+$password))
    if ($Check) {
        $response=Invoke-RestMethod -Uri 'https://127.0.0.1:47990/api/clients/list' -Method Get -Headers @{ Authorization="Basic $basic" }
        if (!$response.status) { throw 'Sunshine authenticated API check failed' }
        'Sunshine authenticated localhost API OK'
        return
    }
    $response = Invoke-RestMethod -Uri 'https://127.0.0.1:47990/api/pin' -Method Post -Headers @{ Authorization="Basic $basic" } -ContentType 'application/json' -Body (@{pin=$Pin;name=$Name}|ConvertTo-Json)
    if (!$response.status) { throw 'Sunshine rejected pairing request' }
    'Moonlight PIN accepted by Sunshine'
} finally { [Net.ServicePointManager]::ServerCertificateValidationCallback=$previous; [Net.ServicePointManager]::SecurityProtocol=$previousProtocol; $password=$null; $basic=$null }
