function Read-VEConfig([string]$Root) {
    $config=@{}
    foreach ($name in @('config.example.json','config.local.json')) {
        $path=Join-Path $Root $name
        if (Test-Path -LiteralPath $path) {
            $obj=Get-Content -Raw -LiteralPath $path -Encoding UTF8 | ConvertFrom-Json
            foreach ($p in $obj.PSObject.Properties) { $config[$p.Name]=$p.Value }
        }
    }
    return $config
}
. (Join-Path $PSScriptRoot 'bootstrap-support.ps1')
function Read-VEProbe([string]$Python,[string]$Root,[switch]$PythonOnly,[string]$ConfigPath) {
    $arguments=@('-B','-X','utf8',(Join-Path $Root 'scripts\bootstrap_probe.py'))
    if ($PythonOnly) { $arguments+='--python-only' }
    if ($ConfigPath) { $arguments+=@('--config',$ConfigPath) }
    try {
        $reply=& $Python @arguments 2>$null
        if ($LASTEXITCODE -eq 0) { return ($reply | ConvertFrom-Json) }
    } catch { }
    return $null
}
function Find-VEPython([string]$Root,$Config) {
    $candidates=New-Object System.Collections.Generic.List[string]
    if ($Config.python) { $candidates.Add([Environment]::ExpandEnvironmentVariables($Config.python)) }
    $checkpoint=Join-Path $Root '.runtime\setup-python.json'
    if (Test-Path -LiteralPath $checkpoint) {
        try {$saved=Get-Content -Raw -LiteralPath $checkpoint -Encoding UTF8 | ConvertFrom-Json;if ($saved.python) {$candidates.Add($saved.python)}} catch {}
    }
    foreach ($r in @('.runtime\venv\Scripts\python.exe','.runtime\Scripts\python.exe','.runtime\python\python.exe')) { $candidates.Add((Join-Path $Root $r)) }
    $ancestor=[IO.DirectoryInfo]$Root
    while ($null -ne $ancestor) {
        $candidates.Add((Join-Path $ancestor.FullName '.tools\media-venv\Scripts\python.exe'));$ancestor=$ancestor.Parent
    }
    $onPath=Get-Command python.exe -ErrorAction SilentlyContinue
    if ($onPath -and $onPath.Source -notlike '*WindowsApps*') { $candidates.Add($onPath.Source) }
    foreach ($pattern in @((Join-Path $env:LOCALAPPDATA 'Programs\Python\Python*\python.exe'),(Join-Path $env:ProgramFiles 'Python*\python.exe'))) {
        foreach ($p in Get-ChildItem -Path $pattern -ErrorAction SilentlyContinue) { $candidates.Add($p.FullName) }
    }
    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            $probe=Read-VEProbe $candidate $Root -PythonOnly
            if ($probe -and $probe.usable) { return $candidate }
        }
    }
    return $null
}
function Get-VEFile([string]$Url,[string]$Destination) {
    $ProgressPreference='SilentlyContinue'
    if (-not $Url.StartsWith('https://')) { throw '下载地址必须使用 HTTPS。' }
    $null=New-Item -ItemType Directory -Path (Split-Path -Parent $Destination) -Force
    for ($attempt=1;$attempt -le 3;$attempt++) {
        try {
            Write-Host ('正在下载（'+$attempt+'/3）：'+[IO.Path]::GetFileName($Destination))
            Invoke-WebRequest -Uri $Url -UseBasicParsing -OutFile ($Destination+'.part') -TimeoutSec 1200
            Move-Item -LiteralPath ($Destination+'.part') -Destination $Destination -Force
            return $Destination
        } catch {
            if ($attempt -eq 3) { throw ('下载未完成，请检查网络后重试。已完成的组件会保留。地址：'+$Url+'；'+$_.Exception.Message) }
            Start-Sleep -Seconds 2
        }
    }
}
function Test-VEPythonSignature([string]$Path) {
    $s=Get-AuthenticodeSignature -LiteralPath $Path
    return ($s.Status -eq 'Valid' -and $s.SignerCertificate.Subject -match 'Python Software Foundation')
}
function Install-VEPython([string]$Root) {
    $version='3.13.16'
    $installer=Join-Path $Root ('.runtime\downloads\python-'+$version+'-amd64.exe')
    $offline=Get-VEOfflineBundle $Root
    if ($offline) {$installer=Get-VEOfflineFile $offline ('python/python-'+$version+'-amd64.exe')}
    elseif (-not (Test-Path -LiteralPath $installer) -or -not (Test-VEPythonSignature $installer)) {
        $null=Get-VEFile ('https://www.python.org/ftp/python/'+$version+'/python-'+$version+'-amd64.exe') $installer
    }
    if (-not (Test-VEPythonSignature $installer)) { throw 'Python 安装包签名检查失败，未执行安装。' }
    $destination=Join-Path $Root '.runtime\python';$log=Join-Path $Root '.runtime\python-install.log'
    Write-Host '正在自动安装 Python 和图形组件…'
    $arguments=@('/quiet','InstallAllUsers=0',('TargetDir="'+$destination+'"'),'PrependPath=0','AppendPath=0','Include_launcher=0',
        'InstallLauncherAllUsers=0','AssociateFiles=0','Shortcuts=0','Include_test=0','Include_doc=0','Include_pip=1','Include_tcltk=1','/log',('"'+$log+'"'))
    $p=Start-Process -FilePath $installer -ArgumentList $arguments -WindowStyle Hidden -Wait -PassThru
    if ($p.ExitCode -notin @(0,3010)) {
        $e=New-Object Exception('Python 安装未完成，代码 '+$p.ExitCode+'。日志：'+$log)
        $e.Data['log']=$log;$e.Data['code']='PYTHON_INSTALL_FAILED';throw $e
    }
    $python=Join-Path $destination 'python.exe';$probe=Read-VEProbe $python $Root -PythonOnly
    if (-not $probe -or -not $probe.usable) { throw ('Python 安装后检查未通过。日志：'+$log) }
    return $python
}
function Test-VEFFmpeg([string]$FFmpeg,[string]$FFprobe) {
    if (-not $FFmpeg -or -not $FFprobe -or -not (Test-Path -LiteralPath $FFmpeg) -or -not (Test-Path -LiteralPath $FFprobe)) { return $false }
    try {
        $null=& $FFprobe -v error -version 2>$null
        if ($LASTEXITCODE -ne 0) { return $false }
        $filters=(& $FFmpeg -hide_banner -filters 2>$null) -join "`n"
        if ($LASTEXITCODE -ne 0) { return $false }
        foreach ($name in @('subtitles','zscale','tonemap')) { if ($filters -notmatch ('\b'+$name+'\b')) { return $false } }
        $encoders=(& $FFmpeg -hide_banner -encoders 2>$null) -join "`n"
        return ($LASTEXITCODE -eq 0 -and $encoders -match '\blibx264\b')
    } catch { return $false }
}
function Install-VEFFmpeg([string]$Root) {
    $base=Join-Path $Root '.runtime\ffmpeg'
    foreach ($f in Get-ChildItem -Path $base -Filter ffmpeg.exe -File -Recurse -ErrorAction SilentlyContinue) {
        $probe=Join-Path $f.DirectoryName 'ffprobe.exe'
        if (Test-VEFFmpeg $f.FullName $probe) { return @{ffmpeg=$f.FullName;ffprobe=$probe} }
    }
    $offline=Get-VEOfflineBundle $Root
    $checksum=Join-Path $Root '.runtime\downloads\ffmpeg.zip.sha256'
    if ($offline) {$checksum=Get-VEOfflineFile $offline 'ffmpeg/ffmpeg.zip.sha256'}
    else {$null=Get-VEFile 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip.sha256' $checksum}
    $match=[regex]::Match((Get-Content -Raw -LiteralPath $checksum),'(?i)\b[0-9a-f]{64}\b')
    if (-not $match.Success) { throw 'FFmpeg 的校验信息无效，未执行。' }
    $expected=$match.Value.ToLowerInvariant();$archive=Join-Path $Root '.runtime\downloads\ffmpeg.zip'
    if ($offline) {$archive=Get-VEOfflineFile $offline 'ffmpeg/ffmpeg.zip'}
    elseif (-not (Test-Path -LiteralPath $archive) -or (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) {
        $null=Get-VEFile 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' $archive
    }
    if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) { throw 'FFmpeg 下载校验失败，未解压或执行；请重试。' }
    $destination=Join-Path $base ([guid]::NewGuid().ToString())
    Write-Host '正在解压并检查 FFmpeg…'
    Expand-Archive -LiteralPath $archive -DestinationPath $destination
    foreach ($f in Get-ChildItem -LiteralPath $destination -Filter ffmpeg.exe -Recurse -File) {
        $probe=Join-Path $f.DirectoryName 'ffprobe.exe'
        if (Test-VEFFmpeg $f.FullName $probe) { return @{ffmpeg=$f.FullName;ffprobe=$probe} }
    }
    throw 'FFmpeg 缺少需要的编码器或字幕/HDR 滤镜，未启用该版本。'
}
function Initialize-VideoEdit([string]$Root) {
    if (-not [Environment]::Is64BitOperatingSystem) { throw '自动配置需要 64 位 Windows。' }
    Set-VEStage $Root 'python' '[1/4] 正在准备 Python…'
    $config=Read-VEConfig $Root;$python=Find-VEPython $Root $config;$offline=Get-VEOfflineBundle $Root
    if (-not $python) { $python=Install-VEPython $Root }
    Write-Host '[1/4] 已找到可用的 Python。'
    $probe=Read-VEProbe $python $Root
    if (-not $probe) { throw '环境探测未完成，请检查配置文件。' }
    if (@($probe.missing_dependencies).Count -gt 0) {
        if ($offline -and $probe.version -notlike '3.13.*') {$python=Install-VEPython $Root;$probe=Read-VEProbe $python $Root}
        Set-VEStage $Root 'dependencies' '[2/4] 正在安装剪辑运行组件…'
        Test-VEVendor $Root
        $venv=Join-Path $Root '.runtime\venv';$privatePython=Join-Path $venv 'Scripts\python.exe'
        $venvProbe=Read-VEProbe $privatePython $Root -PythonOnly
        if (-not $venvProbe -or -not $venvProbe.usable -or ($offline -and $venvProbe.version -notlike '3.13.*')) {
            if (Test-Path -LiteralPath $venv) {
                $venv=Join-Path $Root ('.runtime\venv-'+[guid]::NewGuid().ToString())
                $privatePython=Join-Path $venv 'Scripts\python.exe'
            }
            $null=Invoke-VENative $python @('-m','venv',$venv) $Root 'create-venv' 300
            $venvProbe=Read-VEProbe $privatePython $Root -PythonOnly
            if (-not $venvProbe -or -not $venvProbe.usable) { throw '新建的运行环境无法使用，请查看安装日志。' }
        }
        @{python=$privatePython} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $Root '.runtime\setup-python.json') -Encoding UTF8
        $pipArgs=@('-m','pip','install','--disable-pip-version-check','--only-binary=:all:','--retries','2','--timeout','30')
        if ($offline) {
            foreach ($file in $offline.manifest.files.PSObject.Properties.Name | Where-Object {$_ -like 'wheels/*'}) {$null=Get-VEOfflineFile $offline $file}
            $requirements=Get-VEOfflineFile $offline 'requirements-lock.txt'
            $pipArgs+=@('--no-index','--find-links',(Join-Path $offline.root 'wheels'),'--require-hashes','-r',$requirements)
        } else {$pipArgs+=@('-r',(Join-Path $Root 'requirements.txt'))}
        $null=Invoke-VENative $privatePython $pipArgs $Root 'install-components' 1800
        $python=$privatePython;$probe=Read-VEProbe $python $Root
        if (-not $probe -or @($probe.missing_dependencies).Count -gt 0) { throw ('组件安装后仍无法加载：'+($probe.dependency_errors | ConvertTo-Json -Compress)+'。请复制诊断信息。') }
    } else { Write-Host '[2/4] 运行依赖已齐全，直接复用。' }
    $config.python=$python
    if (Test-VEFFmpeg $probe.ffmpeg $probe.ffprobe) {
        $config.ffmpeg=$probe.ffmpeg;$config.ffprobe=$probe.ffprobe
        Write-Host '[3/4] FFmpeg 已齐全，直接复用。'
    } else {
        $ffmpegMessage=if ($offline) {'[3/4] 正在校验并安装包内的 FFmpeg…'} else {'[3/4] 正在联网下载并安装 FFmpeg…'}
        Set-VEStage $Root 'ffmpeg' $ffmpegMessage
        $f=Install-VEFFmpeg $Root;$config.ffmpeg=$f.ffmpeg;$config.ffprobe=$f.ffprobe
    }
    $model=$probe.model
    if (-not $model) {
        Set-VEStage $Root 'model' '[4/4] 正在准备本地语音模型…'
        $cache=Join-Path $Root '.runtime\models';$result=Join-Path $Root '.runtime\model-download.json'
        $null=New-Item -ItemType Directory -Path $cache -Force
        if ($offline) {
            $model=Join-Path $cache 'faster-whisper-small';$null=New-Item -ItemType Directory -Path $model -Force
            foreach ($file in @('model.bin','config.json','tokenizer.json','vocabulary.txt')) {
                $source=Get-VEOfflineFile $offline ('model/'+$file)
                Copy-Item -LiteralPath $source -Destination (Join-Path $model $file) -Force
            }
        } else {
            $null=Invoke-VENative $python @('-B','-X','utf8',(Join-Path $Root 'scripts\download_model.py'),$cache,'--result',$result) $Root 'download-model' 1800
            $model=(Get-Content -Raw -LiteralPath $result -Encoding UTF8 | ConvertFrom-Json).model
        }
        $config.model_cache=$cache
    } else { Write-Host '[4/4] 本地语音模型已存在，直接复用。' }
    $config.whisper_model_dir=$model
    Set-VEStage $Root 'verify' '正在复核安装结果…'
    if ($config.font_path -and -not (Test-Path -LiteralPath $config.font_path -PathType Leaf)) {
        Write-Host '原来配置的字体已不存在，恢复使用本机系统字体。'
        $config.font_path=$null
    }
    $temporary=Join-Path $Root ('.config-'+[guid]::NewGuid().ToString()+'.json')
    $config | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $temporary -Encoding UTF8
    $final=Read-VEProbe $python $Root -ConfigPath $temporary
    if (-not $final -or -not $final.model -or -not $final.font_ready -or @($final.missing_dependencies).Count -gt 0) { throw ('配置复核失败，原配置未覆盖。检查文件：'+$temporary) }
    $local=Join-Path $Root 'config.local.json'
    if (Test-Path -LiteralPath $local) { Copy-Item -LiteralPath $local -Destination ($local+'.backup') -Force }
    Move-Item -LiteralPath $temporary -Destination $local -Force
    return @{ok=$true;code='OK';python=$python;config=$local;model=$model;ffmpeg=$config.ffmpeg;ffprobe=$config.ffprobe}
}
