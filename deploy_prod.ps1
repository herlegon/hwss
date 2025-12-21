# deploy_prod.ps1 - Copy files instead of symlinks
$ErrorActionPreference = "Stop"
$pythonDir = "C:\Users\Arnaud\AppData\Local\herlegon\python"
$modulesDir = "$pythonDir\Modules"

Write-Host "Deploying in PROD mode (copying files)..." -ForegroundColor Cyan

# Bootstrap - Remove symlinks first, then copy
Write-Host "Deploying bootstrap files..." -ForegroundColor Yellow
Remove-Item "$pythonDir\bootstrap*.pyd" -Force -ErrorAction SilentlyContinue

# Remove bootstrap symlinks if they exist
$bootstrapFiles = Get-ChildItem "$pythonDir\bootstrap*.py" -ErrorAction SilentlyContinue
foreach ($file in $bootstrapFiles) {
    if ($file.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
        Write-Host "  Removing bootstrap symlink: $($file.Name)" -ForegroundColor Yellow
        $file.Delete()
    }
}

# Now copy the actual bootstrap files
Copy-Item ".\bootstrap\bootstrap*.py" -Destination $pythonDir -Force

# Remove existing symlinks/directories first
Write-Host "Removing existing modules..." -ForegroundColor Yellow
$hwssTarget = "$modulesDir\hwss"
$hinstallTarget = "$modulesDir\hinstall"

if (Test-Path $hwssTarget) {
    if ((Get-Item $hwssTarget).Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
        # It's a symlink, just delete it
        Write-Host "  Removing hwss symlink" -ForegroundColor Yellow
        (Get-Item $hwssTarget).Delete()
    } else {
        # It's a directory, remove it
        Write-Host "  Removing hwss directory" -ForegroundColor Yellow
        Remove-Item $hwssTarget -Recurse -Force
    }
}

if (Test-Path $hinstallTarget) {
    if ((Get-Item $hinstallTarget).Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
        Write-Host "  Removing hinstall symlink" -ForegroundColor Yellow
        (Get-Item $hinstallTarget).Delete()
    } else {
        Write-Host "  Removing hinstall directory" -ForegroundColor Yellow
        Remove-Item $hinstallTarget -Recurse -Force
    }
}

# Recreate directories
Write-Host "Creating module directories..." -ForegroundColor Yellow
New-Item -ItemType Directory -Path $hwssTarget -Force | Out-Null
New-Item -ItemType Directory -Path $hinstallTarget -Force | Out-Null

# Copy files
Write-Host "Copying hwss files..." -ForegroundColor Yellow
Copy-Item ".\hwss\*.py" -Destination "$hwssTarget\" -Force

Write-Host "Copying hinstall files..." -ForegroundColor Yellow
Copy-Item "..\hinstall\hinstall\*.py" -Destination "$hinstallTarget\" -Force

Write-Host "`nDeployment complete!" -ForegroundColor Green
Write-Host "Starting server..." -ForegroundColor Cyan
& "$pythonDir\python.exe" "$pythonDir\bootstrap.py"
