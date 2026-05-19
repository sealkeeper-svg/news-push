powershell -Command "$task = Get-ScheduledTask -TaskName 'ReutersBloombergDailyNews'; $task.Settings.DisallowStartIfOnBatteries = $false; $task.Settings.StopIfGoingOnBatteries = $false; $task.Settings.StartWhenAvailable = $true; Set-ScheduledTask -TaskName 'ReutersBloombergDailyNews' -Settings $task.Settings; Write-Host 'Done - missed tasks will run when PC wakes up'"
pause
