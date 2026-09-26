#requires -Version 5.1
# Advanced entry point. Run this PowerShell script to install GCC2CL.
[CmdletBinding()]
param(
    [string]$InstallDir,
    [ValidateSet('User','Machine')]
    [string]$PathScope,
    [ValidateSet('x64','x64_x86')]
    [string]$Architecture,
    [switch]$EnableLogging,
    [switch]$Quiet,
    [switch]$SkipCleanup
)

$ErrorActionPreference = 'Stop'
$sourceDir = $PSScriptRoot
if (-not $InstallDir) { $InstallDir = Join-Path $env:ProgramFiles 'Gcc2Cl' }
if (-not $PathScope) { $PathScope = 'User' }
if (-not $Architecture) { $Architecture = 'x64' }

function Is-Administrator {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p = New-Object Security.Principal.WindowsPrincipal($id)
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Restart-Elevated {
    $argList = @('-NoProfile','-ExecutionPolicy','Bypass','-File',('"' + $PSCommandPath + '"'))
    foreach ($key in @('InstallDir','PathScope','Architecture')) {
        $value = Get-Variable $key -ValueOnly
        if ($value) { $argList += @('-' + $key, ('"' + $value + '"')) }
    }
    if ($EnableLogging) { $argList += '-EnableLogging' }
    if ($Quiet) { $argList += '-Quiet' }
    if ($SkipCleanup) { $argList += '-SkipCleanup' }
    Start-Process powershell.exe -Verb RunAs -ArgumentList ($argList -join ' ') -Wait
    exit $LASTEXITCODE
}

if (-not (Is-Administrator)) {
    Write-Host 'Administrator permission is required to install under Program Files.'
    if (-not $Quiet) { Read-Host 'Press Enter to continue with the UAC prompt' | Out-Null }
    Restart-Elevated
}

if (-not $Quiet) {
    Write-Host ''
    Write-Host 'GCC2CL INSTALLATION OPTIONS' -ForegroundColor Cyan
    $value = Read-Host "Install directory [$InstallDir]"
    if ($value) { $InstallDir = $value }
    do { $value = Read-Host "PATH scope: User or Machine [$PathScope]" } while ($value -and $value -notin @('User','Machine'))
    if ($value) { $PathScope = $value }
    do { $value = Read-Host "Architecture: x64 or x64_x86 [$Architecture]" } while ($value -and $value -notin @('x64','x64_x86'))
    if ($value) { $Architecture = $value }
    $value = Read-Host 'Enable command logging? [y/N]'
    $EnableLogging = ($value -match '^(y|yes)$')
    $value = Read-Host 'Clean previous GCC2CL residue in both scopes? [Y/n]'
    $SkipCleanup = ($value -match '^(n|no)$')
    Write-Host ''
}

function Normalize-Directory([string]$path) {
    try { return [IO.Path]::GetFullPath($path).TrimEnd('\\') } catch { return $path.TrimEnd('\\') }
}

function Remove-Gcc2ClResidues {
    # These are directories used by this project in earlier installer versions.
    # Only exact known entries are removed; unrelated PATH entries are preserved.
    $knownDirs = @(
        $InstallDir,
        (Join-Path $env:ProgramFiles 'Gcc2Cl'),
        (Join-Path $env:USERPROFILE 'gcc2cl-shims')
    ) | Where-Object { $_ } | ForEach-Object { Normalize-Directory $_ } | Select-Object -Unique
    $sourceNormalized = Normalize-Directory $sourceDir

    foreach ($scope in @('User','Machine')) {
        $oldPath = [Environment]::GetEnvironmentVariable('Path', $scope)
        if ($null -ne $oldPath) {
            $kept = @($oldPath -split ';' | Where-Object {
                if (-not $_) { return $false }
                $entry = Normalize-Directory $_.Trim()
                $leaf = [IO.Path]::GetFileName($entry)
                return (($knownDirs -notcontains $entry) -and $leaf -notin @('Gcc2Cl','gcc2cl-shims'))
            })
            [Environment]::SetEnvironmentVariable('Path', ($kept -join ';'), $scope)
        }
        # Remove stale settings in both scopes, not just the current user scope.
        foreach ($name in @('GCC2CL_ARCH','GCC2CL_LOG')) {
            [Environment]::SetEnvironmentVariable($name, $null, $scope)
        }
    }

    $oldShimDir = Join-Path $env:USERPROFILE 'gcc2cl-shims'
    $oldFiles = @('gcc.cmd','g++.cmd','x86_64-w64-mingw32-gcc.cmd','x86_64-w64-mingw32-g++.cmd','i686-w64-mingw32-gcc.cmd','i686-w64-mingw32-g++.cmd','mingw-shim.cmd','gcc2cl.py')
    foreach ($dir in @($oldShimDir, $InstallDir)) {
        if (-not $dir -or (Normalize-Directory $dir) -eq $sourceNormalized) { continue }
        foreach ($name in $oldFiles) {
            $file = Join-Path $dir $name
            if (Test-Path -LiteralPath $file -PathType Leaf) { Remove-Item -LiteralPath $file -Force }
        }
        if ((Test-Path -LiteralPath $dir -PathType Container) -and @(Get-ChildItem -LiteralPath $dir -Force).Count -eq 0) {
            Remove-Item -LiteralPath $dir -Force
        }
    }
    Write-Host 'Cleaned known GCC2CL PATH, environment-variable, and old shim residues.'
}

if (-not $SkipCleanup) {
    Remove-Gcc2ClResidues
}

$required = @('gcc2cl.py','mingw-shim.cmd')
foreach ($file in $required) {
    if (-not (Test-Path (Join-Path $sourceDir $file) -PathType Leaf)) {
        throw "Missing $file beside this installer: $sourceDir"
    }
}

if (-not $Quiet) {
    Write-Host ''
    Write-Host 'GCC-to-MSVC installer'
    Write-Host "Source:       $sourceDir"
    Write-Host "Install path: $InstallDir"
    Write-Host "PATH scope:   $PathScope"
    Write-Host "Architecture: $Architecture"
    Write-Host ''
    $answer = Read-Host 'Continue? [Y/n]'
    if ($answer -and $answer -notmatch '^(y|yes)$') { Write-Host 'Cancelled.'; exit 0 }
}

New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
Copy-Item (Join-Path $sourceDir 'gcc2cl.py') (Join-Path $InstallDir 'gcc2cl.py') -Force
Copy-Item (Join-Path $sourceDir 'mingw-shim.cmd') (Join-Path $InstallDir 'mingw-shim.cmd') -Force

$compilerNames = @('gcc','g++','x86_64-w64-mingw32-gcc','x86_64-w64-mingw32-g++','i686-w64-mingw32-gcc','i686-w64-mingw32-g++')
foreach ($name in $compilerNames) {
    Copy-Item (Join-Path $sourceDir 'mingw-shim.cmd') (Join-Path $InstallDir ($name + '.cmd')) -Force
}

# Copy the uninstall script for convenience, but it is not required for removal.
if (Test-Path (Join-Path $sourceDir 'Uninstall-Gcc2Cl.ps1')) {
    Copy-Item (Join-Path $sourceDir 'Uninstall-Gcc2Cl.ps1') (Join-Path $InstallDir 'Uninstall-Gcc2Cl.ps1') -Force
}

Set-Content -LiteralPath (Join-Path $InstallDir '.gcc2cl-installed') -Value "Installed $(Get-Date -Format o)" -Encoding UTF8

function Add-ToPath([string]$scope) {
    $old = [Environment]::GetEnvironmentVariable('Path', $scope)
    $items = @($old -split ';' | Where-Object { $_ -and $_.TrimEnd('\') -ine $InstallDir.TrimEnd('\') })
    [Environment]::SetEnvironmentVariable('Path', (($InstallDir + ';' + ($items -join ';')).Trim(';')), $scope)
}
Add-ToPath $PathScope
[Environment]::SetEnvironmentVariable('GCC2CL_ARCH', $Architecture, 'User')
if ($EnableLogging) {
    [Environment]::SetEnvironmentVariable('GCC2CL_LOG', (Join-Path $env:TEMP 'gcc2cl-calls.log'), 'User')
}

Write-Host ''
Write-Host "Installed successfully to $InstallDir"
Write-Host "Added installation directory to the $PathScope PATH."
Write-Host "Default architecture: $Architecture"
if ($EnableLogging) { Write-Host "Logging enabled: $env:TEMP\gcc2cl-calls.log" }
Write-Host 'Restart terminals and IDEs before testing.'
if (-not $Quiet) { Read-Host 'Installation finished. Press Enter to exit' | Out-Null }
