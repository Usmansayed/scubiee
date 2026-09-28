# Enable Windows Error Reporting LocalDumps for the Scubiee engine interpreter
# (issue 2: the ONNX Runtime 0xc0000005 crash left no dump).
#
# WER LocalDumps lives under HKLM, so this must run elevated:
#   powershell -ExecutionPolicy Bypass -File scripts/enable_wer_localdumps.ps1            # enable (minidumps)
#   powershell -ExecutionPolicy Bypass -File scripts/enable_wer_localdumps.ps1 -Full      # full dumps (~engine private bytes each)
#   powershell -ExecutionPolicy Bypass -File scripts/enable_wer_localdumps.ps1 -Check     # show current settings
#   powershell -ExecutionPolicy Bypass -File scripts/enable_wer_localdumps.ps1 -Remove    # undo
#
# The keys are per image name (pythonw.exe / python.exe), so they apply to every
# Python on this machine, not only Scubiee. Dumps go to %LOCALAPPDATA%\CrashDumps\scubiee.
# https://learn.microsoft.com/en-us/windows/win32/wer/collecting-user-mode-dumps

param(
    [switch]$Full,
    [switch]$Check,
    [switch]$Remove
)

$ErrorActionPreference = "Stop"
$Base = "HKLM:\SOFTWARE\Microsoft\Windows\Windows Error Reporting\LocalDumps"
$Images = @("pythonw.exe", "python.exe")
$Folder = Join-Path $env:LOCALAPPDATA "CrashDumps\scubiee"

function Show-State {
    foreach ($img in $Images) {
        $key = Join-Path $Base $img
        if (Test-Path $key) {
            $p = Get-ItemProperty $key
            Write-Host "[wer] $img DumpFolder=$($p.DumpFolder) DumpType=$($p.DumpType) DumpCount=$($p.DumpCount)"
        } else {
            Write-Host "[wer] $img not configured"
        }
    }
}

if ($Check) { Show-State; exit 0 }

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) {
    Write-Host "[wer] needs an elevated PowerShell (HKLM). Nothing changed." -ForegroundColor Red
    Show-State
    exit 2
}

if ($Remove) {
    foreach ($img in $Images) {
        $key = Join-Path $Base $img
        if (Test-Path $key) { Remove-Item $key -Recurse -Force; Write-Host "[wer] removed $img" }
    }
    exit 0
}

New-Item -ItemType Directory -Path $Folder -Force | Out-Null
foreach ($img in $Images) {
    $key = Join-Path $Base $img
    if (-not (Test-Path $key)) { New-Item -Path $key -Force | Out-Null }
    New-ItemProperty -Path $key -Name DumpFolder -PropertyType ExpandString -Value $Folder -Force | Out-Null
    New-ItemProperty -Path $key -Name DumpType -PropertyType DWord -Value ($(if ($Full) { 2 } else { 1 })) -Force | Out-Null
    New-ItemProperty -Path $key -Name DumpCount -PropertyType DWord -Value 5 -Force | Out-Null
}
Write-Host "[wer] OK: next pythonw/python crash writes a dump to $Folder" -ForegroundColor Green
Show-State
