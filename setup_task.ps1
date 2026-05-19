# 以管理员身份运行此脚本
$taskName = "ReutersBloombergDailyNews"
$batchPath = "C:\Users\20105\Desktop\cc\news-push\run.bat"

$action = New-ScheduledTaskAction -Execute $batchPath
$trigger = New-ScheduledTaskTrigger -Daily -At 8:00AM
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description "路透社&彭博社每日热点微信推送"

Write-Host "任务已创建！每天早上 8:00 自动推送" -ForegroundColor Green
Write-Host "检查: 打开 taskschd.msc 搜索 '$taskName'" -ForegroundColor Yellow
