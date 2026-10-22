# Server editions can omit the Xbox 360 function driver that ViGEm needs.
# Use Microsoft's signed Update Catalog package; never disable signature enforcement.
param([string]$UnitRoot='C:\acr\units\WIN-SETUP-001')
. "$PSScriptRoot\common.ps1"
if ((Test-Path "$env:windir\System32\drivers\xusb22.sys") -or (Get-ChildItem "$env:windir\System32\DriverStore\FileRepository" -Filter 'xusb21.inf_amd64*' -Directory -ErrorAction SilentlyContinue)) { 'Xbox 360 function driver already present'; return }
$Cache=Join-Path $UnitRoot 'downloads'
New-Item -ItemType Directory -Force $Cache | Out-Null
$cab=Get-Download 'https://catalog.s.download.windowsupdate.com/msdownload/update/driver/drvs/2012/12/20258516_288ade5984a88d007b5b3249e9d36ac3fb15f713.cab' 'microsoft-xusb21.cab'
if((Get-FileHash $cab -Algorithm SHA256).Hash -ne 'f4ce2ec6fe1a256872c7b40ad6f7b672390b0d68aa71e0884a529562da08771d'){throw 'Microsoft XUSB package checksum mismatch'}
$target=Join-Path $UnitRoot 'xusb-driver'
New-Item -ItemType Directory -Force $target | Out-Null
Invoke-Checked expand.exe @('-F:*',$cab,$target)
# The root INF references the signed root catalog. A historical unused x64
# catalog is also in this cabinet; pnputil validates the referenced catalog.
$sig=Get-AuthenticodeSignature "$target\xusb21.cat"
if($sig.Status -ne 'Valid'){throw "Microsoft XUSB catalog signature: $($sig.Status)"}
Invoke-Checked pnputil.exe @('/add-driver',"$target\xusb21.inf",'/install')
'Signed Microsoft Xbox 360 function-driver package staged'
