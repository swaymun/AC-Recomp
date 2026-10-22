[CmdletBinding()]
param([string]$OutputDirectory = 'C:\acr\units\WIN-SETUP-001\tone', [int]$Seconds = 8, [switch]$PrepareOnly)
. "$PSScriptRoot\common.ps1"
New-Item -ItemType Directory -Force $OutputDirectory | Out-Null
$wav = Join-Path $OutputDirectory 'tone.wav'
$job = Start-Process ffmpeg -ArgumentList @('-hide_banner','-y','-f','lavfi','-i','sine=frequency=1000:sample_rate=48000','-t',$Seconds,'-ac','2',('"'+$wav+'"')) -Wait -PassThru -NoNewWindow -RedirectStandardError "$OutputDirectory\generate.log" -RedirectStandardOutput "$OutputDirectory\generate-stdout.log"
if ($job.ExitCode) { throw 'Tone generation failed' }
if ($PrepareOnly) { $wav; return }
$player = New-Object System.Media.SoundPlayer $wav
$player.PlaySync()
