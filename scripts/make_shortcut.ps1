# Creates a "UI Compare" shortcut on the desktop that starts the web UI.
#   powershell -ExecutionPolicy Bypass -File scripts\make_shortcut.ps1
$root = Split-Path -Parent $PSScriptRoot
$link = Join-Path ([Environment]::GetFolderPath("Desktop")) "UI Compare.lnk"
$s = (New-Object -ComObject WScript.Shell).CreateShortcut($link)
$s.TargetPath = Join-Path $root "UI Compare.bat"
$s.WorkingDirectory = $root
$s.Description = "UI Comparison drag-and-drop app"
$s.Save()
Write-Output "Created $link"
