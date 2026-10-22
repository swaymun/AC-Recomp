[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$InstallDir, [switch]$NoDesktopShortcut)
$ErrorActionPreference = 'Stop'
$Kit = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$InstallDir = [IO.Path]::GetFullPath($InstallDir)
foreach ($name in @('astral.exe','run-ac-recomp.ps1','acr-state.json')) {
    if (-not (Test-Path -LiteralPath (Join-Path $InstallDir $name) -PathType Leaf)) {
        throw "Incomplete build: $name is missing. Run setup again."
    }
}
$state = Get-Content -LiteralPath (Join-Path $InstallDir 'acr-state.json') -Raw | ConvertFrom-Json
if (-not $state.stages.app -or -not $state.stages.data) { throw 'Build has not completed app and data stages.' }
$work = Join-Path $InstallDir 'work\windows-launcher'
New-Item -ItemType Directory -Force -Path $work | Out-Null

# Generate an ICO containing PNG images at standard Explorer/taskbar sizes.
# No generated binary is included in the downloadable source kit.
Add-Type -AssemblyName System.Drawing
$source = [Drawing.Image]::FromFile((Join-Path $Kit 'assets\launcher\AC-Recomp.png'))
$images = @()
try {
    foreach ($size in @(16,32,48,256)) {
        $bitmap = New-Object Drawing.Bitmap($size,$size)
        $graphics = [Drawing.Graphics]::FromImage($bitmap)
        $stream = New-Object IO.MemoryStream
        try {
            $graphics.InterpolationMode = [Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
            $graphics.DrawImage($source,0,0,$size,$size)
            $bitmap.Save($stream,[Drawing.Imaging.ImageFormat]::Png)
            $images += ,@{Size=$size; Data=$stream.ToArray()}
        } finally { $graphics.Dispose(); $bitmap.Dispose(); $stream.Dispose() }
    }
} finally { $source.Dispose() }
$iconPath = Join-Path $work 'AC-Recomp.ico'
$stream = [IO.File]::Create($iconPath)
$writer = New-Object IO.BinaryWriter($stream)
try {
    $writer.Write([uint16]0); $writer.Write([uint16]1); $writer.Write([uint16]$images.Count)
    $offset = 6 + 16 * $images.Count
    foreach ($im in $images) {
        $dimension = if ($im.Size -eq 256) {0} else {$im.Size}
        $writer.Write([byte]$dimension); $writer.Write([byte]$dimension)
        $writer.Write([byte]0); $writer.Write([byte]0)
        $writer.Write([uint16]1); $writer.Write([uint16]32)
        $writer.Write([uint32]$im.Data.Length); $writer.Write([uint32]$offset)
        $offset += $im.Data.Length
    }
    foreach ($im in $images) { $writer.Write([byte[]]$im.Data) }
} finally { $writer.Dispose(); $stream.Dispose() }

# Discover the SDK resource compiler with the same checked VS environment as the build.
$python = Join-Path $InstallDir 'venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    # The actual build venv lives in work; retain compatibility with older layouts.
    $python = Join-Path $InstallDir 'work\venv\Scripts\python.exe'
}
if (-not (Test-Path -LiteralPath $python)) { throw 'Build Python environment missing; rerun setup.' }
$envJson = & $python -c 'import sys,json; sys.path.insert(0,sys.argv[1]); import windows_native; print(json.dumps(windows_native.developer_environment()))' (Join-Path $Kit 'tools')
if ($LASTEXITCODE -ne 0) { throw 'Could not discover Windows SDK resource compiler.' }
$dev = $envJson | ConvertFrom-Json
$env:Path = $dev.PATH
$env:INCLUDE = $dev.INCLUDE
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'launcher.rc') -Destination $work -Force
Push-Location $work
try {
    & rc.exe /nologo /fo launcher.res launcher.rc
    if ($LASTEXITCODE -ne 0) { throw 'Icon resource compilation failed.' }
    $compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
    if (-not (Test-Path -LiteralPath $compiler)) { throw '.NET Framework C# compiler missing (required by the launcher).' }
    $candidate = Join-Path $work 'AC-Recomp.exe'
    & $compiler /nologo /target:winexe /platform:x64 /optimize+ /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /win32res:launcher.res "/out:$candidate" (Join-Path $PSScriptRoot 'Launcher.cs')
    if ($LASTEXITCODE -ne 0) { throw 'Launcher compilation failed.' }
} finally { Pop-Location }

