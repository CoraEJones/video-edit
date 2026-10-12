param([ValidateSet('Choose','DeepSeek','Codex','Both')][string]$Target='Choose',[switch]$Quiet)
$ErrorActionPreference='Stop'
$script:skillRoot=Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'install-files.ps1')
. (Join-Path $PSScriptRoot 'bootstrap.ps1')
. (Join-Path $PSScriptRoot 'applications.ps1')
if ($Quiet) {
    if ($Target -eq 'Choose') { throw '静默安装需要指定 Target。' }
    Install-VESkill $script:skillRoot $Target | Write-Output
    exit 0
}
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[Windows.Forms.Application]::EnableVisualStyles()
$script:form=New-Object Windows.Forms.Form
$form.Text='回忆剪辑 · 安装向导';$form.ClientSize=New-Object Drawing.Size(760,620)
$form.MinimumSize=$form.Size;$form.StartPosition='CenterScreen';$form.AutoScaleMode='Dpi'
$form.BackColor=[Drawing.Color]::FromArgb(245,247,251);$form.Font=New-Object Drawing.Font('Microsoft YaHei UI',14)
function New-VELabel($Parent,[string]$Text,[int]$X,[int]$Y,[int]$W,[int]$H,[int]$Size=14) {
    $c=New-Object Windows.Forms.Label;$c.Text=$Text;$c.SetBounds($X,$Y,$W,$H)
    $c.Font=New-Object Drawing.Font('Microsoft YaHei UI',$Size);$c.ForeColor=[Drawing.Color]::FromArgb(27,50,65)
    $Parent.Controls.Add($c);return $c
}
function New-VEButton($Parent,[string]$Text,[int]$X,[int]$Y,[int]$W=220) {
    $c=New-Object Windows.Forms.Button;$c.Text=$Text;$c.SetBounds($X,$Y,$W,52)
    $c.FlatStyle='Flat';$c.BackColor=[Drawing.Color]::White;$Parent.Controls.Add($c);return $c
}
$script:steps=New-VELabel $form '第 1 / 4 步：准备软件' 30 20 700 36 15
$script:heading=New-VELabel $form '先选择你使用的助手' 30 65 700 56 25
$script:body=New-Object Windows.Forms.Panel;$body.SetBounds(30,130,700,385);$form.Controls.Add($body)
$script:back=New-VEButton $form '上一步' 30 545 150
$script:next=New-VEButton $form '下一步' 565 545 165
$script:page=0;$script:installedRoots=@();$script:ready=$false;$script:process=$null;$script:selectedIndex=0
$script:appsReady=$false;$script:apps=@();$script:appButtons=@{}
$script:timer=New-Object Windows.Forms.Timer;$timer.Interval=500

