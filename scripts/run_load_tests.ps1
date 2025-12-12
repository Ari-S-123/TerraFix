<#
.SYNOPSIS
    TerraFix Load Testing Runner Script for Windows

.DESCRIPTION
    This script automates the setup and execution of TerraFix load testing
    experiments using Docker Compose with LocalStack (for AWS emulation) and
    Redis (for state storage).

.PARAMETER Command
    The command to execute: start, stop, status, test, all, clean

.PARAMETER Experiment
    Experiment type: throughput, resilience, scalability, all (default: all)

.PARAMETER Host
    Target host URL (default: http://localhost:8081)

.PARAMETER OutputDir
    Output directory for results (default: ./experiment_results)

.PARAMETER Users
    Number of concurrent users for load testing

.PARAMETER Duration
    Test duration (e.g., 5m, 1h)

.PARAMETER Latency
    Mock processing latency in milliseconds (default: 50)

.PARAMETER FailureRate
    Mock failure rate between 0.0 and 1.0 (default: 0.0)

.PARAMETER LocustUI
    Start Locust with web UI instead of headless mode

.EXAMPLE
    .\run_load_tests.ps1 start
    Starts the local testing environment

.EXAMPLE
    .\run_load_tests.ps1 all
    Starts environment, runs all tests, and generates report

.EXAMPLE
    .\run_load_tests.ps1 test -Experiment throughput -Users 20 -Duration "5m"
    Runs throughput test with 20 users for 5 minutes

.EXAMPLE
    .\run_load_tests.ps1 test -LocustUI
    Starts Locust with web UI for interactive testing
#>

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet("start", "stop", "status", "logs", "test", "all", "clean", "help")]
    [string]$Command = "help",

    [Alias("e")]
    [ValidateSet("throughput", "resilience", "scalability", "all")]
    [string]$Experiment = "all",

    [Alias("h")]
    [string]$Host = "http://localhost:8081",

    [Alias("o")]
    [string]$OutputDir = ".\experiment_results",

    [Alias("u")]
    [int]$Users = 10,

    [Alias("d")]
    [string]$Duration = "3m",

    [int]$Latency = 50,

    [double]$FailureRate = 0.0,

    [switch]$LocustUI
)

# Script directory and project root
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$ComposeFile = Join-Path $ProjectRoot "docker-compose.localstack.yml"

# =============================================================================
# Helper Functions
# =============================================================================

function Write-Info {
    param([string]$Message)
    Write-Host "[INFO] " -ForegroundColor Blue -NoNewline
    Write-Host $Message
}

function Write-Success {
    param([string]$Message)
    Write-Host "[SUCCESS] " -ForegroundColor Green -NoNewline
    Write-Host $Message
}

function Write-Warning {
    param([string]$Message)
    Write-Host "[WARNING] " -ForegroundColor Yellow -NoNewline
    Write-Host $Message
}

function Write-Error {
    param([string]$Message)
    Write-Host "[ERROR] " -ForegroundColor Red -NoNewline
    Write-Host $Message
}

function Test-Dependencies {
    $missing = @()

    # Check Docker
    if (-not (Get-Command "docker" -ErrorAction SilentlyContinue)) {
        $missing += "docker"
    }

    # Check Python
    if (-not (Get-Command "python" -ErrorAction SilentlyContinue)) {
        $missing += "python"
    }

    if ($missing.Count -gt 0) {
        Write-Error "Missing required dependencies: $($missing -join ', ')"
        Write-Info "Please install the missing dependencies and try again."
        exit 1
    }
}

function Get-DockerComposeCommand {
    # Check if 'docker compose' (v2) is available
    $result = docker compose version 2>&1
    if ($LASTEXITCODE -eq 0) {
        return "docker compose"
    }
    return "docker-compose"
}

