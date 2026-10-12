function Set-VEStage([string]$Root,[string]$Stage,[string]$Message,[string]$Detail='') {
    $script:VEStage=$Stage;$script:VEStageMessage=$Message
    $runtime=Join-Path $Root '.runtime';$null=New-Item -ItemType Directory -Path $runtime -Force
    $value=@{stage=$Stage;message=$Message;detail=$Detail;updated=(Get-Date).ToString('o')}
    $path=Join-Path $runtime 'setup-progress.json';$temp=$path+'.tmp'
    $value | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $temp -Encoding UTF8
    Move-Item -LiteralPath $temp -Destination $path -Force
    if (-not $Detail) {Write-Host $Message}
}
function Get-VELogTail([string]$Path,[int]$Lines=12) {
    if ($Path -and (Test-Path -LiteralPath $Path)) {return ((Get-Content -LiteralPath $Path -Encoding UTF8 -Tail $Lines -ErrorAction SilentlyContinue) -join [Environment]::NewLine)}
    return ''
}
function Quote-VEArgument([string]$Value) {
    return '"'+[regex]::Replace([regex]::Replace($Value,'(\\*)"','$1$1\"'),'(\\+)$','$1$1')+'"'
}
function Invoke-VENative([string]$FilePath,[string[]]$Arguments,[string]$Root,[string]$Label,[int]$TimeoutSeconds=3600) {
    $logs=Join-Path $Root '.runtime\logs';$null=New-Item -ItemType Directory -Path $logs -Force
    $stem=Join-Path $logs ($Label+'-'+[guid]::NewGuid().ToString())
    $stdout=$stem+'.out.log';$stderr=$stem+'.error.log';$script:VELastLog=$stderr
    $quoted=($Arguments | ForEach-Object {Quote-VEArgument $_}) -join ' '
    $process=Start-Process -FilePath $FilePath -ArgumentList $quoted -WorkingDirectory $Root -WindowStyle Hidden -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    # Retain the native handle before polling. Windows PowerShell can otherwise
    # lose ExitCode when the child exits before its Process object is refreshed.
    $null=$process.Handle
    $watch=[Diagnostics.Stopwatch]::StartNew()
    while (-not $process.WaitForExit(1000)) {
        if ($watch.Elapsed.TotalSeconds -gt $TimeoutSeconds) {
            $process.Kill();$process.WaitForExit();$process.Dispose()
            $e=New-Object Exception('此步骤等待超时，请重试。日志已保留。');$e.Data['code']='STEP_TIMEOUT';$e.Data['log']=$stderr;throw $e
        }
        $tail=Get-VELogTail $stdout 2
        if (-not $tail) {$tail=Get-VELogTail $stderr 2}
        if ($tail.Length -gt 600) {$tail=$tail.Substring($tail.Length-600)}
        if ($tail) {Set-VEStage $Root $script:VEStage $script:VEStageMessage $tail}
    }
    $process.WaitForExit();$process.Refresh();$exitCode=$process.ExitCode;$process.Dispose()
    if ($exitCode -ne 0) {
        $detail=Get-VELogTail $stderr
        if (-not $detail) {$detail=Get-VELogTail $stdout}
        $e=New-Object Exception(($script:VEStageMessage+'未完成（代码 '+$exitCode+'）。'+[Environment]::NewLine+$detail))
        $e.Data['code']='COMPONENT_FAILED';$e.Data['log']=$stderr;$e.Data['stdout_log']=$stdout;$e.Data['exit_code']=$exitCode;throw $e
    }
    return @{exit_code=$exitCode;stdout_log=$stdout;stderr_log=$stderr}
}
function Get-VEOfflineBundle([string]$Root) {
    $config=Read-VEConfig $Root;$candidates=@((Join-Path $Root 'offline-runtime'))
    if ($config.offline_bundle_path) {$candidates+=[Environment]::ExpandEnvironmentVariables($config.offline_bundle_path)}
    foreach ($path in $candidates) {
        $manifest=Join-Path $path 'manifest.json'
        if (Test-Path -LiteralPath $manifest) {
            $data=Get-Content -Raw -LiteralPath $manifest -Encoding UTF8 | ConvertFrom-Json
            if ($data.schema_version -ne 1 -or $data.platform -ne 'win_amd64') {throw '离线组件包的格式或平台不匹配。'}
            return @{root=[IO.Path]::GetFullPath($path);manifest=$data}
        }
    }
    return $null
}
function Get-VEOfflineFile($Bundle,[string]$Relative) {
    $entry=$Bundle.manifest.files.PSObject.Properties[$Relative]
    if (-not $entry) {throw ('离线组件包缺少校验记录：'+$Relative)}
    $root=[IO.Path]::GetFullPath($Bundle.root).TrimEnd('\');$path=[IO.Path]::GetFullPath((Join-Path $root $Relative))
    if (-not $path.StartsWith($root+'\',[StringComparison]::OrdinalIgnoreCase)) {throw '离线组件路径超出组件包。'}
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {throw ('离线组件包没有解压完整：'+$Relative)}
    if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.Value.sha256) {throw ('离线组件校验失败，请重新解压：'+$Relative)}
    return $path
}
function Test-VEVendor([string]$Root) {
    $base=Join-Path $Root 'assets\vendor';$manifest=Get-Content -Raw -LiteralPath (Join-Path $base 'manifest.json') -Encoding UTF8 | ConvertFrom-Json
    $wheel=Join-Path $base $manifest.file
    if ((Get-FileHash -LiteralPath $wheel -Algorithm SHA256).Hash.ToLowerInvariant() -ne $manifest.sha256) {throw '随包剪映组件校验失败，请重新解压安装包。'}
}
