param([Parameter(Mandatory=$true)][string]$Root,[Parameter(Mandatory=$true)][string]$Result,[switch]$DownloadMissing,[string]$ConfigPath)
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
[Net.ServicePointManager]::SecurityProtocol=[Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
. (Join-Path $PSScriptRoot 'bootstrap.ps1')
. (Join-Path $PSScriptRoot 'applications.ps1')
try { $status=Get-VEApplications $Root -DownloadMissing:$DownloadMissing -ConfigPath $ConfigPath }
catch { $status=@{ready=$false;apps=@();problems=@($_.Exception.Message);phase='applications'} }
$status | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $Result -Encoding UTF8
if ($status.ready) {exit 0} else {exit 2}
