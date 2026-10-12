$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[System.Text.Encoding]::UTF8
$speaker=New-Object -ComObject SAPI.SpVoice
$voices=@($speaker.GetVoices() | ForEach-Object {
    @{name=$_.GetDescription();gender=$_.GetAttribute('Gender');culture=[System.Globalization.CultureInfo]::GetCultureInfo([Convert]::ToInt32($_.GetAttribute('Language').Split(';')[0],16)).Name}
})
ConvertTo-Json -InputObject $voices -Compress
