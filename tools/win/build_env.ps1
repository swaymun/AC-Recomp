# Dot-source before building: . .\tools\win\build_env.ps1
. "$PSScriptRoot\common.ps1"
$vcvars='C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat'
if (!(Test-Path $vcvars)) { throw 'VS C++ tools missing; run setup_vm.ps1' }
$lines = & cmd.exe /d /c "call `"$vcvars`" >nul && set"
if ($LASTEXITCODE) { throw 'vcvars64 failed' }
foreach ($line in $lines) {
    if ($line -match '^([^=]+)=(.*)$') { [Environment]::SetEnvironmentVariable($matches[1],$matches[2],'Process') }
}