# Add the same icon to both private game EXEs. UpdateResource commits each edit atomically.
Add-Type @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
public static class ACRIcon {
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    static extern IntPtr BeginUpdateResource(string file, bool delete);
    [DllImport("kernel32.dll", SetLastError=true)]
    static extern bool UpdateResource(IntPtr update, IntPtr type, IntPtr name, ushort lang, byte[] data, uint size);
    [DllImport("kernel32.dll", SetLastError=true)]
    static extern bool EndUpdateResource(IntPtr update, bool discard);
    public static void Put(string path, byte[][] images, byte[] group) {
        IntPtr update = BeginUpdateResource(path, false);
        if (update == IntPtr.Zero) throw new Win32Exception();
        try {
            for (int i=0; i<images.Length; ++i)
                if (!UpdateResource(update, (IntPtr)3, (IntPtr)(101+i), 0, images[i], (uint)images[i].Length))
                    throw new Win32Exception();
            if (!UpdateResource(update, (IntPtr)14, (IntPtr)1, 0, group, (uint)group.Length))
                throw new Win32Exception();
            IntPtr commit = update; update = IntPtr.Zero;
            if (!EndUpdateResource(commit, false)) throw new Win32Exception();
        } finally { if (update != IntPtr.Zero) EndUpdateResource(update, true); }
    }
}
'@
$groupStream = New-Object IO.MemoryStream
$group = New-Object IO.BinaryWriter($groupStream)
try {
    $group.Write([uint16]0); $group.Write([uint16]1); $group.Write([uint16]$images.Count)
    for ($i=0; $i -lt $images.Count; $i++) {
        $im = $images[$i]
        $dimension = if ($im.Size -eq 256) {0} else {$im.Size}
        $group.Write([byte]$dimension); $group.Write([byte]$dimension)
        $group.Write([byte]0); $group.Write([byte]0)
        $group.Write([uint16]1); $group.Write([uint16]32)
        $group.Write([uint32]$im.Data.Length); $group.Write([uint16](101+$i))
    }
    [byte[][]]$payloads = @($images | ForEach-Object { ,([byte[]]$_.Data) })
    foreach ($binary in @('astral.exe','astral-60fps.exe')) {
        $path = Join-Path $InstallDir $binary
        if (Test-Path -LiteralPath $path) { [ACRIcon]::Put($path,$payloads,$groupStream.ToArray()) }
    }
} finally { $group.Dispose(); $groupStream.Dispose() }

Copy-Item -LiteralPath $candidate -Destination (Join-Path $InstallDir 'AC-Recomp.exe') -Force
$baseRate = if ($state.stages.lift.fps -eq 60) {'60'} else {'30'}
[IO.File]::WriteAllText((Join-Path $InstallDir 'launcher-fps.txt'),$baseRate)
$shell = New-Object -ComObject WScript.Shell
$locations = @([Environment]::GetFolderPath('Programs'))
if (-not $NoDesktopShortcut) { $locations += [Environment]::GetFolderPath('DesktopDirectory') }
foreach ($folder in $locations) {
    if (-not $folder) { throw 'Could not locate the current user shortcut folder.' }
    New-Item -ItemType Directory -Force -Path $folder | Out-Null
    $shortcut = $shell.CreateShortcut((Join-Path $folder 'AC-Recomp.lnk'))
    $shortcut.TargetPath = Join-Path $InstallDir 'AC-Recomp.exe'
    $shortcut.WorkingDirectory = $InstallDir
    $shortcut.IconLocation = (Join-Path $InstallDir 'AC-Recomp.exe') + ',0'
    $shortcut.Description = 'Play your locally built copy of AC-Recomp'
    $shortcut.Save()
    Write-Host "Shortcut created: $folder\AC-Recomp.lnk"
}
Write-Host "Launcher and game icons installed: $InstallDir"
