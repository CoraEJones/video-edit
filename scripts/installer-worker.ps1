param([ValidateSet('check','setup')][string]$Mode,[string]$Root,[string]$AlsoRoot,[string]$Result)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
. (Join-Path $PSScriptRoot 'bootstrap.ps1')
. (Join-Path $PSScriptRoot 'install-files.ps1')
function Invoke-VECheck([string]$Path,[string]$Output) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Path 'scripts\check-environment.ps1') -Root $Path -Result $Output
    if (-not (Test-Path -LiteralPath $Output)) { throw '环境检查没有返回结果，请重试。' }
    return (Get-Content -Raw -LiteralPath $Output -Encoding UTF8 | ConvertFrom-Json)
}
function Invoke-VESetup([string]$Path,[string]$Output) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Path 'scripts\setup.ps1') -Quiet -ResultPath $Output
    if ($LASTEXITCODE -ne 0) {
        if (Test-Path -LiteralPath $Output) {
            $failure=Get-Content -Raw -LiteralPath $Output -Encoding UTF8 | ConvertFrom-Json
            $e=New-Object Exception($failure.message);$e.Data['setup_failure']=$failure;throw $e
        }
        throw '配置程序没有返回结果，请复制诊断信息。'
    }
}
try {
    if ($Mode -eq 'setup') {
        Invoke-VESetup $Root ($Result+'.setup.json')
    }
    $first=Invoke-VECheck $Root ($Result+'.first.json')
    $states=@($first)
    if ($AlsoRoot) {
        $second=Invoke-VECheck $AlsoRoot ($Result+'.second.json')
        if ($Mode -eq 'setup' -and -not $first.auto_setup_needed -and $second.auto_setup_needed) {
            Sync-VERuntimeConfig @($Root,$AlsoRoot)
            Invoke-VESetup $AlsoRoot ($Result+'.second-setup.json')
            $second=Invoke-VECheck $AlsoRoot ($Result+'.second-after.json')
        }
        $states+= $second
    }
    $ready=$true;$needs=$false;$items=@();$problems=@()
    for ($i=0;$i -lt $states.Count;$i++) {
        $s=$states[$i];$ready=$ready -and [bool]$s.ready;$needs=$needs -or [bool]$s.auto_setup_needed
        if ($states.Count -gt 1) { $items+= @('DeepSeek Harness：','Codex：')[$i] }
        $items+=@($s.items);$problems+=@($s.problems)
    }
    $status=@{ready=$ready;auto_setup_needed=$needs;items=$items;problems=$problems}
} catch {
    $status=@{ready=$false;auto_setup_needed=($Mode -eq 'setup');items=@();problems=@($_.Exception.Message);failure=$_.Exception.Data['setup_failure']}
}
$status | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $Result -Encoding UTF8
if ($status.ready) { exit 0 } else { exit 2 }
