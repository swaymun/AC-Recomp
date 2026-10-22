# Start configured autologon without rebooting or interrupting session-0 SSH uploads.
# Refuses to log off a console that already has a user.
param([int]$TimeoutSeconds=45)
. "$PSScriptRoot\common.ps1"
if (!('AcrConsoleUser' -as [type])) {
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class AcrConsoleUser {
 [DllImport("wtsapi32.dll",CharSet=CharSet.Unicode)] static extern bool WTSQuerySessionInformation(IntPtr server,int session,int info,out IntPtr buffer,out int bytes);
 [DllImport("wtsapi32.dll")] static extern void WTSFreeMemory(IntPtr buffer);
 public static string Name(int session) {
  IntPtr buffer; int bytes;
  if(!WTSQuerySessionInformation(IntPtr.Zero,session,5,out buffer,out bytes)) throw new System.ComponentModel.Win32Exception();
  try{return Marshal.PtrToStringUni(buffer);} finally {WTSFreeMemory(buffer);}
 }
}
'@
}
$consoleId=Get-ConsoleSessionId
$user=[AcrConsoleUser]::Name($consoleId)
if($user){
    if($user -ne 'admin'){throw "Console already belongs to another user; refusing logoff"}
    "Console already logged in as admin (session=$consoleId)"
    return
}
$key='HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon'
$settings=Get-ItemProperty $key -Name AutoAdminLogon,DefaultUserName
if($settings.AutoAdminLogon -ne '1' -or $settings.DefaultUserName -ne 'admin'){throw 'Configure autologon before starting the console'}
New-ItemProperty $key -Name ForceAutoLogon -Value '1' -PropertyType String -Force | Out-Null
& logoff.exe $consoleId
if($LASTEXITCODE){throw 'Empty console reset failed'}
$deadline=(Get-Date).AddSeconds($TimeoutSeconds)
do {
    Start-Sleep -Milliseconds 500
    $consoleId=Get-ConsoleSessionId
    $explorer=Get-Process explorer -ErrorAction SilentlyContinue | Where-Object SessionId -eq $consoleId
} while(!$explorer -and (Get-Date) -lt $deadline)
if(!$explorer){throw 'Autologon did not start a console desktop; reboot when other workers are ready'}
"Console started (session=$consoleId)"
