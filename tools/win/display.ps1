# Apply a supported primary-display mode in the interactive console.
param([int]$Width=1920, [int]$Height=1080)
$ErrorActionPreference='Stop'
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class AcrDisplay {
 [StructLayout(LayoutKind.Sequential,CharSet=CharSet.Unicode)] struct DevMode {
  [MarshalAs(UnmanagedType.ByValTStr,SizeConst=32)] public string device;
  public ushort spec,driver,size,extra; public uint fields;
  public int x,y; public uint orientation,fixedOutput;
  public short color,duplex,yres,tt,collate;
  [MarshalAs(UnmanagedType.ByValTStr,SizeConst=32)] public string form;
  public ushort logPixels; public uint bits,width,height,flags,frequency,icmMethod,icmIntent,media,dither,reserved1,reserved2,panningWidth,panningHeight;
 }
 [DllImport("user32.dll",CharSet=CharSet.Unicode)] static extern bool EnumDisplaySettings(string name,int mode,ref DevMode dm);
 [DllImport("user32.dll",CharSet=CharSet.Unicode)] static extern int ChangeDisplaySettings(ref DevMode dm,uint flags);
 public static string Set(int width,int height) {
  var dm=new DevMode(); dm.size=(ushort)Marshal.SizeOf(dm);
  if(!EnumDisplaySettings(null,-1,ref dm)) throw new Exception("No current display mode");
  if(dm.width==width && dm.height==height) return "Already "+width+"x"+height;
  dm.width=(uint)width; dm.height=(uint)height; dm.fields=0x180000;
  int result=ChangeDisplaySettings(ref dm,1);
  if(result!=0) throw new Exception("ChangeDisplaySettings returned "+result);
  return width+"x"+height;
 }
}
'@
[AcrDisplay]::Set($Width,$Height)
Get-CimInstance Win32_VideoController | Select-Object Name,CurrentHorizontalResolution,CurrentVerticalResolution
