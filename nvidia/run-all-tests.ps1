# Scubiee NVIDIA Validation Script
# Run this in PowerShell on the NVIDIA Windows laptop
# It will test each layer and report results

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Scubiee NVIDIA Laptop Validation Suite" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

$pass = 0
$fail = 0
$results = @()

function Test-Step {
    param([string]$Name, [scriptblock]$Block)
    Write-Host "[$($pass + $fail + 1)] Testing: $Name..." -ForegroundColor Yellow
    try {
        $output = & $Block 2>&1
        $exitCode = $LASTEXITCODE
        if ($exitCode -eq 0) {
            Write-Host "    PASS" -ForegroundColor Green
            $script:pass++
            $script:results += [PSCustomObject]@{Test=$Name; Status="PASS"; Detail=""}
        } else {
            Write-Host "    FAIL (exit code $exitCode)" -ForegroundColor Red
            $script:fail++
            $script:results += [PSCustomObject]@{Test=$Name; Status="FAIL"; Detail=$output | Select-Object -Last 3}
        }
    } catch {
        Write-Host "    FAIL (exception: $_)" -ForegroundColor Red
        $script:fail++
        $script:results += [PSCustomObject]@{Test=$Name; Status="FAIL"; Detail=$_.Exception.Message}
    }
    Write-Host ""
}

# Test 1: Version
Test-Step "CLI version" {
    ctx --version
}

# Test 2: Preflight
Test-Step "Preflight capabilities" {
    $out = ctx preflight 2>&1 | Out-String
    if ($out -match '"ok": true') { exit 0 } else { exit 1 }
}

# Test 3: Hardware detection
Test-Step "Hardware detection" {
    $out = ctx resources 2>&1 | Out-String
    if ($out -match 'nvidia' -or $out -match 'NVIDIA' -or $out -match 'cuda') { exit 0 } else { exit 1 }
}

# Test 4: nvidia-smi
Test-Step "NVIDIA driver (nvidia-smi)" {
    nvidia-smi -L
}

# Test 5: Setup/repair
Test-Step "Setup acceleration" {
    ctx setup --repair
}

# Test 6: Init a test repo
$testRepo = "$env:TEMP\scubiee-test-$([System.IO.Path]::GetRandomFileName().Split('.')[0])"
New-Item -ItemType Directory -Path $testRepo -Force | Out-Null
"def hello():`n    return 'world'" | Out-File "$testRepo\app.py" -Encoding utf8

Test-Step "Repository init" {
    ctx init $testRepo
}

# Test 7: Index
Test-Step "Index repository" {
    ctx index $testRepo --force
}

# Test 8: Search
Test-Step "Search works" {
    $out = ctx search "hello" $testRepo 2>&1 | Out-String
    if ($out -match 'app.py') { exit 0 } else { exit 1 }
}

# Test 9: Diagnose
Test-Step "Diagnostic report" {
    ctx diagnose --no-tests
}

# Cleanup
Remove-Item -Recurse -Force $testRepo -ErrorAction SilentlyContinue

# Summary
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Results: $pass PASSED, $fail FAILED" -ForegroundColor $(if ($fail -eq 0) { "Green" } else { "Red" })
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
$results | Format-Table -AutoSize

if ($fail -gt 0) {
    Write-Host "Some tests failed. Run 'ctx diagnose' and share the log file." -ForegroundColor Yellow
    Write-Host "See nvidia/README.md for fix instructions." -ForegroundColor Yellow
    exit 1
}

Write-Host "All tests passed! Ready for Kiro." -ForegroundColor Green
exit 0
