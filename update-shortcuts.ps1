$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
$shell = New-Object -ComObject WScript.Shell
$icon = Join-Path $projectRoot "assets\app-icon.ico"
$command = Join-Path $env:SystemRoot "System32\cmd.exe"

function Save-ProjectShortcut {
    param([string]$Name, [string]$Target, [string]$Arguments = "", [string]$Description = "")
    $shortcut = $shell.CreateShortcut((Join-Path $projectRoot $Name))
    $shortcut.TargetPath = $Target
    $shortcut.Arguments = $Arguments
    $shortcut.WorkingDirectory = $projectRoot
    $shortcut.IconLocation = $icon
    $shortcut.Description = $Description
    $shortcut.Save()
    Write-Host "$Name -> $Target"
}

$sourceArguments = '/c ""' + (Join-Path $projectRoot "launch-app.cmd") + '""'
$builds = @(
    (Join-Path $projectRoot "dist\Marketor\Marketor.exe"),
    (Join-Path $projectRoot "dist\chat-workspace\Marketor\Marketor.exe")
) | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
    Get-Item | Sort-Object LastWriteTimeUtc -Descending

if ($builds) {
    Save-ProjectShortcut "Marketor 市场航图.lnk" $builds[0].FullName "" "启动本项目最新打包版本"
} else {
    Save-ProjectShortcut "Marketor 市场航图.lnk" $command $sourceArguments "启动本项目源码版本"
}
Save-ProjectShortcut "Marketor 源码开发版.lnk" $command $sourceArguments "启动当前项目源码，适合开发与验证"

$installer = Get-ChildItem -LiteralPath (Join-Path $projectRoot "installer-output") -Filter "Marketor-Setup-*.exe" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
if ($installer) {
    Save-ProjectShortcut "安装或更新 Marketor.lnk" $installer.FullName "" "安装本项目最新构建的 Marketor"
}
