param([Parameter(Mandatory=$true)][string]$Root,[Parameter(Mandatory=$true)][string]$Result)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'bootstrap.ps1')
. (Join-Path $PSScriptRoot 'applications.ps1')
try {
    $apps=Get-VEApplications $Root
    if (-not $apps.ready) { throw '剪映或 DeepSeek Harness 尚未安装，请返回安装向导第一步完成软件准备。' }
    $python=Find-VEPython $Root (Read-VEConfig $Root)
    $probe=if ($python) { Read-VEProbe $python $Root } else { $null }
    $items=New-Object System.Collections.Generic.List[string]
    $needsSetup=$false
    if (-not $probe) { $items.Add('待配置：Python 和运行环境');$needsSetup=$true }
    else {
        $items.Add('已就绪：Python')
        if (@($probe.missing_dependencies).Count) { $items.Add('待配置：剪辑运行组件');$needsSetup=$true } else { $items.Add('已就绪：剪辑运行组件') }
        if (Test-VEFFmpeg $probe.ffmpeg $probe.ffprobe) { $items.Add('已就绪：视频处理组件') } else { $items.Add('待配置：视频处理组件');$needsSetup=$true }
        if ($probe.model) { $items.Add('已就绪：本地语音模型') } else { $items.Add('待配置：本地语音模型');$needsSetup=$true }
        if (-not $probe.font_ready) { $items.Add('待配置：恢复本机可用字体');$needsSetup=$true }
    }
    $ready=$false;$problems=@()
    if (-not $needsSetup) {
        $doctorPath=$Result+'.doctor.json'
        $null=& $python -B -X utf8 (Join-Path $Root 'scripts\video_tool.py') doctor --result $doctorPath
        $doctor=Get-Content -Raw -LiteralPath $doctorPath -Encoding UTF8 | ConvertFrom-Json
        $ready=[bool]$doctor.ok
        if ($ready) { $items.Add('已就绪：剪映和图形界面') }
        else { $problems=@($doctor.data.problems);if ($doctor.message) {$problems+= $doctor.message} }
    }
    $status=@{ready=$ready;auto_setup_needed=$needsSetup;items=@($items);problems=$problems;python=$python}
} catch { $status=@{ready=$false;auto_setup_needed=$false;items=@();problems=@($_.Exception.Message)} }
$status | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $Result -Encoding UTF8
if ($status.ready) { exit 0 } else { exit 2 }
