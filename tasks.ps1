<#
    Retryable - Windows task runner.

    GNU make is not available on Windows by default, but the Makefile is the
    canonical interface for reviewers on macOS and Linux. This script mirrors
    it so both audiences get a one-command experience.

    Usage:   .\tasks.ps1 <task>
    Example: .\tasks.ps1 db-up
#>

param([Parameter(Position = 0)][string]$Task = "help")

$ErrorActionPreference = "Stop"

function Show-Help {
    Write-Host ""
    Write-Host "Retryable - developer commands" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  .\tasks.ps1 install    install python dependencies"
    Write-Host "  .\tasks.ps1 db-up      start postgres and wait until healthy"
    Write-Host "  .\tasks.ps1 db-down    stop postgres (data preserved)"
    Write-Host "  .\tasks.ps1 db-shell         open a psql prompt"
    Write-Host "  .\tasks.ps1 migrate          apply alembic migrations up to head"
    Write-Host "  .\tasks.ps1 run              run the API server on :8000"
    Write-Host "  .\tasks.ps1 dispatch         run the outbox dispatcher once"
    Write-Host "  .\tasks.ps1 verify-razorpay  one-off check that real .env credentials work"
    Write-Host "  .\tasks.ps1 eval             run the evaluation harness against the real Razorpay API"
    Write-Host "  .\tasks.ps1 test             run the test suite"
    Write-Host "  .\tasks.ps1 lint             lint and format check"
    Write-Host ""
    Write-Host "  demo is added in Stage 10." -ForegroundColor DarkGray
    Write-Host ""
}

switch ($Task) {
    "install" { pip install -r requirements.txt }

    "db-up" {
        docker compose up -d db
        Write-Host "waiting for postgres to accept connections..." -ForegroundColor DarkGray
        $deadline = (Get-Date).AddSeconds(90)
        while ((Get-Date) -lt $deadline) {
            docker compose exec -T db pg_isready -U retryable -d retryable 2>&1 | Out-Null
            if ($LASTEXITCODE -eq 0) {
                Write-Host "postgres ready on localhost:5432" -ForegroundColor Green
                exit 0
            }
            Start-Sleep -Seconds 1
        }
        Write-Host "timed out waiting for postgres. try: docker compose logs db" -ForegroundColor Red
        exit 1
    }

    "db-down"  { docker compose down }
    "db-logs"  { docker compose logs -f db }
    "db-shell" { docker compose exec db psql -U retryable -d retryable }
    "migrate"  { alembic upgrade head }
    "run"      { uvicorn src.api.main:app --reload --port 8000 }
    "dispatch" { python scripts/run_dispatcher.py }
    "verify-razorpay" { python scripts/verify_razorpay_connection.py }
    "eval"     { python -m eval.run_eval }
    "test"     { pytest -q }

    "lint" {
        ruff check src tests migrations scripts eval
        ruff format --check src tests migrations scripts eval
    }

    "fmt" { ruff format src tests migrations scripts eval }

    default { Show-Help }
}
