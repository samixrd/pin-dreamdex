$ErrorActionPreference = 'Stop'
$action = New-ScheduledTaskAction -Execute 'C:\Program Files\Git\bin\bash.exe' `
  -Argument '-lc "cd /c/Users/Acer/pin-probe && bash supervise.sh >> data/supervise.out 2>&1"'
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 10) -RepetitionDuration (New-TimeSpan -Days 3)
$settings = New-ScheduledTaskSettingsSet -Hidden -StartWhenAvailable -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName 'PIN-Supervisor' -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName 'PIN-Supervisor'
Write-Output 'PIN-Supervisor registered + started'