function Wait-ForService {
    param(
        [string]$Url,
        [int]$MaxAttempts = 30
    )

    Write-Info "Waiting for service at $Url..."

    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        try {
            $response = Invoke-WebRequest -Uri $Url -Method Get -TimeoutSec 5 -ErrorAction SilentlyContinue
            if ($response.StatusCode -eq 200) {
                Write-Success "Service is ready!"
                return $true
            }
        }
        catch {
            Write-Host "." -NoNewline
        }
        Start-Sleep -Seconds 2
    }

    Write-Host ""
    Write-Error "Service did not become ready in time"
    return $false
}

# =============================================================================
# Command Functions
# =============================================================================

function Start-Environment {
    Write-Info "Starting TerraFix local testing environment..."

    Set-Location $ProjectRoot
    $composeCmd = Get-DockerComposeCommand

    # Set environment variables
    $env:MOCK_LATENCY_MS = $Latency
    $env:MOCK_FAILURE_RATE = $FailureRate
    $env:LOG_LEVEL = "INFO"

    # Start services
    $cmd = "$composeCmd -f `"$ComposeFile`" up -d localstack redis terrafix-api"
    Invoke-Expression $cmd

    # Wait for services
    Start-Sleep -Seconds 5
    Wait-ForService -Url "$Host/health" -MaxAttempts 60 | Out-Null

    # Check Redis
    $redisPing = docker exec terrafix-redis redis-cli ping 2>$null
    if ($redisPing -eq "PONG") {
        Write-Success "Redis is ready"
    }
    else {
        Write-Error "Redis is not responding"
        exit 1
    }

    # Check LocalStack
    try {
        $lsHealth = Invoke-WebRequest -Uri "http://localhost:4566/_localstack/health" -TimeoutSec 5 -ErrorAction SilentlyContinue
        if ($lsHealth.StatusCode -eq 200) {
            Write-Success "LocalStack is ready"
        }
    }
    catch {
        Write-Warning "LocalStack may not be fully ready (optional for load testing)"
    }

    Write-Success "Local testing environment is ready!"
    Write-Info "TerraFix API: $Host"
    Write-Info "Redis: localhost:6379"
    Write-Info "LocalStack: http://localhost:4566"
}

function Stop-Environment {
    Write-Info "Stopping TerraFix local testing environment..."

    Set-Location $ProjectRoot
    $composeCmd = Get-DockerComposeCommand

    $cmd = "$composeCmd -f `"$ComposeFile`" down"
    Invoke-Expression $cmd

    Write-Success "Environment stopped"
}

function Get-Status {
    Write-Info "Checking service status..."

    Set-Location $ProjectRoot
    $composeCmd = Get-DockerComposeCommand

    $cmd = "$composeCmd -f `"$ComposeFile`" ps"
    Invoke-Expression $cmd

    Write-Host ""
    Write-Info "Health checks:"

    # TerraFix API
    try {
        $apiHealth = Invoke-WebRequest -Uri "$Host/health" -TimeoutSec 5 -ErrorAction SilentlyContinue
        if ($apiHealth.StatusCode -eq 200) {
            Write-Host "  TerraFix API: " -NoNewline
            Write-Host "healthy" -ForegroundColor Green
        }
    }
    catch {
        Write-Host "  TerraFix API: " -NoNewline
        Write-Host "not responding" -ForegroundColor Red
    }

    # Redis
    $redisPing = docker exec terrafix-redis redis-cli ping 2>$null
    Write-Host "  Redis: " -NoNewline
    if ($redisPing -eq "PONG") {
        Write-Host "healthy" -ForegroundColor Green
    }
    else {
        Write-Host "not responding" -ForegroundColor Red
    }

    # LocalStack
    try {
        $lsHealth = Invoke-WebRequest -Uri "http://localhost:4566/_localstack/health" -TimeoutSec 5 -ErrorAction SilentlyContinue
        Write-Host "  LocalStack: " -NoNewline
        Write-Host "healthy" -ForegroundColor Green
    }
    catch {
        Write-Host "  LocalStack: " -NoNewline
        Write-Host "not responding" -ForegroundColor Yellow
    }
}

function Get-Logs {
    Write-Info "Tailing logs from all services..."

    Set-Location $ProjectRoot
    $composeCmd = Get-DockerComposeCommand

    $cmd = "$composeCmd -f `"$ComposeFile`" logs -f"
    Invoke-Expression $cmd
}

