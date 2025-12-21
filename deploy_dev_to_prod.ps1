# deploy_dev.ps1
$ErrorActionPreference = "Stop"

$pythonDir = "C:\Users\Arnaud\AppData\Local\herlegon\python"
$modulesDir = "$pythonDir\Modules"

Write-Host "Deploying in DEV mode with symlinks..." -ForegroundColor Cyan

# Deploy bootstrap files with symlinks
Write-Host "Setting up bootstrap symlinks..." -ForegroundColor Yellow
Remove-Item "$pythonDir\bootstrap*.pyd" -Force -ErrorAction SilentlyContinue

# Get all bootstrap*.py files in the bootstrap directory (including bootstrap.py)
$bootstrapFiles = Get-ChildItem ".\bootstrap\bootstrap*.py"
foreach ($file in $bootstrapFiles) {
    $target = "$pythonDir\$($file.Name)"

    if (Test-Path $target) {
        if ((Get-Item $target).Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
            (Get-Item $target).Delete()
        } else {
            Remove-Item $target -Force
        }
    }

    New-Item -ItemType SymbolicLink -Path $target -Target $file.FullName -Force | Out-Null
    Write-Host "  Created symlink: $($file.Name) -> $($file.FullName)" -ForegroundColor Green
}

# Deploy hwss with symlink
Write-Host "Setting up hwss symlink..." -ForegroundColor Yellow
$hwssTarget = "$modulesDir\hwss"

# Remove .pyd files from hwss source directory before symlinking
$hwssSource = "A:\hwss\hwss"
if (Test-Path $hwssSource) {
    $pydFiles = Get-ChildItem "$hwssSource\*.pyd" -ErrorAction SilentlyContinue
    if ($pydFiles) {
        Write-Host "  Removing .pyd files from hwss source..." -ForegroundColor Yellow
        foreach ($pyd in $pydFiles) {
            Remove-Item $pyd.FullName -Force
            Write-Host "    Removed: $($pyd.Name)" -ForegroundColor Gray
        }
    }
}

if (Test-Path $hwssTarget) {
    # Remove existing directory or symlink
    if ((Get-Item $hwssTarget).Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
        (Get-Item $hwssTarget).Delete()
    } else {
        Remove-Item $hwssTarget -Recurse -Force
    }
}
New-Item -ItemType SymbolicLink -Path $hwssTarget -Target $hwssSource -Force | Out-Null
Write-Host "  Created symlink: $hwssTarget -> $hwssSource" -ForegroundColor Green

# Deploy hinstall with symlink
Write-Host "Setting up hinstall symlink..." -ForegroundColor Yellow
$hinstallTarget = "$modulesDir\hinstall"

# Remove .pyd files from hinstall source directory before symlinking
$hinstallSource = "A:\hinstall\hinstall"
if (Test-Path $hinstallSource) {
    $pydFiles = Get-ChildItem "$hinstallSource\*.pyd" -ErrorAction SilentlyContinue
    if ($pydFiles) {
        Write-Host "  Removing .pyd files from hinstall source..." -ForegroundColor Yellow
        foreach ($pyd in $pydFiles) {
            Remove-Item $pyd.FullName -Force
            Write-Host "    Removed: $($pyd.Name)" -ForegroundColor Gray
        }
    }
}

if (Test-Path $hinstallTarget) {
    # Remove existing directory or symlink
    if ((Get-Item $hinstallTarget).Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
        (Get-Item $hinstallTarget).Delete()
    } else {
        Remove-Item $hinstallTarget -Recurse -Force
    }
}
New-Item -ItemType SymbolicLink -Path $hinstallTarget -Target $hinstallSource -Force | Out-Null
Write-Host "  Created symlink: $hinstallTarget -> $hinstallSource" -ForegroundColor Green

# Start server
Write-Host "`nStarting server..." -ForegroundColor Cyan
& "$pythonDir\python.exe" "$pythonDir\bootstrap.py" "--to-prod"
