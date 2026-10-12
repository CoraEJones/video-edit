param([switch]$Quiet,[string]$ResultPath)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$env:PYTHONUTF8='1'
[Net.ServicePointManager]::SecurityProtocol=[Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
$skillRoot=Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'bootstrap.ps1')
. (Join-Path $PSScriptRoot 'applications.ps1')
$setupLock=$null
$script:VEStage='initializing'
$failureCode='SETUP_FAILED';$applications=$null
try {
    $null=New-Item -ItemType Directory -Path (Join-Path $skillRoot '.runtime') -Force
    try { $setupLock=[IO.File]::Open((Join-Path $skillRoot '.runtime\setup.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None) }
    catch { throw '已有一个自动配置任务正在运行，请等待它完成。' }
    Write-Host '正在先检查剪映和 DeepSeek Harness…'
    Set-VEStage $skillRoot 'applications' '正在检查软件是否已安装…'
    $applications=Get-VEApplications $skillRoot -DownloadMissing
    if (-not $applications.ready) {
        $failureCode='APP_INSTALL_REQUIRED'
        throw ('软件尚未装好。请双击“安装到助手.cmd”，在第一步打开已下载的官方安装包，装好后重新检测。'+($applications.problems -join '；'))
    }
    Write-Host '正在检查环境，优先使用离线组件，缺少时联网下载。'
    $status=Initialize-VideoEdit $skillRoot
    $code=0;$message='运行环境已自动配置完成，可以回到助手继续制作。'
} catch {
    if ($_.Exception.Data['code']) {$failureCode=$_.Exception.Data['code']}
    $stageNames=@{initializing='开始配置';applications='剪映和助手';python='Python';dependencies='剪辑运行组件';ffmpeg='视频处理组件';model='本地语音模型';verify='最终复核'}
    $status=@{ok=$false;code=$failureCode;message=$_.Exception.Message;applications=$applications;stage_label=$stageNames[$script:VEStage];
        stage=$script:VEStage;log=$_.Exception.Data['log'];stdout_log=$_.Exception.Data['stdout_log'];
        next_action='点击“复制诊断信息”发送给助手；网络不可用时可使用运行组件离线版。'}
    $code=2;$message=$status.message;Write-Host $message
}
if ($setupLock) { $setupLock.Dispose() }
$null=New-Item -ItemType Directory -Path (Join-Path $skillRoot '.runtime') -Force
if (-not $ResultPath) { $ResultPath=Join-Path $skillRoot '.runtime\setup-result.json' }
$status | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $ResultPath -Encoding UTF8
$status | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $skillRoot '.runtime\setup-last-result.json') -Encoding UTF8
if (-not $Quiet) {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show($message,'自动配置环境') | Out-Null
}
exit $code
