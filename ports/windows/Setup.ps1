# Source-only setup. Inputs and generated game files stay on the player's PC.
[CmdletBinding()]
param(
    [string]$Nsp,
    [string]$Keys,
    [Alias('title-keys')][string]$TitleKeys,
    [Alias('import-dir')][string]$ImportDir,
    [Alias('control-receipt')][string]$ControlReceipt,
    [Alias('spirv-dir')][string]$SpirvDir,
    [string]$Fonts,
    [Alias('out')][string]$InstallDir,
    [ValidateSet('30','60')][string]$Fps,
    [ValidateRange(1,128)][int]$Jobs = 1,
    [switch]$NonInteractive,
    [switch]$NoDesktopShortcut,
    [switch]$CheckOnly,
    [ValidateSet('control')][string]$ToStage
)
$ErrorActionPreference = 'Stop'
$Kit = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))

function Set-PythonUtf8 {
    # Python's redirected output and default file encoding otherwise use cp1252
    # on many PCs. Console.OutputEncoding explicitly selects PowerShell 5's
    # native stdout/stderr decoder; OutputEncoding covers pipeline input.
    $env:PYTHONUTF8 = '1'
    $env:PYTHONIOENCODING = 'utf-8'
    [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
    $script:OutputEncoding = [Console]::OutputEncoding
}
Set-PythonUtf8

function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' +
        [Environment]::GetEnvironmentVariable('Path','User') + ';' + $env:Path
}
function Find-Python {
    foreach ($candidate in @('python.exe', 'python3.exe', 'py.exe')) {
        $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($cmd -and $cmd.Source -notlike '*\WindowsApps\*') {
            # Get the actual interpreter, so the build never depends on a py launcher flag.
            $found = & $cmd.Source -c 'import sys; sys.exit(1) if sys.version_info < (3,11) or sys.maxsize < 2**32 else None; print(sys.executable)' 2>$null
            if ($LASTEXITCODE -eq 0 -and $found -and (Test-Path -LiteralPath "$found")) { return "$found" }
        }
    }
    return $null
}
function Offer-Install([string]$Name, [string]$Id, [string]$Url, [string]$Override = '') {
    Write-Host "`n$Name is missing. Official installer: $Url"
    if ($NonInteractive -or $CheckOnly) { throw "Install $Name, then rerun setup." }
    if (-not (Get-Command winget.exe -ErrorAction SilentlyContinue)) {
        throw "WinGet is unavailable. Install $Name from $Url, then close and reopen setup."
    }
    $arguments = @('install','--exact','--id',$Id,'--source','winget','--interactive')
    if ($Override) { $arguments += @('--override',$Override) }
    Write-Host ('winget ' + ($arguments -join ' '))
    if ((Read-Host 'Install this prerequisite now? [y/N]') -notmatch '^(y|yes)$') {
        throw 'Installation declined. Run setup again when the prerequisite is installed.'
    }
    & winget.exe @arguments
    if ($LASTEXITCODE -ne 0) { throw "Installer returned $LASTEXITCODE. Finish installation and rerun setup." }
    Refresh-Path
}
function Ask-Path([string]$Value, [string]$Prompt, [bool]$Optional = $false) {
    if (-not $Value -and -not $NonInteractive) { $Value = Read-Host $Prompt }
    if (-not $Value) {
        if ($Optional) { return '' }
        throw "$Prompt is required."
    }
    $Value = $Value.Trim().Trim('"')
    if (-not (Test-Path -LiteralPath $Value)) { throw "Path not found: $Value" }
    return [IO.Path]::GetFullPath($Value)
}
function Invoke-SetupBuild([string]$Python, [string[]]$Arguments) {
    # Windows PowerShell 5 represents native stderr (including benign Git progress) as
    # ErrorRecords when redirected. The process exit code, not that stream, decides success.
    if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw 'Build interpreter is missing. Rerun setup.' }
    Set-PythonUtf8
    $previous = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & $Python @Arguments 2>&1 | ForEach-Object { Write-Host "$_" }
        return $LASTEXITCODE
    } finally { $ErrorActionPreference = $previous }
}

