param([Parameter(Mandatory=$true)][string]$Work)
$ErrorActionPreference='Stop'
$repo=Split-Path -Parent $PSScriptRoot
. (Join-Path $repo 'scripts/bootstrap.ps1')
. (Join-Path $repo 'scripts/applications.ps1')
$resolved=[IO.Path]::GetFullPath($Work)
if (Test-Path -LiteralPath $resolved) {throw 'Use a fresh test work directory.'}
$null=New-Item -ItemType Directory -Path $resolved
function Assert-VE($Condition,[string]$Message) {if (-not $Condition) {throw $Message}}
# No real application detection, downloads, installer launches or user config writes.
$script:scan=@();$script:found=@{}
function Find-VEApplication([string]$Id,$Config) {$script:scan+=$Id;return $script:found[$Id]}
function Test-VEAppInstaller([string]$Id,[string]$Path) {return $false}
function Save-VEAppInstaller([string]$Id,[string]$Root) {throw 'Unexpected download'}
$status=Get-VEApplications $resolved -HostName codex -DeliveryMode mp4 -ActiveHost
Assert-VE $status.ready 'An active Codex chat must not require desktop executables.'
Assert-VE ($script:scan.Count -eq 0) 'Active MP4 must not scan Jianying or a second host.'
$script:found=@{codex='mock codex'};$script:scan=@()
$status=Get-VEApplications $resolved -HostName codex -DeliveryMode mp4
Assert-VE $status.ready 'A Codex-only MP4 machine should be ready.'
Assert-VE (($script:scan -join ',') -eq 'codex') 'Do not scan the unselected DeepSeek host.'
$script:found=@{harness='mock deepseek'};$script:scan=@()
$status=Get-VEApplications $resolved -HostName deepseek -DeliveryMode mp4
Assert-VE $status.ready 'A DeepSeek-only MP4 machine should be ready.'
Assert-VE (($script:scan -join ',') -eq 'harness') 'Do not scan the unselected Codex host.'
$script:found=@{codex='mock codex'};$script:scan=@()
$status=Get-VEApplications $resolved -HostName codex -DeliveryMode editable
Assert-VE (-not $status.ready) 'Editable delivery needs Jianying.'
Assert-VE (($script:scan -join ',') -eq 'codex,jianying') 'Only selected host and editor are required.'
$script:found.jianying='mock editor'
Assert-VE (Get-VEApplications $resolved -HostName codex -DeliveryMode editable).ready 'Reuse an installed editor.'
$old=@{font_path='preserve-font';output_root='preserve-output';custom_setting=42;whisper_model_dir='preserve-model'}
$old | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $resolved 'config.local.json') -Encoding UTF8
$saved=Save-VESelection $resolved codex mp4 chat
Assert-VE ($saved.host -eq 'codex' -and $saved.delivery_mode -eq 'mp4' -and $saved.entry_mode -eq 'chat') 'Selections must persist.'
Assert-VE ($saved.font_path -eq 'preserve-font' -and $saved.output_root -eq 'preserve-output' -and $saved.custom_setting -eq 42 -and $saved.whisper_model_dir -eq 'preserve-model') 'Existing configuration must survive.'
$status=Get-VEApplications $resolved -HostName '' -DeliveryMode '' -ActiveHost
Assert-VE ($status.ready -and $status.delivery_mode -eq 'mp4' -and $status.selected_host -eq 'codex') 'Empty forwarded parameters must use persisted selection.'
foreach ($file in Get-ChildItem (Join-Path $repo 'scripts') -Filter *.ps1) {
    $tokens=$null;$errors=$null
    [Management.Automation.Language.Parser]::ParseFile($file.FullName,[ref]$tokens,[ref]$errors) | Out-Null
    Assert-VE ($errors.Count -eq 0) ('PowerShell parse errors: '+$file.Name)
}
Write-Output 'Passed: host alternatives, MP4 without editor, editable editor scan, selection persistence, PowerShell syntax.'
