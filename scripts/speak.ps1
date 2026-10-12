param([Parameter(Mandatory=$true)][string]$Request)
$ErrorActionPreference = 'Stop'
$data = Get-Content -Raw -LiteralPath $Request -Encoding UTF8 | ConvertFrom-Json
$speaker = New-Object -ComObject SAPI.SpVoice
$voices = @($speaker.GetVoices() | Where-Object {
    $culture=[System.Globalization.CultureInfo]::GetCultureInfo([Convert]::ToInt32($_.GetAttribute('Language').Split(';')[0],16)).Name
    $culture -like ($data.language.Split('-')[0] + '*')
})
if ($voices.Count -eq 0) { throw ('没有安装所需语言的离线声音：' + $data.language) }
$wanted = if ($data.gender -eq '男声') { 'Male' } else { 'Female' }
$voice = @($voices | Where-Object { $_.GetAttribute('Gender') -eq $wanted } | Select-Object -First 1)
if ($voice.Count -eq 0) { $voice = @($voices | Select-Object -First 1) }
$speaker.Voice=$voice[0]
$speaker.Rate=0
$speaker.Volume=100
$stream=New-Object -ComObject SAPI.SpFileStream
$stream.Format.Type=22
$stream.Open($data.output,3,$false)
$speaker.AudioOutputStream=$stream
try { $null=$speaker.Speak([string]$data.text,0) } finally { $stream.Close() }
$source=@{engine='Windows SAPI offline';voice=$voice[0].GetDescription();gender=$voice[0].GetAttribute('Gender');network_used=$false}
[System.IO.File]::WriteAllText(($data.output+'.voice.json'),($source | ConvertTo-Json),[System.Text.Encoding]::UTF8)