function Start-LoadTest {
    Write-Info "Running load tests..."

    Set-Location $ProjectRoot

    # Ensure output directory exists
    if (-not (Test-Path $OutputDir)) {
        New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
    }

    # Check if API server is running
    try {
        $apiHealth = Invoke-WebRequest -Uri "$Host/health" -TimeoutSec 5 -ErrorAction SilentlyContinue
    }
    catch {
        Write-Error "TerraFix API server is not running. Start it with: .\run_load_tests.ps1 start"
        exit 1
    }

    # Set experiment environment variable
    $env:TERRAFIX_EXPERIMENT = $Experiment

    $locustFile = Join-Path $ProjectRoot "src\terrafix\experiments\locustfile.py"

    if ($LocustUI) {
        Write-Info "Starting Locust with web UI at http://localhost:8089"
        $locustArgs = @(
            "-f", $locustFile,
            "--host", $Host
        )
    }
    else {
        $csvPath = Join-Path $OutputDir $Experiment
        $htmlPath = Join-Path $OutputDir "${Experiment}_report.html"

        $locustArgs = @(
            "-f", $locustFile,
            "--host", $Host,
            "--headless",
            "--csv", $csvPath,
            "--html", $htmlPath,
            "--users", $Users,
            "--spawn-rate", "2",
            "--run-time", $Duration
        )
    }

    Write-Info "Executing: locust $($locustArgs -join ' ')"
    & locust @locustArgs

    if (-not $LocustUI) {
        Write-Success "Load test completed!"
        Write-Info "Results saved to: $OutputDir"
    }
}

function Start-AllTests {
    Write-Info "Running complete load testing suite..."

    # Start environment
    Start-Environment

    # Wait for stabilization
    Start-Sleep -Seconds 5

    Set-Location $ProjectRoot

    # Ensure output directory exists
    if (-not (Test-Path $OutputDir)) {
        New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
    }

    # Run the full experiment suite
    Write-Info "Starting automated experiment runner..."

    $env:TERRAFIX_EXPERIMENT = $Experiment
    $env:MOCK_LATENCY_MS = $Latency

    python -m terrafix.experiments.run_experiments `
        --host $Host `
        --output $OutputDir `
        --experiment $Experiment

    Write-Success "All experiments completed!"
    Write-Info "Results saved to: $OutputDir"
    Write-Host ""
    Write-Info "View results:"
    Write-Info "  - Summary: $OutputDir\experiment_summary.html"
    Write-Info "  - Charts: $OutputDir\charts\"
}

function Clear-Environment {
    Write-Info "Cleaning up all data and volumes..."

    Set-Location $ProjectRoot
    $composeCmd = Get-DockerComposeCommand

    # Stop all services
    $cmd = "$composeCmd -f `"$ComposeFile`" down -v --remove-orphans"
    Invoke-Expression $cmd

    # Remove named volumes
    docker volume rm terrafix-localstack-data 2>$null
    docker volume rm terrafix-redis-data 2>$null

    # Remove experiment results
    if (Test-Path $OutputDir) {
        Remove-Item -Path $OutputDir -Recurse -Force
    }

    Write-Success "Cleanup complete"
}

function Show-Help {
    Get-Help $MyInvocation.MyCommand.Path -Full
}

# =============================================================================
# Main Entry Point
# =============================================================================

Test-Dependencies

switch ($Command) {
    "start" { Start-Environment }
    "stop" { Stop-Environment }
    "status" { Get-Status }
    "logs" { Get-Logs }
    "test" { Start-LoadTest }
    "all" { Start-AllTests }
    "clean" { Clear-Environment }
    "help" { Show-Help }
    default {
        Write-Error "Unknown command: $Command"
        Show-Help
        exit 1
    }
}

