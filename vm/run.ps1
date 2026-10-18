# Run a scenario script in a throwaway Linux container (nothing touches this machine).
#   powershell -File vm\run.ps1                 # full real-user journey
#   powershell -File vm\run.ps1 wipe_check.sh   # focused wipe check
param([string]$Script = "journey.sh")
$vm = Split-Path -Parent $MyInvocation.MyCommand.Path
docker run --rm --cpus 8 --memory 6g -e SKIP_OLD `
    -v "${vm}:/vm" `
    python:3.12-slim `
    bash -c "tr -d '\r' < /vm/$Script > /tmp/run.sh && bash /tmp/run.sh"
