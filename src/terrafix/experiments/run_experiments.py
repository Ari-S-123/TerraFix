#!/usr/bin/env python3
"""
TerraFix Load Testing Experiment Runner.

This script orchestrates running the three load testing experiments defined
in the project specification:

1. Pipeline Throughput and Bottleneck Identification
   - Ramps from 1 failure/30s to 10 concurrent failures
   - Collects P50/P95/P99 latency at each stage
   - Identifies compute, I/O, or API bottlenecks

2. Concurrency and Failure Resilience
   - Tests steady-state, burst, and cascade patterns
   - Injects failures (Bedrock throttling, GitHub rate limits)
   - Measures retry success rates and recovery time

3. Repository Analysis Scalability
   - Tests small (5-15 resources), medium (50-100), large (300+)
   - Measures parsing time vs complexity
   - Tracks memory consumption patterns

Usage:
    # Run all experiments
    python -m terrafix.experiments.run_experiments

    # Run specific experiment
    python -m terrafix.experiments.run_experiments --experiment throughput

    # Custom target
    python -m terrafix.experiments.run_experiments --host http://deployed-service.amazonaws.com

    # Dry run (show what would be executed)
    python -m terrafix.experiments.run_experiments --dry-run

Environment Variables:
    TERRAFIX_API_HOST: Target service URL
    TERRAFIX_OUTPUT_DIR: Results output directory
    TERRAFIX_MOCK_MODE: Run API server in mock mode locally
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class ExperimentConfig:
    """
    Configuration for a load testing experiment.

    Attributes:
        name: Experiment name
        description: Human-readable description
        locust_class: Locust user class environment variable
        users: Number of concurrent users
        spawn_rate: Users spawned per second
        run_time: Test duration (e.g., "5m", "1h")
        extra_env: Additional environment variables
    """

    name: str
    description: str
    locust_class: str
    users: int
    spawn_rate: float
    run_time: str
    extra_env: dict[str, str] = field(default_factory=dict)


# Experiment configurations based on the spec
EXPERIMENTS: dict[str, list[ExperimentConfig]] = {
    "throughput": [
        # Ramp up test - start low
        ExperimentConfig(
            name="throughput_baseline",
            description="Baseline throughput with 5 users",
            locust_class="throughput",
            users=5,
            spawn_rate=1,
            run_time="3m",
        ),
        # Medium load
        ExperimentConfig(
            name="throughput_medium",
            description="Medium throughput with 20 users",
            locust_class="throughput",
            users=20,
            spawn_rate=2,
            run_time="5m",
        ),
        # High load
        ExperimentConfig(
            name="throughput_high",
            description="High throughput with 50 users",
            locust_class="throughput",
            users=50,
            spawn_rate=5,
            run_time="5m",
        ),
        # Maximum load
        ExperimentConfig(
            name="throughput_max",
            description="Maximum throughput with 100 users",
            locust_class="throughput",
            users=100,
            spawn_rate=10,
            run_time="5m",
        ),
    ],
    "resilience": [
        # Steady-state workload
        ExperimentConfig(
            name="resilience_steady",
            description="Steady-state workload with deduplication testing",
            locust_class="resilience",
            users=10,
            spawn_rate=2,
            run_time="5m",
        ),
        # Burst workload
        ExperimentConfig(
            name="resilience_burst",
            description="Burst workload - high spikes",
            locust_class="burst",
            users=30,
            spawn_rate=10,
            run_time="5m",
        ),
        # Cascade workload
        ExperimentConfig(
            name="resilience_cascade",
            description="Cascade workload - exponentially increasing",
            locust_class="cascade",
            users=50,
            spawn_rate=5,
            run_time="10m",
        ),
        # Mixed with failure injection
        ExperimentConfig(
            name="resilience_failures",
            description="Mixed workload with simulated failures",
            locust_class="mixed",
            users=20,
            spawn_rate=4,
            run_time="5m",
            extra_env={"TERRAFIX_MOCK_FAILURE_RATE": "0.1"},  # 10% failures
        ),
    ],
    "scalability": [
        # Small repositories
        ExperimentConfig(
            name="scalability_small",
            description="Small repos (5-15 resources)",
            locust_class="scalability",
            users=10,
            spawn_rate=2,
            run_time="3m",
            extra_env={"TERRAFIX_REPO_SIZE": "small"},
        ),
        # Medium repositories
        ExperimentConfig(
            name="scalability_medium",
            description="Medium repos (50-100 resources)",
            locust_class="scalability",
            users=10,
            spawn_rate=2,
            run_time="3m",
            extra_env={"TERRAFIX_REPO_SIZE": "medium"},
        ),
        # Large repositories
        ExperimentConfig(
            name="scalability_large",
            description="Large repos (300+ resources)",
            locust_class="scalability",
            users=10,
            spawn_rate=2,
            run_time="3m",
            extra_env={"TERRAFIX_REPO_SIZE": "large"},
        ),
        # Mixed sizes
        ExperimentConfig(
            name="scalability_mixed",
            description="Mixed repository sizes",
            locust_class="scalability",
            users=15,
            spawn_rate=3,
            run_time="5m",
        ),
    ],
}


def get_locustfile_path() -> Path:
    """
    Get the path to the locustfile.

    Returns:
        Path to locustfile.py
    """
    # Try relative to this script
    script_dir = Path(__file__).parent
    locustfile = script_dir / "locustfile.py"

    if locustfile.exists():
        return locustfile

    # Try from cwd
    cwd_locustfile = Path.cwd() / "src" / "terrafix" / "experiments" / "locustfile.py"
    if cwd_locustfile.exists():
        return cwd_locustfile

    raise FileNotFoundError("Could not find locustfile.py")


def start_mock_server(port: int = 8081) -> subprocess.Popen[bytes]:
    """
    Start the mock API server for local testing.

    Args:
        port: Port for the API server

    Returns:
        Subprocess handle for the server
    """
    env = os.environ.copy()
    env["TERRAFIX_MOCK_MODE"] = "true"
    env["TERRAFIX_API_PORT"] = str(port)
    env["TERRAFIX_MOCK_LATENCY_MS"] = "50"

    print(f"Starting mock API server on port {port}...")

    process = subprocess.Popen(
        [sys.executable, "-m", "terrafix.api_server"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Wait for server to start
    time.sleep(2)

    if process.poll() is not None:
        stderr = process.stderr.read() if process.stderr else b""
        raise RuntimeError(f"Failed to start mock server: {stderr.decode()}")

    print("Mock server started successfully")
    return process


def stop_mock_server(process: subprocess.Popen[bytes]) -> None:
    """
    Stop the mock API server.

    Args:
        process: Server process handle
    """
    print("Stopping mock API server...")
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
    print("Mock server stopped")


def run_locust_experiment(
    config: ExperimentConfig,
    host: str,
    output_dir: Path,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Run a single locust experiment.

    Args:
        config: Experiment configuration
        host: Target host URL
        output_dir: Directory for results
        dry_run: If True, only show command without executing

    Returns:
        Dictionary with experiment results
    """
    locustfile = get_locustfile_path()
    csv_prefix = output_dir / config.name

    # Build environment
    env = os.environ.copy()
    env["TERRAFIX_EXPERIMENT"] = config.locust_class
    env.update(config.extra_env)

    # Build locust command
    cmd = [
        "locust",
        "-f", str(locustfile),
        "--host", host,
        "--headless",
        "--users", str(config.users),
        "--spawn-rate", str(config.spawn_rate),
        "--run-time", config.run_time,
        "--csv", str(csv_prefix),
        "--csv-full-history",
        "--html", str(output_dir / f"{config.name}_report.html"),
    ]

    print(f"\n{'='*60}")
    print(f"Experiment: {config.name}")
    print(f"Description: {config.description}")
    print(f"Users: {config.users}, Spawn Rate: {config.spawn_rate}/s")
    print(f"Duration: {config.run_time}")
    print(f"{'='*60}")

    if dry_run:
        print(f"[DRY RUN] Would execute: {' '.join(cmd)}")
        return {"name": config.name, "status": "dry_run"}

    print(f"Running: {' '.join(cmd)}")
    start_time = time.time()

    try:
        result = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
        )

        duration = time.time() - start_time

        # Check for errors
        if result.returncode != 0:
            print(f"ERROR: Experiment failed with code {result.returncode}")
            print(f"STDERR: {result.stderr}")
            return {
                "name": config.name,
                "status": "failed",
                "error": result.stderr,
                "duration_seconds": duration,
            }

        print(f"Completed in {duration:.1f}s")

        # Load results from CSV
        stats_file = Path(f"{csv_prefix}_stats.csv")
        results: dict[str, Any] = {
            "name": config.name,
            "status": "completed",
            "duration_seconds": duration,
            "config": {
                "users": config.users,
                "spawn_rate": config.spawn_rate,
                "run_time": config.run_time,
            },
        }

        if stats_file.exists():
            results["stats_file"] = str(stats_file)
            # Parse summary from CSV
            import csv
            with stats_file.open() as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get("Name") == "Aggregated":
                        results["summary"] = {
                            "total_requests": int(row.get("Request Count", 0)),
                            "failure_count": int(row.get("Failure Count", 0)),
                            "median_response_ms": float(row.get("Median Response Time", 0)),
                            "avg_response_ms": float(row.get("Average Response Time", 0)),
                            "p95_response_ms": float(row.get("95%", 0)),
                            "p99_response_ms": float(row.get("99%", 0)),
                            "requests_per_sec": float(row.get("Requests/s", 0)),
                        }

        return results

    except FileNotFoundError:
        print("ERROR: locust command not found. Install with: pip install locust")
        return {
            "name": config.name,
            "status": "error",
            "error": "locust not found",
        }
    except Exception as e:
        print(f"ERROR: {e}")
        return {
            "name": config.name,
            "status": "error",
            "error": str(e),
        }


