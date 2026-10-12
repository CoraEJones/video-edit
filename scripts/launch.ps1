param([ValidateSet('wizard','chat','doctor','repair')][string]$Mode,[string]$Package,
    [ValidateSet('auto','codex','deepseek')][string]$HostName,[ValidateSet('mp4','editable')][string]$DeliveryMode,
    [ValidateSet('chat','wizard')][string]$EntryMode,[switch]$ActiveHost)
$ErrorActionPreference='Stop'
$skillRoot=Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'bootstrap.ps1')
. (Join-Path $PSScriptRoot 'applications.ps1')
$config=Read-VEConfig $skillRoot
if (-not $Mode) {$Mode=if ($config.entry_mode) {$config.entry_mode} else {'wizard'}}
if ($Mode -in @('chat','wizard')) {$EntryMode=$Mode}
if ($Mode -eq 'repair') {$DeliveryMode='editable'}
if ($HostName -or $DeliveryMode -or $EntryMode) {$config=Save-VESelection $skillRoot $HostName $DeliveryMode $EntryMode}
$useWindow=($Mode -eq 'wizard')
try {
    $apps=Get-VEApplications $skillRoot -HostName $HostName -DeliveryMode $DeliveryMode -ActiveHost:$ActiveHost
    if (-not $apps.ready) {throw ($apps.problems -join [Environment]::NewLine)}
    $pythonExe=Find-VEPython $skillRoot $config
    $probe=if ($pythonExe) {Read-VEProbe $pythonExe $skillRoot} else {$null}
    if (-not $probe -or @($probe.missing_dependencies).Count -gt 0 -or ($probe.transcription_required -and -not $probe.model) -or -not $probe.font_ready -or -not (Test-VEFFmpeg $probe.ffmpeg $probe.ffprobe)) {
        $setupResult=Join-Path ([IO.Path]::GetTempPath()) ('video-edit-setup-'+[guid]::NewGuid().ToString()+'.json')
        $setupArgs=@('-NoProfile','-ExecutionPolicy','Bypass','-File',(Join-Path $PSScriptRoot 'setup.ps1'),'-Quiet','-ResultPath',$setupResult)
        if ($ActiveHost) {$setupArgs+='-ActiveHost'}
        & powershell.exe @setupArgs
        if ($LASTEXITCODE -ne 0) {throw (Get-Content -Raw -LiteralPath $setupResult -Encoding UTF8 | ConvertFrom-Json).message}
        $pythonExe=(Read-VEConfig $skillRoot).python
    }
    $entry=Join-Path $skillRoot 'scripts/video_tool.py'
    $result=Join-Path ([IO.Path]::GetTempPath()) ('video-edit-result-'+[guid]::NewGuid().ToString()+'.json')
    if ($Mode -in @('doctor','chat')) {& $pythonExe -B -X utf8 $entry doctor --result $result}
    elseif ($Mode -eq 'repair') {& $pythonExe -B -X utf8 $entry export-jianying --relocate $Package --register --result $result}
    else {
        # This is a separate intake workspace, never the chosen delivery directory.
        $requestWorkspace=Join-Path $skillRoot ('.runtime\requests\'+[guid]::NewGuid().ToString())
        & $pythonExe -B -X utf8 $entry analyze --wizard --request-only --output $requestWorkspace --result $result
    }
    $code=$LASTEXITCODE
    $reply=Get-Content -Raw -LiteralPath $result -Encoding UTF8 | ConvertFrom-Json
    if ($reply.code -eq 'CANCELLED') {exit 0}
    if (-not $reply.ok) {$message=if ($reply.message) {$reply.message} else {$reply.data.problems -join [Environment]::NewLine}}
    elseif ($Mode -eq 'repair') {$message='工程已登记，现在打开剪映，在首页选择作品。'}
    elseif ($Mode -eq 'wizard') {$message='需求已保存，请回到助手补充并确认制作单后再开始。'+[Environment]::NewLine+'需求文件：'+$reply.data.request}
    else {$message='环境已就绪。请在所选助手对话中提供素材路径和需求；缺项由助手补问，确认制作单后开始。'}
} catch {$code=2;$message=$_.Exception.Message}
if ($useWindow) {Add-Type -AssemblyName System.Windows.Forms;[System.Windows.Forms.MessageBox]::Show($message,'回忆剪辑') | Out-Null}
else {Write-Output $message}
exit $code
