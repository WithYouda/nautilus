[CmdletBinding()]
param(
    [string]$SourceRoot = '',
    [string]$BuildRoot = (Join-Path $env:LOCALAPPDATA 'NautilusBuild\windows-validation'),
    [string]$OutputDirectory = (Join-Path $env:USERPROFILE 'Downloads')
)
$ErrorActionPreference = 'Stop'
# WSL-launched PowerShell may inherit PATHEXT=.CPL, hiding SDK discovery helpers.
$env:PATHEXT = [Environment]::GetEnvironmentVariable('PATHEXT', 'Machine')
if (-not $SourceRoot) { $SourceRoot = Split-Path $PSScriptRoot -Parent }

# Use a local build cache: Windows native tools do not all support WSL UNC paths.
# Copy only build inputs, never the trial, installed app data, or Android outputs.
$files = @(
    'Cargo.toml', 'Cargo.lock', 'core\Cargo.toml',
    'src-tauri\Cargo.toml', 'src-tauri\build.rs', 'src-tauri\tauri.conf.json',
    'src-tauri\icons\icon.ico', 'src-tauri\icons\icon.png'
)
$directories = @('core\src', 'src-tauri\src', 'src-tauri\capabilities', 'dist')
foreach ($relative in $files + $directories) {
    if (-not (Test-Path (Join-Path $SourceRoot $relative))) {
        throw "Missing build input: $relative. Build the native frontend and icons first."
    }
}
$cargo = Join-Path $env:USERPROFILE '.cargo\bin\cargo.exe'
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
if (-not (Test-Path $cargo) -or -not (Test-Path $vswhere)) {
    throw 'Rust MSVC and Microsoft C++ Build Tools must be installed first.'
}
New-Item -ItemType Directory -Force $BuildRoot | Out-Null
$discoveryLog = Join-Path $BuildRoot 'vswhere.txt'
$discovery = Start-Process -FilePath $vswhere -ArgumentList '-latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath' -Wait -PassThru -NoNewWindow -RedirectStandardOutput $discoveryLog
if ($discovery.ExitCode -ne 0) { throw 'Visual Studio discovery failed.' }
$vsPath = (Get-Content -LiteralPath $discoveryLog -Raw).Trim()
if (-not $vsPath) { throw 'Microsoft C++ tools were not found.' }

foreach ($relative in $files) {
    $destination = Join-Path $BuildRoot $relative
    New-Item -ItemType Directory -Force (Split-Path $destination -Parent) | Out-Null
    Copy-Item -LiteralPath (Join-Path $SourceRoot $relative) -Destination $destination -Force
}
foreach ($relative in $directories) {
    $destination = Join-Path $BuildRoot $relative
    New-Item -ItemType Directory -Force $destination | Out-Null
    Get-ChildItem -LiteralPath (Join-Path $SourceRoot $relative) -Force | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $destination -Recurse -Force
    }
}
Push-Location $BuildRoot
try {
    # Explicit override leaves the user's existing default GNU toolchain unchanged.
    $stdoutLog = Join-Path $BuildRoot 'build.stdout.log'
    $stderrLog = Join-Path $BuildRoot 'build.stderr.log'
    Write-Output "BUILD_LOG=$stderrLog"
    $commandFile = Join-Path $BuildRoot 'build.cmd'
    @"
@echo off
call "$vsPath\Common7\Tools\VsDevCmd.bat" -arch=amd64 -host_arch=amd64 >NUL
if errorlevel 1 exit /b %errorlevel%
if not exist "%WindowsSdkDir%Lib\%WindowsSDKVersion%um\x64\kernel32.lib" (
    echo Windows SDK libraries were not found. 1>&2
    exit /b 1
)
"$cargo" +stable-x86_64-pc-windows-msvc build --locked --release --target x86_64-pc-windows-msvc --package nautilus-device --features tauri/custom-protocol
exit /b %errorlevel%
"@ | Set-Content -LiteralPath $commandFile -Encoding ASCII
    $build = Start-Process -FilePath $env:ComSpec -ArgumentList ('/d /c ""' + $commandFile + '""') -WorkingDirectory $BuildRoot -Wait -PassThru -NoNewWindow -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog
    if ($build.ExitCode -ne 0) {
        Get-Content -LiteralPath $stderrLog -Tail 30
        throw "Windows build failed: $($build.ExitCode)"
    }
    $binary = Join-Path $BuildRoot 'target\x86_64-pc-windows-msvc\release\nautilus-device.exe'
    New-Item -ItemType Directory -Force $OutputDirectory | Out-Null
    $filename = 'nautilus-independent-0.1.0-windows-x64-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.exe'
    $output = Join-Path $OutputDirectory $filename
    Copy-Item -LiteralPath $binary -Destination $output
    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $output).Hash
    Write-Output "OUTPUT=$output"
    Write-Output "SHA256=$hash"
}
finally { Pop-Location }