def run_experiment_suite(
    experiment_type: str,
    host: str,
    output_dir: Path,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """
    Run a complete experiment suite.

    Args:
        experiment_type: Type of experiment (throughput, resilience, scalability)
        host: Target host URL
        output_dir: Directory for results
        dry_run: If True, only show commands

    Returns:
        List of experiment results
    """
    if experiment_type not in EXPERIMENTS:
        raise ValueError(f"Unknown experiment type: {experiment_type}")

    configs = EXPERIMENTS[experiment_type]
    results = []

    print(f"\n{'#'*60}")
    print(f"# Running {experiment_type.upper()} experiments")
    print(f"# Target: {host}")
    print(f"# Output: {output_dir}")
    print(f"{'#'*60}")

    # Create output directory
    suite_output = output_dir / experiment_type
    suite_output.mkdir(parents=True, exist_ok=True)

    for config in configs:
        result = run_locust_experiment(config, host, suite_output, dry_run)
        results.append(result)

        # Brief pause between experiments
        if not dry_run:
            print("Waiting 10 seconds before next experiment...")
            time.sleep(10)

    return results


def generate_summary_report(
    all_results: dict[str, list[dict[str, Any]]],
    output_dir: Path,
) -> None:
    """
    Generate a summary report across all experiments.

    Args:
        all_results: Results from all experiment suites
        output_dir: Output directory
    """
    report_path = output_dir / "experiment_summary.json"
    html_path = output_dir / "experiment_summary.html"

    # Save JSON results
    with report_path.open("w") as f:
        json.dump(
            {
                "timestamp": datetime.now().isoformat(),
                "experiments": all_results,
            },
            f,
            indent=2,
        )

    print(f"\nJSON report saved to: {report_path}")

    # Generate HTML summary
    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>TerraFix Experiment Summary</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }}
            h1 {{ color: #2c3e50; }}
            h2 {{ color: #34495e; margin-top: 30px; }}
            .experiment-card {{
                background: white;
                border-radius: 8px;
                padding: 15px;
                margin: 10px 0;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }}
            .success {{ border-left: 4px solid #2ecc71; }}
            .failed {{ border-left: 4px solid #e74c3c; }}
            .summary-table {{
                width: 100%;
                border-collapse: collapse;
                margin: 10px 0;
            }}
            .summary-table th, .summary-table td {{
                padding: 8px 12px;
                text-align: left;
                border-bottom: 1px solid #ddd;
            }}
            .summary-table th {{ background: #3498db; color: white; }}
            .metric {{ font-weight: bold; color: #3498db; }}
        </style>
    </head>
    <body>
        <h1>🧪 TerraFix Experiment Summary</h1>
        <p>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
    """

    for suite_name, results in all_results.items():
        html_content += f"<h2>{suite_name.title()} Experiments</h2>"

        for result in results:
            status_class = "success" if result.get("status") == "completed" else "failed"
            html_content += f"""
            <div class="experiment-card {status_class}">
                <h3>{result.get('name', 'Unknown')}</h3>
                <p>Status: <strong>{result.get('status', 'unknown')}</strong></p>
            """

            if "summary" in result:
                summary = result["summary"]
                html_content += f"""
                <table class="summary-table">
                    <tr>
                        <th>Metric</th>
                        <th>Value</th>
                    </tr>
                    <tr>
                        <td>Total Requests</td>
                        <td class="metric">{summary.get('total_requests', 0):,}</td>
                    </tr>
                    <tr>
                        <td>Failures</td>
                        <td class="metric">{summary.get('failure_count', 0):,}</td>
                    </tr>
                    <tr>
                        <td>Requests/sec</td>
                        <td class="metric">{summary.get('requests_per_sec', 0):.1f}</td>
                    </tr>
                    <tr>
                        <td>Median Response (ms)</td>
                        <td class="metric">{summary.get('median_response_ms', 0):.0f}</td>
                    </tr>
                    <tr>
                        <td>P95 Response (ms)</td>
                        <td class="metric">{summary.get('p95_response_ms', 0):.0f}</td>
                    </tr>
                    <tr>
                        <td>P99 Response (ms)</td>
                        <td class="metric">{summary.get('p99_response_ms', 0):.0f}</td>
                    </tr>
                </table>
                """

            if "error" in result:
                html_content += f"<p style='color: red;'>Error: {result['error']}</p>"

            html_content += "</div>"

    html_content += """
    </body>
    </html>
    """

    html_path.write_text(html_content)
    print(f"HTML report saved to: {html_path}")

    # Generate charts if matplotlib is available
    try:
        from terrafix.experiments.charts import (
            ExperimentChartGenerator,
            ExperimentData,
        )

        print("\nGenerating visualization charts...")

        # Collect data for chart generation
        data_list = []
        for suite_name, results in all_results.items():
            for result in results:
                if "summary" in result:
                    summary = result["summary"]
                    data = ExperimentData(
                        experiment_type=suite_name,
                        profile=result.get("name", "unknown"),
                        success_count=summary.get("total_requests", 0) - summary.get("failure_count", 0),
                        failure_count=summary.get("failure_count", 0),
                        latencies_ms=[
                            summary.get("median_response_ms", 0),
                            summary.get("avg_response_ms", 0),
                            summary.get("p95_response_ms", 0),
                            summary.get("p99_response_ms", 0),
                        ],
                    )
                    data_list.append(data)

        if data_list:
            generator = ExperimentChartGenerator(data_list)
            generator.generate_all(output_dir / "charts")
            generator.generate_html_report(output_dir / "charts_report.html")
            generator.close()
            print(f"Charts saved to: {output_dir / 'charts'}")

    except ImportError as e:
        print(f"Skipping chart generation (matplotlib not available): {e}")


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="TerraFix Load Testing Experiment Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Run all experiments against local mock server:
    %(prog)s --local

  Run throughput experiments against deployed service:
    %(prog)s --experiment throughput --host https://terrafix.example.com

  Dry run to see what would be executed:
    %(prog)s --dry-run

  Run with custom output directory:
    %(prog)s --output ./results
        """,
    )

    parser.add_argument(
        "--experiment",
        "-e",
        choices=["throughput", "resilience", "scalability", "all"],
        default="all",
        help="Experiment type to run (default: all)",
    )

    parser.add_argument(
        "--host",
        "-H",
        default=os.environ.get("TERRAFIX_API_HOST", "http://localhost:8081"),
        help="Target service URL (default: http://localhost:8081)",
    )

    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=Path(os.environ.get("TERRAFIX_OUTPUT_DIR", "./experiment_results")),
        help="Output directory for results (default: ./experiment_results)",
    )

    parser.add_argument(
        "--local",
        "-l",
        action="store_true",
        help="Start local mock server for testing",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show commands without executing",
    )

    parser.add_argument(
        "--no-charts",
        action="store_true",
        help="Skip chart generation",
    )

    return parser.parse_args()


def main() -> int:
    """
    Main entry point.

    Returns:
        Exit code (0 for success, 1 for error)
    """
    args = parse_args()

    print("=" * 60)
    print("TerraFix Load Testing Experiment Runner")
    print("=" * 60)
    print(f"Target: {args.host}")
    print(f"Output: {args.output}")
    print(f"Experiment: {args.experiment}")
    print("=" * 60)

    # Create output directory
    args.output.mkdir(parents=True, exist_ok=True)

    # Start local mock server if requested
    mock_server = None
    if args.local:
        try:
            mock_server = start_mock_server()
        except Exception as e:
            print(f"Failed to start mock server: {e}")
            return 1

    all_results: dict[str, list[dict[str, Any]]] = {}

    try:
        # Determine which experiments to run
        if args.experiment == "all":
            experiment_types = ["throughput", "resilience", "scalability"]
        else:
            experiment_types = [args.experiment]

        # Run experiments
        for exp_type in experiment_types:
            results = run_experiment_suite(
                exp_type,
                args.host,
                args.output,
                args.dry_run,
            )
            all_results[exp_type] = results

        # Generate summary report
        if not args.dry_run:
            generate_summary_report(all_results, args.output)

        print("\n" + "=" * 60)
        print("All experiments completed!")
        print(f"Results saved to: {args.output}")
        print("=" * 60)

        return 0

    except KeyboardInterrupt:
        print("\nExperiments interrupted by user")
        return 1

    except Exception as e:
        print(f"\nError running experiments: {e}")
        return 1

    finally:
        # Stop mock server if we started one
        if mock_server:
            stop_mock_server(mock_server)


if __name__ == "__main__":
    sys.exit(main())

