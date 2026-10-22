# Synthetic tone only: keep default-device playback active across the complete capture.
param([Parameter(Mandatory)][string]$ToneFile,[Parameter(Mandatory)][string]$OutputDirectory,[int]$Seconds=8, [int]$WindowPID=0)
$ErrorActionPreference='Stop'
if ($WindowPID) {
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class AcrProbeWindow {
 delegate bool Callback(IntPtr hwnd,IntPtr parameter);
 [DllImport("user32.dll")] static extern bool EnumWindows(Callback callback,IntPtr parameter);
 [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr hwnd,out uint pid);
 [DllImport("user32.dll")] static extern bool ShowWindow(IntPtr hwnd,int command);
 [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr hwnd);
 public static bool Show(uint pid) {
  bool found=false;
  EnumWindows(delegate(IntPtr hwnd,IntPtr p) {uint owner;GetWindowThreadProcessId(hwnd,out owner);if(owner==pid){ShowWindow(hwnd,9);SetForegroundWindow(hwnd);found=true;}return true;},IntPtr.Zero);
  return found;
 }
}
'@
    if (![AcrProbeWindow]::Show($WindowPID)) { throw 'No Vulkan window for the supplied probe PID' }
}
$player=New-Object System.Media.SoundPlayer $ToneFile
$player.Load()
$player.PlayLooping()
try { & "$PSScriptRoot\capture.ps1" -Seconds $Seconds -OutputDirectory $OutputDirectory }
finally { $player.Stop(); $player.Dispose() }
