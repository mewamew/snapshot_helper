$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\SnapTool.lnk")
$Shortcut.TargetPath = "D:\dev\snap_tools\run.bat"
$Shortcut.WorkingDirectory = "D:\dev\snap_tools"
$Shortcut.WindowStyle = 7
$Shortcut.Save()
Write-Host "Startup shortcut created successfully!"
