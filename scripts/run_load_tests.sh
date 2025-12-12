#!/usr/bin/env bash
# =============================================================================
# TerraFix Load Testing Runner Script
# =============================================================================
#
# This script automates the setup and execution of TerraFix load testing
# experiments using Docker Compose with LocalStack (for AWS emulation) and
# Redis (for state storage).
#
# Usage:
#   ./scripts/run_load_tests.sh [command] [options]
#
# Commands:
#   start       Start the local testing environment (Redis + API server)
#   stop        Stop and cleanup the testing environment
#   status      Check status of all services
#   logs        Tail logs from all services
#   test        Run load tests (requires running environment)
#   all         Start environment, run all tests, generate report
#   clean       Remove all data volumes and reset environment
#
# Options:
#   --experiment TYPE   Experiment type: throughput, resilience, scalability, all
#   --host URL          Target host URL (default: http://localhost:8081)
#   --output DIR        Output directory for results (default: ./experiment_results)
#   --users N           Number of concurrent users
#   --duration TIME     Test duration (e.g., 5m, 1h)
#   --latency MS        Mock processing latency in milliseconds
#   --failure-rate N    Mock failure rate (0.0 to 1.0)
#   --locust-ui         Start Locust with web UI instead of headless
#
# Examples:
#   # Start environment and run all experiments
#   ./scripts/run_load_tests.sh all
#
#   # Run specific experiment
#   ./scripts/run_load_tests.sh test --experiment throughput
#
#   # Start environment with custom latency
#   ./scripts/run_load_tests.sh start --latency 100
#
#   # Run with Locust web UI for interactive testing
#   ./scripts/run_load_tests.sh test --locust-ui
#
# =============================================================================

set -euo pipefail

