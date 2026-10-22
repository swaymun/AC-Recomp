using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
public static class AcrLsa {
    [StructLayout(LayoutKind.Sequential)] struct UnicodeString { public ushort Length, MaximumLength; public IntPtr Buffer; }
    [StructLayout(LayoutKind.Sequential)] struct ObjectAttributes { public int Length; public IntPtr RootDirectory, ObjectName; public uint Attributes; public IntPtr SecurityDescriptor, SecurityQualityOfService; }
    [DllImport("advapi32.dll")] static extern uint LsaOpenPolicy(IntPtr name, ref ObjectAttributes attributes, uint access, out IntPtr handle);
    [DllImport("advapi32.dll")] static extern uint LsaStorePrivateData(IntPtr handle, ref UnicodeString key, ref UnicodeString value);
    [DllImport("advapi32.dll")] static extern uint LsaNtStatusToWinError(uint status);
    [DllImport("advapi32.dll")] static extern uint LsaClose(IntPtr handle);
    static UnicodeString Make(string s) { return new UnicodeString { Length=checked((ushort)(s.Length*2)), MaximumLength=checked((ushort)((s.Length+1)*2)), Buffer=Marshal.StringToHGlobalUni(s) }; }
    static void Check(uint status) { if(status!=0) throw new Win32Exception((int)LsaNtStatusToWinError(status)); }
    public static void Store(string key, string value) {
        ObjectAttributes attributes=new ObjectAttributes(); attributes.Length=Marshal.SizeOf(attributes);
        IntPtr handle; Check(LsaOpenPolicy(IntPtr.Zero, ref attributes, 0x20, out handle));
        UnicodeString k=Make(key), v=Make(value);
        try { Check(LsaStorePrivateData(handle,ref k,ref v)); }
        finally { Marshal.FreeHGlobal(k.Buffer); Marshal.ZeroFreeGlobalAllocUnicode(v.Buffer); LsaClose(handle); }
    }
}
