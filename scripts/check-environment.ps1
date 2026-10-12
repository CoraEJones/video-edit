param([Parameter(Mandatory=$true)][string]$Root,[Parameter(Mandatory=$true)][string]$Result,[ValidateSet('auto','codex','deepseek')][string]$HostName,[ValidateSet('mp4','editable')][string]$DeliveryMode,[ValidateSet('chat','wizard')][string]$EntryMode,[switch]$ActiveHost)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'bootstrap.ps1')
. (Join-Path $PSScriptRoot 'applications.ps1')
try {
    if ($HostName -or $DeliveryMode -or $EntryMode) {$null=Save-VESelection $Root $HostName $DeliveryMode $EntryMode}
    $apps=Get-VEApplications $Root -DeliveryMode $DeliveryMode -HostName $HostName -ActiveHost:$ActiveHost
    if (-not $apps.ready) { throw '所选助手或可编辑工程需要的剪映尚未安装，请返回安装向导的软件准备。' }
    $python=Find-VEPython $Root (Read-VEConfig $Root)
    $probe=if ($python) { Read-VEProbe $python $Root } else { $null }
    $items=New-Object System.Collections.Generic.List[string]
    $needsSetup=$false
    if (-not $probe) { $items.Add('待配置：Python 和运行环境');$needsSetup=$true }
    else {
        $items.Add('已就绪：Python')
        if (@($probe.missing_dependencies).Count) { $items.Add('待配置：剪辑运行组件');$needsSetup=$true } else { $items.Add('已就绪：剪辑运行组件') }
        if (Test-VEFFmpeg $probe.ffmpeg $probe.ffprobe) { $items.Add('已就绪：视频处理组件') } else { $items.Add('待配置：视频处理组件');$needsSetup=$true }
        if ($probe.model) { $items.Add('可用：本地语音模型') } elseif ($probe.transcription_required) { $items.Add('待配置：此次转录需要的本地语音模型');$needsSetup=$true } else {$items.Add('按需准备：本地转录与配音，当前不阻塞')}
        if (-not $probe.font_ready) { $items.Add('待配置：恢复本机可用字体');$needsSetup=$true }
    }
    $ready=$false;$problems=@()
    if (-not $needsSetup) {
        $doctorPath=$Result+'.doctor.json'
        $null=& $python -B -X utf8 (Join-Path $Root 'scripts\video_tool.py') doctor --result $doctorPath
        $doctor=Get-Content -Raw -LiteralPath $doctorPath -Encoding UTF8 | ConvertFrom-Json
        $ready=[bool]$doctor.ok
        if ($ready) { $items.Add('已就绪：所选入口和交付方式') }
        else { $problems=@($doctor.data.problems);if ($doctor.message) {$problems+= $doctor.message} }
    }
    $status=@{ready=$ready;auto_setup_needed=$needsSetup;items=@($items);problems=$problems;python=$python}
} catch { $status=@{ready=$false;auto_setup_needed=$false;items=@();problems=@($_.Exception.Message)} }
$status | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $Result -Encoding UTF8
if ($status.ready) { exit 0 } else { exit 2 }
