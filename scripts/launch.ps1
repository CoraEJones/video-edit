param([ValidateSet('wizard','doctor','repair')][string]$Mode='wizard',[string]$Package)
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Windows.Forms
$skillRoot=Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'bootstrap.ps1')
. (Join-Path $PSScriptRoot 'applications.ps1')
try {
    $apps=Get-VEApplications $skillRoot
    if (-not $apps.ready) {
        Start-Process powershell.exe -WindowStyle Normal -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File',('"'+(Join-Path $PSScriptRoot 'install.ps1')+'"'))
        exit 0
    }
    $pythonExe=Find-VEPython $skillRoot (Read-VEConfig $skillRoot)
    $probe=if ($pythonExe) { Read-VEProbe $pythonExe $skillRoot } else { $null }
    if (-not $probe -or @($probe.missing_dependencies).Count -gt 0 -or -not $probe.model -or -not $probe.font_ready -or -not (Test-VEFFmpeg $probe.ffmpeg $probe.ffprobe)) {
        $setupResult=Join-Path ([IO.Path]::GetTempPath()) ('video-edit-setup-'+[guid]::NewGuid().ToString()+'.json')
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'setup.ps1') -Quiet -ResultPath $setupResult
        if ($LASTEXITCODE -ne 0) {
            $failure=Get-Content -Raw -LiteralPath $setupResult -Encoding UTF8 | ConvertFrom-Json
            throw $failure.message
        }
        $pythonExe=(Read-VEConfig $skillRoot).python
    }
    $entry=Join-Path $skillRoot 'scripts\video_tool.py'
    $result=Join-Path ([IO.Path]::GetTempPath()) ('video-edit-result-'+[guid]::NewGuid().ToString()+'.json')
    if ($Mode -eq 'doctor') { & $pythonExe -B -X utf8 $entry doctor --result $result }
    elseif ($Mode -eq 'repair') { & $pythonExe -B -X utf8 $entry export-jianying --relocate $Package --register --result $result }
    else { & $pythonExe -B -X utf8 $entry analyze --wizard --result $result }
    $code=$LASTEXITCODE
    $reply=Get-Content -Raw -LiteralPath $result -Encoding UTF8 | ConvertFrom-Json
    if ($reply.code -eq 'CANCELLED') { exit 0 }
    if (-not $reply.ok) { $message=if ($reply.message) {$reply.message} else {$reply.data.problems -join [Environment]::NewLine} }
    elseif ($Mode -eq 'doctor') { $message='环境检查通过，可以开始使用。' }
    elseif ($Mode -eq 'repair') { $message='工程已登记，现在打开剪映，在首页选择作品。' }
    else { $message='素材分析完成。请回到剪辑助手继续制作。'+[Environment]::NewLine+'结果位置：'+$reply.data.inventory }
} catch { $code=2;$message=$_.Exception.Message }
[System.Windows.Forms.MessageBox]::Show($message,'回忆剪辑') | Out-Null
exit $code
