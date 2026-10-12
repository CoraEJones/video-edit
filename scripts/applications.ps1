# Desktop prerequisites, independent of Python and video-processing packages.
function Find-VEApplication([string]$Id,$Config) {
    $roots=New-Object System.Collections.Generic.List[string]
    $exe=if ($Id -eq 'jianying') {'JianyingPro.exe'} elseif ($Id -eq 'codex') {'Codex.exe'} else {'DeepSeek Harness.exe'}
    $display=if ($Id -eq 'jianying') {'Jianying|剪映'} elseif ($Id -eq 'codex') {'OpenAI.*Codex|Codex'} else {'DeepSeek Harness'}
    $configured=if ($Id -eq 'jianying') {$Config.jianying_install_dir} elseif ($Id -eq 'codex') {$Config.codex_exe} else {$Config.harness_exe}
    if ($Id -ne 'jianying') {
        $command=Get-Command $(if ($Id -eq 'codex') {'codex'} else {'dsh'}) -ErrorAction SilentlyContinue
        if ($command -and $command.Source) {return $command.Source}
    }
    if ($Id -eq 'codex' -and (Get-Command Get-AppxPackage -ErrorAction SilentlyContinue)) {
        foreach ($package in Get-AppxPackage -Name '*Codex*' -ErrorAction SilentlyContinue) {
            if ($package.InstallLocation -and (Test-Path -LiteralPath $package.InstallLocation)) {return $package.InstallLocation}
        }
    }
    if ($configured) { $roots.Add([Environment]::ExpandEnvironmentVariables($configured)) }
    foreach ($base in @($env:LOCALAPPDATA,$env:ProgramFiles,${env:ProgramFiles(x86)})) {
        if (-not $base) { continue }
        $name=if ($Id -eq 'jianying') {'JianyingPro'} elseif ($Id -eq 'codex') {'Codex'} else {'DeepSeek Harness'}
        $roots.Add((Join-Path $base $name));$roots.Add((Join-Path $base ('Programs\'+$name)))
    }
    foreach ($reg in @('HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*','HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*','HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*')) {
        foreach ($app in Get-ItemProperty $reg -ErrorAction SilentlyContinue | Where-Object {$_.DisplayName -match $display}) {
            if ($app.InstallLocation) {$roots.Add($app.InstallLocation)}
            if ($app.DisplayIcon) {$roots.Add(($app.DisplayIcon -replace ',\d+$','').Trim('"'))}
        }
    }
    foreach ($p in Get-Process -Name ([IO.Path]::GetFileNameWithoutExtension($exe)) -ErrorAction SilentlyContinue) {
        try { if ($p.Path) {$roots.Add($p.Path)} } catch { }
    }
    foreach ($root in ($roots | Select-Object -Unique)) {
        if ((Test-Path -LiteralPath $root -PathType Leaf) -and [IO.Path]::GetFileName($root) -eq $exe) { return [IO.Path]::GetFullPath($root) }
        $candidates=@((Join-Path $root $exe))
        if ($Id -eq 'jianying') {
            foreach ($dir in @($root,(Join-Path $root 'Apps'))) {
                foreach ($child in Get-ChildItem -LiteralPath $dir -Directory -ErrorAction SilentlyContinue | Sort-Object Name -Descending) {
                    $candidates+=Join-Path $child.FullName $exe
                }
            }
        }
        foreach ($candidate in $candidates) { if (Test-Path -LiteralPath $candidate -PathType Leaf) { return [IO.Path]::GetFullPath($candidate) } }
    }
    return $null
}
function Get-VEAppSpec([string]$Id) {
    if ($Id -eq 'jianying') {
        return @{id=$Id;name='剪映专业版';homepage='https://www.capcut.cn/';publisher='Shenzhen Lianmeng|深圳市脸萌';host_pattern='^lf\d+-package\.vlabstatic\.com$'}
    }
    if ($Id -eq 'codex') {
        return @{id=$Id;name='Codex';homepage='https://chatgpt.com/codex';publisher='OpenAI';host_pattern='^$';manual=$true}
    }
    if ($Id -eq 'harness') {
        return @{id=$Id;name='DeepSeek Harness';homepage='https://www.deepseek.com/zh/download/';publisher='Hangzhou DeepSeek Artificial Intelligence';host_pattern='^download\.deepseek\.com$'}
    }
    throw '未知的软件名称。'
}
function Resolve-VEAppInstaller([string]$Id,[string]$Html) {
    $spec=Get-VEAppSpec $Id
    if (-not $Html) { $Html=(Invoke-WebRequest -Uri $spec.homepage -UseBasicParsing -TimeoutSec 60).Content }
    if ($Id -eq 'jianying') {
        $m=[regex]::Match($Html,'download_url=([^&"\s<>]+)')
        if (-not $m.Success) { throw '剪映官网的下载入口有变化，请通过官网下载安装。' }
        $url=[uri]::UnescapeDataString($m.Groups[1].Value)
    } else {
        $m=[regex]::Match($Html,'https://download\.deepseek\.com/[^"\s<>]*windows-x64\.exe')
        if (-not $m.Success) { $m=[regex]::Match($Html,'https://download\.deepseek\.com/[^"\s<>]*win-x64\.exe') }
        if (-not $m.Success) { throw 'DeepSeek 官网的下载入口有变化，请通过官网下载安装。' }
        $url=$m.Value
    }
    $uri=[uri]$url
    if ($uri.Scheme -ne 'https' -or $uri.Host -notmatch $spec.host_pattern -or $uri.AbsolutePath -notmatch '\.exe$') { throw '官网安装包地址未通过检查。' }
    return $url
}
function Test-VEAppInstaller([string]$Id,[string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $false }
    $spec=Get-VEAppSpec $Id;$sig=Get-AuthenticodeSignature -LiteralPath $Path
    return ($sig.Status -eq 'Valid' -and $sig.SignerCertificate.Subject -match $spec.publisher)
}
function Save-VEAppInstaller([string]$Id,[string]$Root) {
    $spec=Get-VEAppSpec $Id
    if ($spec.manual) {return $null}
    $path=Join-Path $Root ('.runtime\downloads\'+$Id+'-setup.exe')
    if (Test-VEAppInstaller $Id $path) { return $path }
    Write-Host ('正在从官网下载 '+$spec.name+' 安装包…')
    $url=Resolve-VEAppInstaller $Id
    $null=Get-VEFile $url $path
    if (-not (Test-VEAppInstaller $Id $path)) { throw ($spec.name+' 安装包的发布者签名检查未通过，未运行。') }
    @{official_page=$spec.homepage;url=$url;sha256=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash;verified_at=(Get-Date -Format o)} |
        ConvertTo-Json | Set-Content -LiteralPath ($path+'.json') -Encoding UTF8
    return $path
}
function Get-VEApplications([string]$Root,[switch]$DownloadMissing,[string]$ConfigPath,
    [string]$DeliveryMode,[string]$HostName,[switch]$ActiveHost) {
    $config=Read-VEConfig $Root;$apps=@();$problems=@()
    if ($ConfigPath) {
        $custom=Get-Content -Raw -LiteralPath $ConfigPath -Encoding UTF8 | ConvertFrom-Json
        foreach ($property in $custom.PSObject.Properties) {$config[$property.Name]=$property.Value}
    }
    if (-not $DeliveryMode) {$DeliveryMode=if ($config.delivery_mode) {$config.delivery_mode} else {'editable'}}
    if (-not $HostName) {$HostName=if ($config.host) {$config.host} else {'auto'}}
    if ($DeliveryMode -notin @('mp4','editable') -or $HostName -notin @('auto','codex','deepseek')) {throw '交付方式或助手配置无效，请重新选择。'}
    if ($HostName -eq 'auto') {
        if (Find-VEApplication 'codex' $config) {$HostName='codex'}
        elseif (Find-VEApplication 'harness' $config) {$HostName='deepseek'}
        else {$problems+='请先选择并安装一个助手：Codex 或 DeepSeek Harness。'}
    }
    $ids=@()
    if ($HostName -ne 'auto') {$ids+=if ($HostName -eq 'deepseek') {'harness'} else {'codex'}}
    if ($DeliveryMode -eq 'editable') {$ids+='jianying'}
    foreach ($id in $ids) {
        $spec=Get-VEAppSpec $id;$installer=$null;$errorText=$null
        $current=($ActiveHost -and $id -ne 'jianying' -and $HostName -ne 'auto')
        $path=if ($current) {$null} else {Find-VEApplication $id $config}
        $installed=($current -or [bool]$path)
        if (-not $installed) {
            try {
                if ($DownloadMissing) { $installer=Save-VEAppInstaller $id $Root }
                elseif (-not $spec.manual) {
                    $candidate=Join-Path $Root ('.runtime\downloads\'+$id+'-setup.exe')
                    if (Test-VEAppInstaller $id $candidate) {$installer=$candidate}
                }
            } catch {$errorText=$_.Exception.Message;$problems+=$errorText}
            $problems+=($spec.name+'尚未安装；已安装时请指定程序位置或重新扫描。')
        }
        $apps+=@{id=$id;name=$spec.name;installed=$installed;path=$path;installer=$installer;homepage=$spec.homepage;error=$errorText;
            detection=if ($current) {'active_host'} else {'local_scan'}}
    }
    return @{ready=($HostName -ne 'auto' -and @($apps | Where-Object {-not $_.installed}).Count -eq 0);
        apps=$apps;problems=$problems;phase='applications';delivery_mode=$DeliveryMode;selected_host=$HostName}
}
