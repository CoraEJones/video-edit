$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Windows.Forms
$roots=@((Join-Path $env:USERPROFILE '.dsh\skills\video-edit'),(Join-Path $env:USERPROFILE '.codex\skills\video-edit'))
$toolRoot=$roots | Where-Object { Test-Path -LiteralPath (Join-Path $_ 'scripts\launch.ps1') } | Select-Object -First 1
if (-not $toolRoot) {
    $dialog=New-Object System.Windows.Forms.FolderBrowserDialog
    $dialog.Description='请选择已经安装的 video-edit 文件夹'
    if ($dialog.ShowDialog() -ne 'OK') { exit 0 }
    $toolRoot=$dialog.SelectedPath
    $dialog.Dispose()
}
$launcher=Join-Path $toolRoot 'scripts\launch.ps1'
if (-not (Test-Path -LiteralPath $launcher)) {
    [System.Windows.Forms.MessageBox]::Show('这个文件夹里没有 video-edit，请选择正确的技能文件夹。','未找到工具') | Out-Null
    exit 2
}
& $launcher -Mode repair -Package $PSScriptRoot
