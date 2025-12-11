"""
Command-line interface for TerraFix experiment harness.

This module provides CLI commands for running experiments and
generating reports from the command line.

Usage:
    # Run a throughput experiment
    python -m terrafix.experiments run --type throughput --profile steady_state

    # Run with custom duration
    python -m terrafix.experiments run --type throughput --duration 600

    # Run resilience test with failure injection
    python -m terrafix.experiments run --type resilience --failure-rate 0.2

    # Generate report from results
    python -m terrafix.experiments report --input results.json --output report.txt
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from .profiles import PRESETS, ProfileConfig, WorkloadProfile
from .reporter import ExperimentReporter, ExperimentResult
from .runner import ExperimentRunner


def setup_logging(verbose: bool = False) -> None:
    """Configure logging for CLI."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="TerraFix Experiment Harness",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Run a quick throughput test:
    %(prog)s run --type throughput --preset quick_test

  Run a stress test:
    %(prog)s run --type throughput --preset stress_test

  Run resilience test with 20%% failure rate:
    %(prog)s run --type resilience --failure-rate 0.2

  Run scalability test across repo sizes:
    %(prog)s run --type scalability

  Generate report from saved results:
    %(prog)s report --input results.json
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Run command
    run_parser = subparsers.add_parser("run", help="Run an experiment")
    run_parser.add_argument(
        "--type",
        "-t",
        choices=["throughput", "resilience", "scalability"],
        default="throughput",
        help="Type of experiment to run (default: throughput)",
    )
    run_parser.add_argument(
        "--profile",
        "-p",
        choices=["steady_state", "burst", "cascade"],
        default="steady_state",
        help="Workload profile (default: steady_state)",
    )
    run_parser.add_argument(
        "--preset",
        choices=list(PRESETS.keys()),
        help="Use a preset configuration",
    )
    run_parser.add_argument(
        "--duration",
        "-d",
        type=int,
        default=300,
        help="Experiment duration in seconds (default: 300)",
    )
    run_parser.add_argument(
        "--failures-per-interval",
        type=int,
        default=5,
        help="Failures to generate per interval (default: 5)",
    )
    run_parser.add_argument(
        "--interval",
        type=int,
        default=10,
        help="Interval between failure batches in seconds (default: 10)",
    )
    run_parser.add_argument(
        "--failure-rate",
        type=float,
        default=0.0,
        help="Failure injection rate for resilience tests (default: 0.0)",
    )
    run_parser.add_argument(
        "--output",
        "-o",
        type=Path,
        help="Output file for results (JSON)",
    )
    run_parser.add_argument(
        "--seed",
        type=int,
        help="Random seed for reproducibility",
    )
    run_parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    # Report command
    report_parser = subparsers.add_parser("report", help="Generate report from results")
    report_parser.add_argument(
        "--input",
        "-i",
        type=Path,
        required=True,
        help="Input JSON results file",
    )
    report_parser.add_argument(
        "--output",
        "-o",
        type=Path,
        help="Output file (default: stdout)",
    )
    report_parser.add_argument(
        "--format",
        "-f",
        choices=["text", "json", "csv"],
        default="text",
        help="Output format (default: text)",
    )

    # List presets command
    subparsers.add_parser("list-presets", help="List available presets")

    return parser.parse_args()


async def run_experiment(args: argparse.Namespace) -> ExperimentResult | list[ExperimentResult]:
    """
    Run the specified experiment.

    Args:
        args: Parsed command line arguments

    Returns:
        Experiment result(s)
    """
    # Build configuration
    if args.preset:
        config = PRESETS[args.preset]
    else:
        config = ProfileConfig(
            profile=WorkloadProfile(args.profile),
            duration_seconds=args.duration,
            failures_per_interval=args.failures_per_interval,
            interval_seconds=args.interval,
        )

    # Create runner
    runner = ExperimentRunner(
        seed=args.seed,
        failure_rate=args.failure_rate,
    )

    # Run appropriate experiment type
    if args.type == "throughput":
        return await runner.run_throughput_experiment(config)
    elif args.type == "resilience":
        return await runner.run_resilience_experiment(
            config,
            failure_rate=args.failure_rate or 0.2,
        )
    elif args.type == "scalability":
        return await runner.run_scalability_experiment(base_config=config)

    raise ValueError(f"Unknown experiment type: {args.type}")


def generate_report(args: argparse.Namespace) -> None:
    """
    Generate a report from saved results.

    Args:
        args: Parsed command line arguments
    """
    # Load results
    with args.input.open() as f:
        data = json.load(f)

    # Reconstruct ExperimentResult
    result = ExperimentResult(
        experiment_type=data.get("experiment_type", "unknown"),
        profile=data.get("profile", "unknown"),
        duration_seconds=data.get("duration", {}).get("configured_seconds", 0),
    )
    result.total_generated = data.get("counts", {}).get("generated", 0)
    result.total_processed = data.get("counts", {}).get("processed", 0)
    result.total_skipped = data.get("counts", {}).get("skipped", 0)
    result.total_failed = data.get("counts", {}).get("failed", 0)

    reporter = ExperimentReporter(result)

    # Generate output
    if args.format == "text":
        output = reporter.generate_summary()
    elif args.format == "json":
        output = json.dumps(reporter.to_dict(), indent=2)
    elif args.format == "csv":
        if args.output:
            reporter.export_csv(args.output)
            print(f"CSV exported to {args.output}")
            return
        else:
            print("CSV format requires --output file", file=sys.stderr)
            sys.exit(1)
    else:
        output = reporter.generate_summary()

    # Write output
    if args.output:
        args.output.write_text(output)
        print(f"Report written to {args.output}")
    else:
        print(output)


def list_presets() -> None:
    """List available preset configurations."""
    print("Available Presets:")
    print("-" * 60)
    for name, config in PRESETS.items():
        print(f"\n{name}:")
        print(f"  Profile: {config.profile.value}")
        print(f"  Duration: {config.duration_seconds}s")
        print(f"  Failures/interval: {config.failures_per_interval}")
        print(f"  Interval: {config.interval_seconds}s")


def main() -> None:
    """Main entry point for CLI."""
    args = parse_args()

    if args.command is None:
        print("No command specified. Use --help for usage information.")
        sys.exit(1)

    if args.command == "list-presets":
        list_presets()
        return

    if args.command == "report":
        generate_report(args)
        return

    if args.command == "run":
        setup_logging(getattr(args, "verbose", False))

        # Run experiment
        result = asyncio.run(run_experiment(args))

        # Handle results
        if isinstance(result, list):
            # Multiple results from scalability test
            runner = ExperimentRunner()
            print(runner.generate_comparison_report(result))

            if args.output:
                results_data = [ExperimentReporter(r).to_dict() for r in result]
                with args.output.open("w") as f:
                    json.dump(results_data, f, indent=2)
                print(f"\nResults saved to {args.output}")
        else:
            # Single result
            reporter = ExperimentReporter(result)
            print(reporter.generate_summary())

            if args.output:
                reporter.export_json(args.output)
                print(f"\nResults saved to {args.output}")


if __name__ == "__main__":
    main()
