# Start both regional FastAPI workers for the local ABT demo.
#
# Worker A: us-west-2  -> http://localhost:8080
# Worker B: us-east-1  -> http://localhost:8081
#
# Open http://localhost:8080 after both workers are up.

param(
    [string]$Python = ""
)

Set-Location (Split-Path $PSScriptRoot)

# ── Load .env ─────────────────────────────────────────────────────────────────
if (-not (Test-Path ".env")) {
    Write-Error ".env not found. Copy .env.example and fill in your DSQL endpoints."
    exit 1
}
Get-Content ".env" | ForEach-Object {
    if ($_ -match "^\s*([^#=\s][^=]*)\s*=\s*(.*)\s*$") {
        $k = $Matches[1].Trim(); $v = $Matches[2].Trim()
        [Environment]::SetEnvironmentVariable($k, $v, "Process")
    }
}

# ── Find Python ───────────────────────────────────────────────────────────────
$py = if ($Python) { $Python } else {
    @("python", "python3", "C:\Program Files\Python313\python.exe") |
    Where-Object { try { & $_ --version 2>$null; $true } catch { $false } } |
    Select-Object -First 1
}
if (-not $py) { Write-Error "Python not found. Pass -Python C:\path\to\python.exe"; exit 1 }
Write-Host "Using Python: $py"

$epA     = [Environment]::GetEnvironmentVariable("DSQL_ENDPOINT_A", "Process")
$epB     = [Environment]::GetEnvironmentVariable("DSQL_ENDPOINT_B", "Process")

Write-Host ""
Write-Host "=== ACME Booking Travel — Starting dual-region workers ==="
Write-Host ""

# ── Worker A — us-west-2, port 8080 ──────────────────────────────────────────
$envA = @{
    WORKER_REGION   = "us-west-2"
    DSQL_ENDPOINT   = $epA
    PEER_URL        = "http://localhost:8081"
    PEER_REGION     = "us-east-1"
}
# Merge with current environment
$allEnvA = [System.Collections.Generic.Dictionary[string,string]]::new()
[System.Environment]::GetEnvironmentVariables("Process").GetEnumerator() |
    ForEach-Object { $allEnvA[$_.Key] = $_.Value }
$envA.GetEnumerator() | ForEach-Object { $allEnvA[$_.Key] = $_.Value }

$procA = Start-Process -FilePath $py `
    -ArgumentList "-m", "uvicorn", "src.api.server:app", "--host", "0.0.0.0", "--port", "8080", "--log-level", "warning", "--no-access-log" `
    -PassThru -NoNewWindow `
    -RedirectStandardOutput "$env:TEMP\worker_a.log" `
    -RedirectStandardError  "$env:TEMP\worker_a_err.log" `
    -Environment $allEnvA
Write-Host "Worker A (us-west-2) PID $($procA.Id) — http://localhost:8080"

# ── Worker B — us-east-1, port 8081 ──────────────────────────────────────────
$envB = @{
    WORKER_REGION   = "us-east-1"
    DSQL_ENDPOINT   = $epB
    PEER_URL        = "http://localhost:8080"
    PEER_REGION     = "us-west-2"
}
$allEnvB = [System.Collections.Generic.Dictionary[string,string]]::new()
[System.Environment]::GetEnvironmentVariables("Process").GetEnumerator() |
    ForEach-Object { $allEnvB[$_.Key] = $_.Value }
$envB.GetEnumerator() | ForEach-Object { $allEnvB[$_.Key] = $_.Value }

$procB = Start-Process -FilePath $py `
    -ArgumentList "-m", "uvicorn", "src.api.server:app", "--host", "0.0.0.0", "--port", "8081", "--log-level", "warning", "--no-access-log" `
    -PassThru -NoNewWindow `
    -RedirectStandardOutput "$env:TEMP\worker_b.log" `
    -RedirectStandardError  "$env:TEMP\worker_b_err.log" `
    -Environment $allEnvB
Write-Host "Worker B (us-east-1) PID $($procB.Id) — http://localhost:8081"

# ── Wait for healthy responses ────────────────────────────────────────────────
Write-Host ""
Write-Host "Waiting for workers to be ready..." -NoNewline
$ready = $false
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep 1
    Write-Host "." -NoNewline
    try {
        $ra = Invoke-WebRequest -Uri "http://localhost:8080/health" -UseBasicParsing -TimeoutSec 2 -ErrorAction SilentlyContinue
        $rb = Invoke-WebRequest -Uri "http://localhost:8081/health" -UseBasicParsing -TimeoutSec 2 -ErrorAction SilentlyContinue
        if ($ra.StatusCode -eq 200 -and $rb.StatusCode -eq 200) { $ready = $true; break }
    } catch {}
}
Write-Host ""
if ($ready) { Write-Host "Both workers are healthy!" }
else        { Write-Host "WARNING: One or more workers may not have started. Check logs:" }

Write-Host ""
Write-Host "============================================"
Write-Host "  Worker A (us-west-2):  http://localhost:8080"
Write-Host "  Worker B (us-east-1):  http://localhost:8081"
Write-Host ""
Write-Host "  Open either URL in your browser."
Write-Host "  Logs: $env:TEMP\worker_a.log / worker_b.log"
Write-Host "  Press Ctrl+C or close this window to stop."
Write-Host "============================================"
Write-Host ""

# Keep running; Ctrl+C will stop the script
try {
    while (-not $procA.HasExited -and -not $procB.HasExited) {
        Start-Sleep 2
    }
} finally {
    Write-Host "Stopping workers..."
    if (-not $procA.HasExited) { $procA.Kill() }
    if (-not $procB.HasExited) { $procB.Kill() }
    Write-Host "Done."
}
