# Scubiee Windows GPU Validation Script (DirectML)
# Run this in PowerShell on any Windows laptop with a GPU
# Works on NVIDIA, AMD, and Intel GPUs

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Scubiee Windows GPU Validation Suite" -ForegroundColor Cyan
Write-Host "  (DirectML — NVIDIA / AMD / Intel)" -ForegroundColor Cyan
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
    if ($out -match '"ok"') { exit 0 } else { exit 1 }
}

# Test 3: GPU detection
Test-Step "GPU detection (WMI)" {
    $out = ctx resources 2>&1 | Out-String
    if ($out -match 'DmlExecutionProvider' -or $out -match 'nvidia' -or $out -match 'Radeon' -or $out -match 'Intel') { exit 0 } else { exit 1 }
}

# Test 4: Setup
Test-Step "Setup acceleration (DirectML)" {
    ctx setup --repair
}

# Test 5: Verify DML profile
Test-Step "Profile is DML" {
    $out = ctx preflight 2>&1 | Out-String
    if ($out -match '"profile": "dml"' -or $out -match 'DmlExecutionProvider') { exit 0 } else { exit 1 }
}

# Test 6: Init a test repo
$testRepo = "$env:TEMP\scubiee-test-$([System.IO.Path]::GetRandomFileName().Split('.')[0])"
New-Item -ItemType Directory -Path $testRepo -Force | Out-Null
"def hello():`n    return 'world'`n`ndef greet(name):`n    return f'Hi {name}'" | Out-File "$testRepo\app.py" -Encoding utf8

Test-Step "Repository init" {
    ctx init $testRepo
}

# Test 7: Index
Test-Step "Index repository" {
    ctx index $testRepo --force
}

# Test 8: Search
Test-Step "Search works" {
    $out = ctx search "greet" $testRepo 2>&1 | Out-String
    if ($out -match 'app.py') { exit 0 } else { exit 1 }
}

# Test 9: Diagnose
Test-Step "Diagnostic report" {
    $out = ctx diagnose --no-tests 2>&1 | Out-String
    if ($out -match '"ok": true' -or $out -match 'Acceleration: dml') { exit 0 } else { exit 1 }
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
    exit 1
}

Write-Host "All tests passed! DirectML GPU acceleration is working." -ForegroundColor Green
exit 0
