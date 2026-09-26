#requires -Version 5.1
# Advanced entry point. Run this PowerShell script to uninstall GCC2CL.
[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$InstallDir,
    [switch]$RemoveSettings,
    [switch]$RemoveDirectory,
    [switch]$Quiet
)

$ErrorActionPreference = 'Stop'
if (-not $InstallDir) { $InstallDir = Join-Path $env:ProgramFiles 'Gcc2Cl' }

function Is-Administrator {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p = New-Object Security.Principal.WindowsPrincipal($id)
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}
function Restart-Elevated {
    $args = @('-NoProfile','-ExecutionPolicy','Bypass','-File',('"' + $PSCommandPath + '"'),'-InstallDir',('"' + $InstallDir + '"'))
    if ($RemoveSettings) { $args += '-RemoveSettings' }
    if ($RemoveDirectory) { $args += '-RemoveDirectory' }
    if ($Quiet) { $args += '-Quiet' }
    Start-Process powershell.exe -Verb RunAs -ArgumentList ($args -join ' ') -Wait
    exit $LASTEXITCODE
}
if (-not (Is-Administrator)) {
    Write-Host 'Administrator permission is required to remove files under Program Files.'
    if (-not $Quiet) { Read-Host 'Press Enter to continue with the UAC prompt' | Out-Null }
    Restart-Elevated
}

if (-not $Quiet) {
    Write-Host ''
    Write-Host 'GCC2CL UNINSTALLATION OPTIONS' -ForegroundColor Yellow
    $value = Read-Host "Installation directory [$InstallDir]"
    if ($value) { $InstallDir = $value }
    $value = Read-Host 'Remove GCC2CL_ARCH and GCC2CL_LOG settings? [Y/n]'
    $RemoveSettings = -not ($value -match '^(n|no)$')
    $value = Read-Host 'Remove the installation directory if it is empty? [Y/n]'
    $RemoveDirectory = -not ($value -match '^(n|no)$')
    Write-Host ''
}

$marker = Join-Path $InstallDir '.gcc2cl-installed'
if (-not (Test-Path $marker)) {
    Write-Warning "The installation marker was not found in $InstallDir."
    if (-not $Quiet) {
        $answer = Read-Host 'Remove known GCC2CL files and PATH entries anyway? [y/N]'
        if ($answer -notmatch '^(y|yes)$') { exit 0 }
    }
}

if (-not $Quiet) {
    Write-Host "This will remove the GCC2CL installation from: $InstallDir"
    $answer = Read-Host 'Continue? [y/N]'
    if ($answer -notmatch '^(y|yes)$') { Write-Host 'Cancelled.'; exit 0 }
}

$names = @('gcc.cmd','g++.cmd','x86_64-w64-mingw32-gcc.cmd','x86_64-w64-mingw32-g++.cmd','i686-w64-mingw32-gcc.cmd','i686-w64-mingw32-g++.cmd','mingw-shim.cmd','gcc2cl.py','Uninstall-Gcc2Cl.ps1','.gcc2cl-installed')
foreach ($name in $names) {
    $file = Join-Path $InstallDir $name
    if (Test-Path $file -PathType Leaf) { Remove-Item $file -Force; Write-Host "Removed $file" }
}

function Remove-FromPath([string]$scope) {
    $old = [Environment]::GetEnvironmentVariable('Path', $scope)
    if ($null -eq $old) { return }
    $items = @($old -split ';' | Where-Object { $_ -and $_.TrimEnd('\') -ine $InstallDir.TrimEnd('\') })
    [Environment]::SetEnvironmentVariable('Path', ($items -join ';'), $scope)
    Write-Host "Removed $InstallDir from the $scope PATH."
}
Remove-FromPath 'User'
Remove-FromPath 'Machine'

if ($RemoveSettings) {
    [Environment]::SetEnvironmentVariable('GCC2CL_ARCH', $null, 'User')
    [Environment]::SetEnvironmentVariable('GCC2CL_LOG', $null, 'User')
    Write-Host 'Removed GCC2CL_ARCH and GCC2CL_LOG user settings.'
}

if ($RemoveDirectory -and (Test-Path $InstallDir)) {
    if (@(Get-ChildItem -LiteralPath $InstallDir -Force).Count -eq 0) {
        Remove-Item $InstallDir -Force
        Write-Host "Removed empty directory $InstallDir"
    } else {
        Write-Warning "$InstallDir is not empty; it was preserved."
    }
}
Write-Host 'Restart terminals and IDEs to receive the updated PATH.'
if (-not $Quiet) { Read-Host 'Uninstallation finished. Press Enter to exit' | Out-Null }
