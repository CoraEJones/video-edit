param([ValidateSet('Choose','DeepSeek','Codex','Both')][string]$Target='Choose',[switch]$Quiet,
    [ValidateSet('mp4','editable')][string]$DeliveryMode,[ValidateSet('chat','wizard')][string]$EntryMode)
$ErrorActionPreference='Stop'
$script:skillRoot=Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'bootstrap.ps1')
. (Join-Path $PSScriptRoot 'install-files.ps1')
. (Join-Path $PSScriptRoot 'applications.ps1')
if ($Quiet) {
    if ($Target -eq 'Choose') {throw '静默安装需要指定 Target 为 Codex 或 DeepSeek。'}
    Install-VESkill $skillRoot $Target $DeliveryMode $EntryMode | Write-Output
    exit 0
}
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[Windows.Forms.Application]::EnableVisualStyles()
$script:form=New-Object Windows.Forms.Form
$form.Text='回忆剪辑 · 安装向导';$form.ClientSize=New-Object Drawing.Size(800,650)
$form.MinimumSize=$form.Size;$form.StartPosition='CenterScreen';$form.AutoScaleMode='Dpi'
$form.Font=New-Object Drawing.Font('Microsoft YaHei UI',14)
function New-VELabel($Parent,[string]$Text,[int]$X,[int]$Y,[int]$W,[int]$H,[int]$Size=14) {
    $c=New-Object Windows.Forms.Label;$c.Text=$Text;$c.SetBounds($X,$Y,$W,$H)
    $c.Font=New-Object Drawing.Font('Microsoft YaHei UI',$Size);$Parent.Controls.Add($c);return $c
}
function New-VEButton($Parent,[string]$Text,[int]$X,[int]$Y,[int]$W=240) {
    $c=New-Object Windows.Forms.Button;$c.Text=$Text;$c.SetBounds($X,$Y,$W,48);$Parent.Controls.Add($c);return $c
}
function New-VEChoice($Parent,$Items,[int]$Y,[int]$Index) {
    $c=New-Object Windows.Forms.ComboBox;$c.DropDownStyle='DropDownList';$c.SetBounds(0,$Y,720,40)
    $null=$c.Items.AddRange($Items);$c.SelectedIndex=$Index;$Parent.Controls.Add($c);return $c
}
$script:heading=New-VELabel $form '' 30 25 740 60 23
$script:body=New-Object Windows.Forms.Panel;$body.SetBounds(30,100,740,430);$form.Controls.Add($body)
$script:back=New-VEButton $form '上一步' 30 575 150
$script:next=New-VEButton $form '下一步' 600 575 170
$script:page=0;$script:installedRoots=@();$script:process=$null;$script:ready=$false;$script:appsReady=$false
$script:selectedHost=if ($Target -eq 'DeepSeek') {'deepseek'} else {'codex'}
$script:selectedDelivery=if ($DeliveryMode) {$DeliveryMode} else {'mp4'}
$script:selectedEntry=if ($EntryMode) {$EntryMode} else {'wizard'}
$script:timer=New-Object Windows.Forms.Timer;$timer.Interval=500
function Set-VEBusy([bool]$Busy) {
    $script:back.Enabled=(-not $Busy -and $page -gt 0)
    $script:next.Enabled=(-not $Busy -and ($page -eq 0 -or ($page -eq 1 -and $appsReady) -or ($page -eq 2 -and $installedRoots.Count) -or ($page -eq 3 -and $ready) -or $page -eq 4))
    if ($script:action) {$script:action.Enabled=-not $Busy}
    if ($script:setupButton) {$script:setupButton.Enabled=-not $Busy}
}
function Start-VEWorker([string]$Mode) {
    if ($script:process -and -not $script:process.HasExited) {return}
    $script:resultPath=Join-Path ([IO.Path]::GetTempPath()) ('video-edit-'+[guid]::NewGuid().ToString()+'.json')
    $script:errorPath=$script:resultPath+'.error.log';$script:logPath=$script:resultPath+'.log'
    if ($Mode -eq 'apps') {
        $worker=Join-Path $skillRoot 'scripts/application-worker.ps1'
        $arguments=@('-Root',$skillRoot,'-Result',$resultPath,'-HostName',$selectedHost,'-DeliveryMode',$selectedDelivery)
        $script:appsReady=$false
    } else {
        $worker=Join-Path $installedRoots[0] 'scripts/installer-worker.ps1'
        $arguments=@('-Mode',$Mode,'-Root',$installedRoots[0],'-Result',$resultPath)
        $script:ready=$false
    }
    $arguments=@('-NoProfile','-ExecutionPolicy','Bypass','-File',$worker)+$arguments
    $quoted=($arguments | ForEach-Object {Quote-VEArgument $_}) -join ' '
    try {
        $script:detail.Text=if ($Mode -eq 'apps') {'正在扫描所选助手。只有选择可编辑工程时才检查剪映。'} else {'正在检查或准备所选模式需要的组件，请稍候…'}
        $script:process=Start-Process powershell.exe -ArgumentList $quoted -WindowStyle Hidden -PassThru -RedirectStandardOutput $logPath -RedirectStandardError $errorPath
        Set-VEBusy $true;$script:timer.Start()
    } catch {$script:detail.Text=$_.Exception.Message;Set-VEBusy $false}
}
function New-VEDetail([int]$Y) {
    $script:detail=New-Object Windows.Forms.TextBox;$detail.Multiline=$true;$detail.ReadOnly=$true;$detail.ScrollBars='Vertical'
    $detail.SetBounds(0,$Y,730,(425-$Y));$body.Controls.Add($detail)
}
function Show-VEPage {
    $body.Controls.Clear();$script:action=$null;$script:setupButton=$null
    $next.Text=if ($page -eq 4) {'完成'} else {'下一步'}
    if ($page -eq 0) {
        $heading.Text='1 / 5　选一个助手，再选交付方式'
        $null=New-VELabel $body '只需一个助手；已有的软件会继续使用。' 0 0 730 42
        $hostChoice=New-VEChoice $body @('Codex','DeepSeek Harness') 48 $(if ($selectedHost -eq 'codex') {0} else {1})
        $null=New-VELabel $body '最后希望拿到什么？' 0 106 730 38
        $deliveryChoice=New-VEChoice $body @('只要 MP4 成片：无需安装剪映','MP4 ＋可编辑工程：需要剪映') 150 $(if ($selectedDelivery -eq 'mp4') {0} else {1})
        $null=New-VELabel $body '怎样告诉助手你的要求？' 0 210 730 38
        $entryChoice=New-VEChoice $body @('大字向导：点选素材和需求','直接对话：在助手中提供路径和需求') 254 $(if ($selectedEntry -eq 'wizard') {0} else {1})
        $hostChoice.add_SelectedIndexChanged({$script:selectedHost=@('codex','deepseek')[$this.SelectedIndex];$script:appsReady=$false;$script:installedRoots=@();$script:ready=$false})
        $deliveryChoice.add_SelectedIndexChanged({$script:selectedDelivery=@('mp4','editable')[$this.SelectedIndex];$script:appsReady=$false;$script:installedRoots=@();$script:ready=$false})
        $entryChoice.add_SelectedIndexChanged({$script:selectedEntry=@('wizard','chat')[$this.SelectedIndex];$script:installedRoots=@();$script:ready=$false})
        $null=New-VELabel $body '语音识别和配音在需要时再配置。路径和风格等需求会在开工前补问、确认。' 0 325 730 90
    } elseif ($page -eq 1) {
        $heading.Text='2 / 5　扫描本地软件'
        $script:action=New-VEButton $body '重新扫描' 0 0 230;$action.add_Click({Start-VEWorker 'apps'})
        $openHost=New-VEButton $body '打开所选助手官网' 250 0 290
        $openHost.add_Click({$id=if ($selectedHost -eq 'codex') {'codex'} else {'harness'};Start-Process (Get-VEAppSpec $id).homepage})
        if ($selectedDelivery -eq 'editable') {
            $openEditor=New-VEButton $body '打开剪映官网' 0 65 230;$openEditor.add_Click({Start-Process (Get-VEAppSpec 'jianying').homepage})
        }
        New-VEDetail 140
        $detail.Text='已安装的软件会直接使用。仅需安装扫描结果中缺少的软件；安装后点“重新扫描”。'
    } elseif ($page -eq 2) {
        $heading.Text='3 / 5　安装 Skill 到所选助手'
        $null=New-VELabel $body ('助手：'+$selectedHost+'；交付：'+$selectedDelivery+'；入口：'+$selectedEntry) 0 0 730 75
        $null=New-VELabel $body '已有配置会保留；本次所选入口和交付方式会一起保存。' 0 82 730 70
        $script:action=New-VEButton $body '安装或更新 Skill' 0 165 300
        New-VEDetail 235
        $action.add_Click({
            try {
                $targetName=if ($selectedHost -eq 'codex') {'Codex'} else {'DeepSeek'}
                $script:installedRoots=@(Install-VESkill $skillRoot $targetName $selectedDelivery $selectedEntry)
                $detail.Text='Skill 已安装。继续检查环境。'
            } catch {$detail.Text=$_.Exception.Message}
            Set-VEBusy $false
        })
        if ($installedRoots.Count) {$detail.Text='已安装，可继续检查环境。'}
    } elseif ($page -eq 3) {
        $heading.Text='4 / 5　检查 Skill 和运行环境'
        $script:action=New-VEButton $body '检查环境' 0 0 220;$action.add_Click({Start-VEWorker 'check'})
        $script:setupButton=New-VEButton $body '自动配置缺少组件' 245 0 290;$setupButton.add_Click({Start-VEWorker 'setup'})
        New-VEDetail 80
        $detail.Text='优先复用现有环境；只为所选入口和交付方式准备必需组件。'
    } else {
        $heading.Text='5 / 5　回到助手，确认后开工'
        $script:prompt='请使用 video-edit 帮我剪辑视频。交付方式是 '+$selectedDelivery+'。先检查 Skill 和环境，从我提供的信息提取路径和需求；没有提供的素材路径、输出位置、故事、时长、画幅、风格、字幕、配音、音乐及必留内容，请补问。信息齐全后汇总给我确认，再开始。'
        $null=New-VELabel $body '重新打开所选助手，把下面的请求发送给它：' 0 0 730 60
        $null=New-VELabel $body $prompt 0 65 730 230 14
        $copy=New-VEButton $body '复制请求' 0 320 230;$copy.add_Click({[Windows.Forms.Clipboard]::SetText($script:prompt)})
        if ($selectedEntry -eq 'wizard') {
            $start=New-VEButton $body '开始选素材' 250 320 230
            $start.add_Click({Start-Process powershell.exe -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File',('"'+(Join-Path $installedRoots[0] 'scripts/launch.ps1')+'"'),'-Mode','wizard') -WindowStyle Hidden})
        }
    }
    Set-VEBusy $false
}
$timer.add_Tick({
    if (-not $script:process) {return}
    $process.Refresh();if (-not $process.HasExited) {return}
    $timer.Stop()
    try {
        if (-not (Test-Path -LiteralPath $resultPath)) {throw ('检查未返回结果。日志：'+$errorPath)}
        $state=Get-Content -Raw -LiteralPath $resultPath -Encoding UTF8 | ConvertFrom-Json
        if ($page -eq 1) {
            $script:appsReady=[bool]$state.ready
            $lines=@($state.apps | ForEach-Object {if ($_.installed) {'已找到：'+$_.name} else {'需要安装：'+$_.name}})
            $detail.Text=(@($lines)+@($state.problems) -join [Environment]::NewLine)
        } else {$script:ready=[bool]$state.ready;$detail.Text=(@($state.items)+@($state.problems) -join [Environment]::NewLine)}
        if ($state.ready) {$detail.AppendText([Environment]::NewLine+'已就绪，可以继续下一步。')}
    } catch {$detail.Text=$_.Exception.Message}
    $process.Dispose();$script:process=$null;Set-VEBusy $false
})
$back.add_Click({if ($page -gt 0) {$script:page--;Show-VEPage}})
$next.add_Click({if ($page -eq 4) {$form.Close()} else {$script:page++;Show-VEPage;if ($page -eq 1) {Start-VEWorker 'apps'}}})
$form.add_FormClosing({$timer.Stop()})
Show-VEPage;$null=$form.ShowDialog();$timer.Dispose();$form.Dispose()