function Set-VEBusy([bool]$Busy) {
    $script:back.Enabled=(-not $Busy -and $script:page -gt 0)
    $script:next.Enabled=(-not $Busy -and (($script:page -eq 0 -and $script:appsReady) -or ($script:page -eq 1 -and $script:installedRoots.Count -gt 0) -or ($script:page -eq 2 -and $script:ready) -or $script:page -eq 3))
    if ($script:page -eq 2) { $script:checkButton.Enabled=-not $Busy;$script:autoButton.Enabled=-not $Busy;$script:bar.Visible=$Busy }
    if ($script:page -eq 0) {
        $script:checkButton.Enabled=-not $Busy;$script:bar.Visible=$Busy
        foreach ($button in $script:appButtons.Values) {$button.Enabled=-not $Busy}
    }
}
function Start-VEAppsWorker {
    if ($script:process -and -not $script:process.HasExited) { return }
    $script:appsReady=$false;$script:ready=$false
    foreach ($button in $script:appButtons.Values) {$button.Visible=$false}
    $script:resultPath=Join-Path ([IO.Path]::GetTempPath()) ('video-edit-apps-'+[guid]::NewGuid().ToString()+'.json')
    $script:logPath=$script:resultPath+'.log';$script:errorPath=$script:resultPath+'.error.log'
    $worker=Join-Path $script:skillRoot 'scripts\application-worker.ps1'
    $arguments=@('-NoProfile','-ExecutionPolicy','Bypass','-File',('"'+$worker+'"'),'-Root',('"'+$script:skillRoot+'"'),'-Result',('"'+$script:resultPath+'"'),'-DownloadMissing')
    try {
        $script:detail.Text='正在检查剪映和 DeepSeek Harness，缺少时会自动下载官方安装包。'
        $script:process=Start-Process powershell.exe -ArgumentList $arguments -WindowStyle Hidden -PassThru -RedirectStandardOutput $script:logPath -RedirectStandardError $script:errorPath
        Set-VEBusy $true;$script:timer.Start()
    } catch { $script:detail.Text=$_.Exception.Message;Set-VEBusy $false }
}
function Open-VEAppInstaller([string]$Id) {
    $app=@($script:apps | Where-Object {$_.id -eq $Id})[0]
    try {
        if ($app.installer) {
            if (-not (Test-VEAppInstaller $Id $app.installer)) { throw '安装包签名复核未通过，请重新检测下载。' }
            Start-Process -FilePath $app.installer -WindowStyle Normal
            $script:appButtons[$Id].Enabled=$false
            $script:detail.AppendText([Environment]::NewLine+'请按软件安装窗口完成安装，再点“已安装，重新检测”。')
        } else { Start-Process -FilePath (Get-VEAppSpec $Id).homepage }
    } catch { $script:detail.Text=$_.Exception.Message }
}
function Start-VEWorker([string]$Mode) {
    if ($script:process -and -not $script:process.HasExited) { return }
    $script:ready=$false;$script:detail.Text='正在检查…';$script:autoButton.Visible=$false
    $script:activeMode=$Mode;$script:diagnosticButton.Visible=$false;$script:lastDiagnostic=''
    $script:resultPath=Join-Path ([IO.Path]::GetTempPath()) ('video-edit-install-'+[guid]::NewGuid().ToString()+'.json')
    $script:logPath=$script:resultPath+'.log';$script:errorPath=$script:resultPath+'.error.log'
    $worker=Join-Path $script:installedRoots[0] 'scripts\installer-worker.ps1'
    $arguments=@('-NoProfile','-ExecutionPolicy','Bypass','-File',('"'+$worker+'"'),'-Mode',$Mode,'-Root',('"'+$script:installedRoots[0]+'"'),'-Result',('"'+$script:resultPath+'"'))
    if ($script:installedRoots.Count -gt 1) { $arguments+=@('-AlsoRoot',('"'+$script:installedRoots[1]+'"')) }
    try {
        $script:process=Start-Process powershell.exe -ArgumentList $arguments -WindowStyle Hidden -PassThru -RedirectStandardOutput $script:logPath -RedirectStandardError $script:errorPath
        $script:detail.Text=if ($Mode -eq 'setup') {'正在自动配置。有离线组件包时直接使用，否则联网下载。'} else {'正在检查本机环境，请稍候。'}
        Set-VEBusy $true;$script:timer.Start()
    } catch { $script:detail.Text=$_.Exception.Message;Set-VEBusy $false }
}
function Show-VEPage {
    $script:body.Controls.Clear()
    $script:steps.Text=@('第 1 / 4 步：准备软件','第 2 / 4 步：安装到助手','第 3 / 4 步：准备运行环境','第 4 / 4 步：可以开始了')[$script:page]
    $script:next.Text=if ($script:page -eq 3) {'完成'} else {'下一步'}
    if ($script:page -eq 0) {
        $script:heading.Text='先准备剪映和 DeepSeek Harness'
        $null=New-VELabel $body '已有的软件直接使用。缺少时会下载官方安装包，点下面的安装按钮即可。' 0 0 690 60
        $script:checkButton=New-VEButton $body '已安装，重新检测' 0 65 260
        $checkButton.add_Click({Start-VEAppsWorker})
        $script:appButtons=@{}
        $script:appButtons.jianying=New-VEButton $body '安装剪映专业版' 0 132 290
        $script:appButtons.harness=New-VEButton $body '安装 DeepSeek Harness' 310 132 370
        $script:appButtons.jianying.add_Click({Open-VEAppInstaller 'jianying'})
        $script:appButtons.harness.add_Click({Open-VEAppInstaller 'harness'})
        foreach ($button in $script:appButtons.Values) {$button.Visible=$false}
        $script:bar=New-Object Windows.Forms.ProgressBar;$bar.SetBounds(0,198,690,12);$bar.Style='Marquee';$bar.Visible=$false;$body.Controls.Add($bar)
        $script:detail=New-Object Windows.Forms.TextBox;$detail.Multiline=$true;$detail.ReadOnly=$true;$detail.ScrollBars='Vertical'
        $detail.SetBounds(0,228,690,145);$detail.BackColor=$form.BackColor;$detail.BorderStyle='None';$body.Controls.Add($detail)
        $detail.Text=if ($script:appsReady) {'两个软件已找到，可以点击“下一步”。'} else {'正在准备软件检测…'}
    } elseif ($script:page -eq 1) {
        $script:heading.Text='先选择你使用的助手'
        $null=New-VELabel $body '选一个你平时使用的助手，再点击“安装”。已有版本会保留配置并更新。' 0 0 690 62
        $script:choice=New-Object Windows.Forms.ComboBox;$choice.DropDownStyle='DropDownList';$choice.SetBounds(0,86,440,42)
        $null=$choice.Items.AddRange(@('DeepSeek Harness','Codex','两个助手都安装'));$choice.SelectedIndex=$script:selectedIndex;$body.Controls.Add($choice)
        $script:installButton=New-VEButton $body '安装到这个助手' 0 157 270
        $script:installNote=New-VELabel $body '' 0 232 690 145
        $choice.add_SelectedIndexChanged({$script:selectedIndex=$script:choice.SelectedIndex;$script:installedRoots=@();$script:ready=$false;$script:installNote.Text='';Set-VEBusy $false})
        $installButton.add_Click({
            try {
                $script:installButton.Enabled=$false
                $targetName=@('DeepSeek','Codex','Both')[$script:choice.SelectedIndex]
                $script:installedRoots=@(Install-VESkill $script:skillRoot $targetName)
                $script:installNote.Text='安装完成。点击右下角“下一步”，检查运行环境。'
                $script:choice.Enabled=$false
            } catch { $script:installNote.Text='安装未完成：'+$_.Exception.Message;$script:installButton.Enabled=$true }
            Set-VEBusy $false
        })
        if ($script:installedRoots.Count) { $script:installNote.Text='已安装，可以继续下一步。' }
    } elseif ($script:page -eq 2) {
        $script:heading.Text='检查一下，让电脑准备好'
        $null=New-VELabel $body '点击“检查环境”。缺少时点“自动配置环境”；有离线组件包会优先使用。' 0 0 690 54
        $script:checkButton=New-VEButton $body '检查环境' 0 60 210
        $script:autoButton=New-VEButton $body '自动配置环境' 235 60 240;$autoButton.Visible=$false
        $script:diagnosticButton=New-VEButton $body '复制诊断信息' 495 60 195;$diagnosticButton.Visible=$false
        $diagnosticButton.add_Click({if ($script:lastDiagnostic) {[Windows.Forms.Clipboard]::SetText($script:lastDiagnostic);[Windows.Forms.MessageBox]::Show('已复制。回到助手对话，粘贴发送即可。','诊断信息') | Out-Null}})
        $script:bar=New-Object Windows.Forms.ProgressBar;$bar.SetBounds(0,130,690,12);$bar.Style='Marquee';$bar.Visible=$false;$body.Controls.Add($bar)
        $script:detail=New-Object Windows.Forms.TextBox;$detail.Multiline=$true;$detail.ReadOnly=$true;$detail.ScrollBars='Vertical'
        $detail.SetBounds(0,160,690,210);$detail.BackColor=$form.BackColor;$detail.BorderStyle='None';$body.Controls.Add($detail)
        $detail.Text=if ($script:ready) {'环境已就绪，点击“下一步”。'} else {'无需输入路径，也不需要选择 Python 或 FFmpeg。'}
        $checkButton.add_Click({Start-VEWorker 'check'});$autoButton.add_Click({Start-VEWorker 'setup'})
    } else {
        $script:heading.Text='恭喜，可以开始剪辑视频啦！'
        $null=New-VELabel $body '重新打开助手，在对话中说：' 0 12 690 40 17
        $null=New-VELabel $body '用 video-edit 帮我做一部旅行纪念片。' 0 68 690 78 22
        $copy=New-VEButton $body '复制这句话' 0 165 220
        $copy.add_Click({[Windows.Forms.Clipboard]::SetText('用 video-edit 帮我做一部旅行纪念片。')})
        $start=New-VEButton $body '开始选素材' 250 165 220
        $start.add_Click({Start-Process powershell.exe -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File',('"'+(Join-Path $script:installedRoots[0] 'scripts\launch.ps1')+'"')) -WindowStyle Hidden})
        $null=New-VELabel $body '接下来会先弹出文件夹选择窗口。找到你的视频文件夹即可，原片会保留。选材分析后，回到助手继续制作。' 0 250 690 115
    }
    Set-VEBusy $false
}
$timer.add_Tick({
    if (-not $script:process) { return }
    $script:process.Refresh()
    if (-not $script:process.HasExited) {
        if ($script:page -eq 2 -and $script:activeMode -eq 'setup') {
            $progressLines=@()
            foreach ($root in $script:installedRoots) {
                $progressPath=Join-Path $root '.runtime\setup-progress.json'
                if (Test-Path -LiteralPath $progressPath) {
                    try {
                        $p=Get-Content -Raw -LiteralPath $progressPath -Encoding UTF8 | ConvertFrom-Json
                        $progressLines+=@($p.message,$p.detail)
                    } catch {}
                }
            }
            if ($progressLines.Count) {$script:detail.Text=($progressLines -join [Environment]::NewLine);return}
        }
        $lines=@(Get-Content -LiteralPath $script:logPath -Encoding UTF8 -Tail 80 -ErrorAction SilentlyContinue | Where-Object { $_ -match '^\[\d/4\]|^正在|^本地语音模型|^原来配置' } | Select-Object -Last 5)
        if ($lines.Count) { $script:detail.Text=($lines -join [Environment]::NewLine) }
        return
    }
    $script:timer.Stop()
    try {
        if (-not (Test-Path -LiteralPath $script:resultPath)) { throw ('处理未完成，可重试。日志：'+$script:errorPath) }
        $state=Get-Content -Raw -LiteralPath $script:resultPath -Encoding UTF8 | ConvertFrom-Json
        if ($script:page -eq 0) {
            $script:appsReady=[bool]$state.ready;$script:apps=@($state.apps)
            $lines=@()
            foreach ($app in $script:apps) {
                if ($app.installed) {$lines+='已找到：'+$app.name}
                else {
                    $button=$script:appButtons[$app.id];$button.Visible=$true
                    $button.Text=if ($app.installer) {'安装 '+$app.name} else {'打开'+$app.name+'官网'}
                    $lines+=if ($app.installer) {$app.name+'安装包已下载，请点击上方安装按钮。'} else {$app.name+'尚未准备好，可重试或打开官网。'}
                }
            }
            $script:detail.Text=(@($lines)+@($state.problems) -join [Environment]::NewLine)
            if ($script:appsReady) {$script:detail.AppendText([Environment]::NewLine+'软件已就绪，点击右下角“下一步”。')}
        } else {
        $script:ready=[bool]$state.ready
        $script:detail.Text=(@($state.items)+@($state.problems) -join [Environment]::NewLine)
        $script:autoButton.Visible=[bool]$state.auto_setup_needed
        $script:autoButton.Text=if ($state.failure) {'重试自动配置'} else {'自动配置环境'}
        if (-not $script:ready) {
            $diagnostic=@('回忆剪辑安装诊断','操作：'+$script:activeMode,'时间：'+(Get-Date).ToString('s'),$script:detail.Text)
            if ($state.failure) {
                $diagnostic+=@('失败步骤：'+$state.failure.stage,'错误代码：'+$state.failure.code)
                foreach ($log in @($state.failure.log,$state.failure.stdout_log)) {if ($log) {$diagnostic+=@('日志：'+$log,(Get-VELogTail $log 30))}}
                $script:detail.Text='配置未完成：'+$state.failure.stage_label+[Environment]::NewLine+$script:detail.Text+[Environment]::NewLine+'可重试；仍失败请点“复制诊断信息”，粘贴给助手。'
            }
            $diagnostic+=@((Get-VELogTail $script:errorPath 20),(Get-VELogTail $script:logPath 20))
            $script:lastDiagnostic=$diagnostic -join [Environment]::NewLine;$script:diagnosticButton.Visible=$true
        }
        if ($script:ready) { $script:detail.AppendText([Environment]::NewLine+'全部就绪，点击右下角“下一步”。') }
        elseif (-not $state.auto_setup_needed) { $script:detail.AppendText([Environment]::NewLine+'上面的项目处理好后，再点击“检查环境”。软件未安装时请返回第一步。') }
        }
    } catch {
        $script:ready=$false;if ($script:page -eq 0) {$script:appsReady=$false}
        $script:detail.Text=$_.Exception.Message
        if ($script:page -eq 2) {
            $script:autoButton.Visible=$true;$script:autoButton.Text='重试自动配置'
            $script:lastDiagnostic=@($script:detail.Text,(Get-VELogTail $script:errorPath 30),(Get-VELogTail $script:logPath 30)) -join [Environment]::NewLine
            $script:diagnosticButton.Visible=$true
        }
    }
    $script:process.Dispose();$script:process=$null;Set-VEBusy $false
})
$back.add_Click({if ($script:page -gt 0) {$script:page--;Show-VEPage;if ($script:page -eq 0) {Start-VEAppsWorker}}})
$next.add_Click({if ($script:page -eq 3) {$script:form.Close()} else {$script:page++;Show-VEPage}})
$form.add_Shown({Start-VEAppsWorker})
$form.add_FormClosing({$script:timer.Stop()})
Show-VEPage
$null=$form.ShowDialog()
$timer.Dispose();$form.Dispose()
