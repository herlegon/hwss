# deploy_dev.ps1
$ErrorActionPreference = "Stop"

$pythonDir = "C:\Users\Arnaud\AppData\Local\herlegon\python"
$modulesDir = "$pythonDir\modules"

Write-Host "Deploying in DEV mode with symlinks..." -ForegroundColor Cyan

# Bootstrap files (still copy these)
Write-Host "Deploying bootstrap files..." -ForegroundColor Yellow
Remove-Item "$pythonDir\bootstrap_*.pyd" -Force -ErrorAction SilentlyContinue
Copy-Item ".\bootstrap\*.py" -Destination $pythonDir -Force

# Deploy hwss with symlink
Write-Host "Setting up hwss symlink..." -ForegroundColor Yellow
$hwssTarget = "$modulesDir\hwss"
if (Test-Path $hwssTarget) {
    # Remove existing directory or symlink
    if ((Get-Item $hwssTarget).Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
        (Get-Item $hwssTarget).Delete()
    } else {
        Remove-Item $hwssTarget -Recurse -Force
    }
}
New-Item -ItemType SymbolicLink -Path $hwssTarget -Target "A:\hwss\hwss" -Force | Out-Null
Write-Host "  Created symlink: $hwssTarget -> A:\hwss\hwss" -ForegroundColor Green

# Deploy hinstall with symlink
Write-Host "Setting up hinstall symlink..." -ForegroundColor Yellow
$hinstallTarget = "$modulesDir\hinstall"
if (Test-Path $hinstallTarget) {
    # Remove existing directory or symlink
    if ((Get-Item $hinstallTarget).Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
        (Get-Item $hinstallTarget).Delete()
    } else {
        Remove-Item $hinstallTarget -Recurse -Force
    }
}
New-Item -ItemType SymbolicLink -Path $hinstallTarget -Target "A:\hinstall\hinstall" -Force | Out-Null
Write-Host "  Created symlink: $hinstallTarget -> A:\hinstall\hinstall" -ForegroundColor Green

# Start server
Write-Host "`nStarting server..." -ForegroundColor Cyan
& "$pythonDir\python.exe" "$pythonDir\bootstrap.py"