# Script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Default configuration
COMPOSE_FILE="${PROJECT_ROOT}/docker-compose.localstack.yml"
OUTPUT_DIR="${PROJECT_ROOT}/experiment_results"
HOST="http://localhost:8081"
EXPERIMENT="all"
USERS=""
DURATION=""
MOCK_LATENCY_MS="50"
MOCK_FAILURE_RATE="0.0"
LOCUST_UI=false

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# =============================================================================
# Helper Functions
# =============================================================================

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_dependencies() {
    local missing=()

    if ! command -v docker &> /dev/null; then
        missing+=("docker")
    fi

    if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null 2>&1; then
        missing+=("docker-compose")
    fi

    if ! command -v python &> /dev/null && ! command -v python3 &> /dev/null; then
        missing+=("python3")
    fi

    if [ ${#missing[@]} -gt 0 ]; then
        log_error "Missing required dependencies: ${missing[*]}"
        log_info "Please install the missing dependencies and try again."
        exit 1
    fi
}

get_docker_compose_cmd() {
    if docker compose version &> /dev/null 2>&1; then
        echo "docker compose"
    else
        echo "docker-compose"
    fi
}

wait_for_service() {
    local url=$1
    local max_attempts=${2:-30}
    local attempt=1

    log_info "Waiting for service at ${url}..."

    while [ $attempt -le $max_attempts ]; do
        if curl -sf "${url}" > /dev/null 2>&1; then
            log_success "Service is ready!"
            return 0
        fi
        echo -n "."
        sleep 2
        ((attempt++))
    done

    echo ""
    log_error "Service did not become ready in time"
    return 1
}

# =============================================================================
# Command Functions
# =============================================================================

cmd_start() {
    log_info "Starting TerraFix local testing environment..."

    cd "${PROJECT_ROOT}"
    local compose_cmd=$(get_docker_compose_cmd)

    # Export environment variables for docker-compose
    export MOCK_LATENCY_MS="${MOCK_LATENCY_MS}"
    export MOCK_FAILURE_RATE="${MOCK_FAILURE_RATE}"
    export LOG_LEVEL="${LOG_LEVEL:-INFO}"

    # Start services
    ${compose_cmd} -f "${COMPOSE_FILE}" up -d localstack redis terrafix-api

    # Wait for services to be ready
    wait_for_service "http://localhost:6379" 30 || true  # Redis doesn't respond to HTTP
    wait_for_service "http://localhost:8081/health" 60

    # Verify Redis is running
    if docker exec terrafix-redis redis-cli ping | grep -q "PONG"; then
        log_success "Redis is ready"
    else
        log_error "Redis is not responding"
        exit 1
    fi

    # Check LocalStack health
    if curl -sf "http://localhost:4566/_localstack/health" > /dev/null 2>&1; then
        log_success "LocalStack is ready"
    else
        log_warning "LocalStack may not be fully ready (optional for load testing)"
    fi

    log_success "Local testing environment is ready!"
    log_info "TerraFix API: http://localhost:8081"
    log_info "Redis: localhost:6379"
    log_info "LocalStack: http://localhost:4566"
}

cmd_stop() {
    log_info "Stopping TerraFix local testing environment..."

    cd "${PROJECT_ROOT}"
    local compose_cmd=$(get_docker_compose_cmd)

    ${compose_cmd} -f "${COMPOSE_FILE}" down

    log_success "Environment stopped"
}

cmd_status() {
    log_info "Checking service status..."

    cd "${PROJECT_ROOT}"
    local compose_cmd=$(get_docker_compose_cmd)

    ${compose_cmd} -f "${COMPOSE_FILE}" ps

    echo ""
    log_info "Health checks:"

    # TerraFix API
    if curl -sf "http://localhost:8081/health" > /dev/null 2>&1; then
        echo -e "  TerraFix API: ${GREEN}healthy${NC}"
    else
        echo -e "  TerraFix API: ${RED}not responding${NC}"
    fi

    # Redis
    if docker exec terrafix-redis redis-cli ping 2>/dev/null | grep -q "PONG"; then
        echo -e "  Redis: ${GREEN}healthy${NC}"
    else
        echo -e "  Redis: ${RED}not responding${NC}"
    fi

    # LocalStack
    if curl -sf "http://localhost:4566/_localstack/health" > /dev/null 2>&1; then
        echo -e "  LocalStack: ${GREEN}healthy${NC}"
    else
        echo -e "  LocalStack: ${YELLOW}not responding${NC}"
    fi
}

cmd_logs() {
    log_info "Tailing logs from all services..."

    cd "${PROJECT_ROOT}"
    local compose_cmd=$(get_docker_compose_cmd)

    ${compose_cmd} -f "${COMPOSE_FILE}" logs -f
}

cmd_test() {
    log_info "Running load tests..."

    cd "${PROJECT_ROOT}"

    # Ensure output directory exists
    mkdir -p "${OUTPUT_DIR}"

    # Check if API server is running
    if ! curl -sf "http://localhost:8081/health" > /dev/null 2>&1; then
        log_error "TerraFix API server is not running. Start it with: $0 start"
        exit 1
    fi

    # Build locust command
    local locust_args=()

    if [ "$LOCUST_UI" = true ]; then
        log_info "Starting Locust with web UI at http://localhost:8089"
        locust_args+=(
            "-f" "${PROJECT_ROOT}/src/terrafix/experiments/locustfile.py"
            "--host" "${HOST}"
        )
    else
        locust_args+=(
            "-f" "${PROJECT_ROOT}/src/terrafix/experiments/locustfile.py"
            "--host" "${HOST}"
            "--headless"
            "--csv" "${OUTPUT_DIR}/${EXPERIMENT}"
            "--html" "${OUTPUT_DIR}/${EXPERIMENT}_report.html"
        )

        if [ -n "$USERS" ]; then
            locust_args+=("--users" "$USERS")
        else
            locust_args+=("--users" "10")
        fi

        if [ -n "$DURATION" ]; then
            locust_args+=("--run-time" "$DURATION")
        else
            locust_args+=("--run-time" "3m")
        fi

        locust_args+=("--spawn-rate" "2")
    fi

    # Set experiment type
    export TERRAFIX_EXPERIMENT="${EXPERIMENT}"

    # Run locust
    log_info "Executing: locust ${locust_args[*]}"
    locust "${locust_args[@]}"

    if [ "$LOCUST_UI" = false ]; then
        log_success "Load test completed!"
        log_info "Results saved to: ${OUTPUT_DIR}"
    fi
}

cmd_all() {
    log_info "Running complete load testing suite..."

    # Start environment
    cmd_start

    # Wait a bit for services to stabilize
    sleep 5

    cd "${PROJECT_ROOT}"
    mkdir -p "${OUTPUT_DIR}"

    # Run the full experiment suite
    log_info "Starting automated experiment runner..."

    export TERRAFIX_EXPERIMENT="${EXPERIMENT}"
    export MOCK_LATENCY_MS="${MOCK_LATENCY_MS}"

    python -m terrafix.experiments.run_experiments \
        --host "${HOST}" \
        --output "${OUTPUT_DIR}" \
        --experiment "${EXPERIMENT}"

    log_success "All experiments completed!"
    log_info "Results saved to: ${OUTPUT_DIR}"
    log_info ""
    log_info "View results:"
    log_info "  - Summary: ${OUTPUT_DIR}/experiment_summary.html"
    log_info "  - Charts: ${OUTPUT_DIR}/charts/"
}

cmd_clean() {
    log_info "Cleaning up all data and volumes..."

    cd "${PROJECT_ROOT}"
    local compose_cmd=$(get_docker_compose_cmd)

    # Stop all services
    ${compose_cmd} -f "${COMPOSE_FILE}" down -v --remove-orphans

    # Remove named volumes
    docker volume rm terrafix-localstack-data 2>/dev/null || true
    docker volume rm terrafix-redis-data 2>/dev/null || true

    # Remove experiment results
    if [ -d "${OUTPUT_DIR}" ]; then
        rm -rf "${OUTPUT_DIR}"
    fi

    log_success "Cleanup complete"
}

show_help() {
    head -n 50 "$0" | tail -n 48 | grep "^#" | sed 's/^# //'
}

# =============================================================================
# Argument Parsing
# =============================================================================

parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --experiment)
                EXPERIMENT="$2"
                shift 2
                ;;
            --host)
                HOST="$2"
                shift 2
                ;;
            --output)
                OUTPUT_DIR="$2"
                shift 2
                ;;
            --users)
                USERS="$2"
                shift 2
                ;;
            --duration)
                DURATION="$2"
                shift 2
                ;;
            --latency)
                MOCK_LATENCY_MS="$2"
                shift 2
                ;;
            --failure-rate)
                MOCK_FAILURE_RATE="$2"
                shift 2
                ;;
            --locust-ui)
                LOCUST_UI=true
                shift
                ;;
            --help|-h)
                show_help
                exit 0
                ;;
            *)
                # Unknown option or command
                break
                ;;
        esac
    done
}

# =============================================================================
# Main Entry Point
# =============================================================================

main() {
    check_dependencies

    local command="${1:-help}"
    shift || true

    parse_args "$@"

    case $command in
        start)
            cmd_start
            ;;
        stop)
            cmd_stop
            ;;
        status)
            cmd_status
            ;;
        logs)
            cmd_logs
            ;;
        test)
            cmd_test
            ;;
        all)
            cmd_all
            ;;
        clean)
            cmd_clean
            ;;
        help|--help|-h)
            show_help
            ;;
        *)
            log_error "Unknown command: $command"
            echo ""
            show_help
            exit 1
            ;;
    esac
}

main "$@"

