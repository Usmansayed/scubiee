<#
  Context Engine test entrypoint.

  Examples:
    .\scripts\ce-test.ps1 quick
    .\scripts\ce-test.ps1 core
    .\scripts\ce-test.ps1 fault
    .\scripts\ce-test.ps1 clients -Clients
#>
[CmdletBinding()]
param(
    [ValidateSet("quick", "core", "fault", "install", "clients", "all")]
    [string]$Tier = "quick",
    [string]$Path = ".",
    [switch]$Clients
)

$ErrorActionPreference = "Stop"
$env:PYTHONPATH = "packages" + $(if ($env:PYTHONPATH) { ";$env:PYTHONPATH" } else { "" })
$args = @("-m", "pipeline", "test", $Tier, $Path)
if ($Clients) {
    $args += "--clients"
}
& python @args
exit $LASTEXITCODE
