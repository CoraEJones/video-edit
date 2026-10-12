function Install-VESkill([string]$Source,[string]$Target,[string]$DeliveryMode,[string]$EntryMode) {
    if (($DeliveryMode -and $DeliveryMode -notin @('mp4','editable')) -or ($EntryMode -and $EntryMode -notin @('chat','wizard'))) {throw '安装模式无效。'}
    $roots=@()
    if ($Target -in @('DeepSeek','Both')) { $roots+=Join-Path $env:USERPROFILE '.dsh\skills\video-edit' }
    if ($Target -in @('Codex','Both')) { $roots+=Join-Path $env:USERPROFILE '.codex\skills\video-edit' }
    $files=@(Get-ChildItem -LiteralPath $Source -File -Recurse -Force | Where-Object {
        $relative=$_.FullName.Substring($Source.Length).TrimStart([char[]]'\/')
        $relative -notmatch '(^|[\\/])(\.runtime|offline-runtime|\.git|__pycache__)([\\/]|$)' -and $_.Extension -ne '.pyc' -and
        $_.Name -notlike 'config.local.json*' -and $_.Name -notlike '.config-*.json'
    })
    foreach ($dest in $roots) {
        if ([IO.Path]::GetFullPath($dest).TrimEnd('\') -eq [IO.Path]::GetFullPath($Source).TrimEnd('\')) {
            $selectedHost=if ($Target -eq 'DeepSeek') {'deepseek'} else {'codex'}
            $null=Save-VESelection $dest $selectedHost $DeliveryMode $EntryMode
            continue
        }
        $null=New-Item -ItemType Directory -Path $dest -Force
        $backup=Join-Path $dest ('.runtime\installer-backups\'+[guid]::NewGuid().ToString())
        foreach ($file in $files) {
            $relative=$file.FullName.Substring($Source.Length).TrimStart([char[]]'\/');$targetFile=Join-Path $dest $relative
            if (Test-Path -LiteralPath $targetFile) {
                $old=Join-Path $backup $relative;$null=New-Item -ItemType Directory -Path (Split-Path -Parent $old) -Force
                Copy-Item -LiteralPath $targetFile -Destination $old -Force
            }
            $null=New-Item -ItemType Directory -Path (Split-Path -Parent $targetFile) -Force
            Copy-Item -LiteralPath $file.FullName -Destination $targetFile -Force
        }
        $local=Join-Path $dest 'config.local.json'
        if (-not (Test-Path -LiteralPath $local) -and (Test-Path -LiteralPath (Join-Path $Source 'config.local.json'))) {
            Copy-Item -LiteralPath (Join-Path $Source 'config.local.json') -Destination $local
        }
        $offline=Join-Path $Source 'offline-runtime'
        if (Test-Path -LiteralPath (Join-Path $offline 'manifest.json')) {
            $config=Read-VEConfig $dest;$config.offline_bundle_path=[IO.Path]::GetFullPath($offline)
            if (Test-Path -LiteralPath $local) {Copy-Item -LiteralPath $local -Destination ($local+'.backup') -Force}
            $config | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $local -Encoding UTF8
        }
        $hostName=if ($dest -like '*\.dsh\*') {'deepseek'} else {'codex'}
        $null=Save-VESelection $dest $hostName $DeliveryMode $EntryMode
    }
    return $roots
}
function Sync-VERuntimeConfig($Roots) {
    if ($Roots.Count -lt 2) { return }
    $primary=Read-VEConfig $Roots[0]
    foreach ($root in $Roots[1..($Roots.Count-1)]) {
        $config=Read-VEConfig $root
        foreach ($key in @('python','ffmpeg','ffprobe','whisper_model_dir','model_cache','offline_bundle_path')) { $config[$key]=$primary[$key] }
        $local=Join-Path $root 'config.local.json'
        if (Test-Path -LiteralPath $local) { Copy-Item -LiteralPath $local -Destination ($local+'.backup') -Force }
        $temp=Join-Path $root ('.config-'+[guid]::NewGuid().ToString()+'.json')
        $config | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $temp -Encoding UTF8
        Move-Item -LiteralPath $temp -Destination $local -Force
    }
}