try {
    Write-Host "`nAC-Recomp Setup`n==============="
    Write-Host 'Build a private Windows copy from your own Astral Chain 1.0.0 dump.'
    Write-Host 'No game data is included. Internet is needed to download build dependencies.'
    Write-Host 'Requires an AVX2-capable x64 CPU and a Vulkan 1.3+ graphics driver.'
    Write-Host 'Keep at least 25 GB free; the first build can take an hour or more.'
    Write-Host ''
    Write-Host 'Select your own NSP dump and console keys. They stay on this PC.'
    Write-Host 'Keep the extracted kit and build folder in place after setup.'
    if (-not [Environment]::Is64BitOperatingSystem -or $env:PROCESSOR_ARCHITECTURE -eq 'ARM64') {
        throw 'Windows x64 is required.'
    }
    if (-not $CheckOnly) {
        if ($ImportDir) {
            if ($Nsp -or $Keys -or $TitleKeys) { throw 'Do not combine an import folder with dump/key options.' }
            $ImportDir = Ask-Path $ImportDir 'Imported game folder (contains exefs, analysis and extract)'
            $ControlReceipt = Ask-Path $ControlReceipt 'Original control receipt (receipt.json)'
        } else {
            if ($ControlReceipt) { throw 'A control receipt requires an import folder.' }
            $Nsp = Ask-Path $Nsp 'Astral Chain 1.0.0 NSP dump'
            $Keys = Ask-Path $Keys 'Console prod.keys file'
            $TitleKeys = Ask-Path $TitleKeys 'Title keys file (optional; Enter to skip)' $true
        }
        $SpirvDir = Ask-Path $SpirvDir 'Translated shader folder (optional; Enter to translate on Windows)' $true
        $Fonts = Ask-Path $Fonts 'Shared font folder (optional; Enter for replacement fonts)' $true
        if (-not $InstallDir) {
            $default = Join-Path $env:LOCALAPPDATA 'AC-Recomp\build'
            if (-not $NonInteractive) { $InstallDir = Read-Host "Install folder [Enter for $default]" }
            if (-not $InstallDir) { $InstallDir = $default }
        }
        $InstallDir = [IO.Path]::GetFullPath($InstallDir.Trim().Trim('"'))
    }
    $Python = Find-Python
    if (-not $Python) {
        Offer-Install '64-bit Python 3.11 or newer' 'Python.Python.3.12' 'https://www.python.org/downloads/windows/'
        $Python = Find-Python
        if (-not $Python) { throw 'Python still unavailable. Close and reopen setup after installing Python.' }
    }
    $checkArgs = @((Join-Path $Kit 'tools\acr_setup_cmd.py'),'check','--windows')
    if ($SpirvDir) { $checkArgs += '--reuse-shaders' }
    $rows = & $Python @checkArgs | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { throw 'Could not check prerequisites.' }
    foreach ($row in $rows) {
        $status = if ($row.ok) {'OK'} elseif ($row.required) {'MISSING'} else {'OPTIONAL'}
        Write-Host ("[{0}] {1}: {2}" -f $status,$row.title,$row.detail)
        if ($row.ok -or -not $row.required) { continue }
        switch ($row.id) {
            'git' { Offer-Install $row.title 'Git.Git' 'https://git-scm.com/download/win' }
            'vs' {
                Offer-Install $row.title 'Microsoft.VisualStudio.2022.BuildTools' 'https://visualstudio.microsoft.com/downloads/' '--wait --passive --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended --add Microsoft.VisualStudio.Component.VC.Llvm.Clang --add Microsoft.VisualStudio.Component.VC.Llvm.ClangToolset'
            }
            'dotnet' { Offer-Install $row.title 'Microsoft.DotNet.SDK.10' 'https://dotnet.microsoft.com/download/dotnet/10.0' }
            default { throw $row.detail }
        }
    }
    # Do not optimistically continue just because an installer exited successfully.
    $rows = & $Python @checkArgs | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0 -or @($rows | Where-Object { $_.required -and -not $_.ok }).Count) {
        throw 'Some prerequisites are still missing. Close and reopen setup after installation.'
    }
    if ($CheckOnly) { Write-Host 'Prerequisite checks passed.'; exit 0 }
    Write-Host "`nBuild location: $InstallDir"
    Write-Host "Compiler jobs: $Jobs (default 1 to limit memory use; override with -Jobs)."
    Write-Host 'Build logs and resumable progress are saved there. Ctrl+C stops the build.'
    if (-not $NonInteractive -and (Read-Host 'Start building now? [y/N]') -notmatch '^(y|yes)$') {
        throw 'Build cancelled before starting.'
    }
    $buildArgs = @((Join-Path $Kit 'tools\acr_setup_cmd.py'),'run','--windows',
        '--out',$InstallDir,'--python',$Python)
    if ($ImportDir) { $buildArgs += @('--import-dir',$ImportDir,'--control-receipt',$ControlReceipt) }
    else {
        $buildArgs += @('--nsp',$Nsp,'--keys',$Keys)
        if ($TitleKeys) { $buildArgs += @('--title-keys',$TitleKeys) }
    }
    if ($ToStage) { $buildArgs += @('--to-stage',$ToStage) }
    if ($SpirvDir) { $buildArgs += @('--spirv-dir',$SpirvDir) }
    if ($Fonts) { $buildArgs += @('--fonts',$Fonts) }
    if ($Fps) { $buildArgs += @('--fps',$Fps) }
    if ($Jobs -gt 0) { $buildArgs += @('--jobs',"$Jobs") }
    if ($NoDesktopShortcut) { $buildArgs += '--no-desktop-shortcut' }
    $buildResult = Invoke-SetupBuild -Python $Python -Arguments $buildArgs
    if ($buildResult -ne 0) { throw "Build failed ($buildResult). Fix the error above and rerun the same setup to resume." }
    if ($ToStage) { Write-Host 'Import and control metadata verified. Rerun without -ToStage to build.'; exit 0 }
    Write-Host "`nReady. Open AC-Recomp from the Start menu or your desktop."
    Write-Host 'Do not move or share the build or imported game folders. Your saves stay in build\data\user.'
    exit 0
} catch {
    Write-Host "`nSetup stopped: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
