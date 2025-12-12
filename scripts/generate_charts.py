#!/usr/bin/env python3
"""
Generate missing charts from existing experiment results.

This script reads the experiment stats CSV files and generates visualization
charts using the ExperimentChartGenerator class. It creates:
- Latency distribution charts
- Percentile charts
- Throughput timeline charts
- Success/failure rate charts
- Comparison charts across experiments
- HTML report with embedded charts
"""

import json
from pathlib import Path
from typing import Any

# Ensure we can import from src
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from terrafix.experiments.charts import (
    ExperimentChartGenerator,
    ExperimentData,
)


def load_experiment_data_from_json(json_path: Path) -> list[ExperimentData]:
    """
    Load experiment data from the summary JSON file.

    Args:
        json_path: Path to experiment_summary.json

    Returns:
        List of ExperimentData objects for chart generation.
    """
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    data_list: list[ExperimentData] = []
    all_results: dict[str, list[dict[str, Any]]] = data.get("experiments", {})

    for suite_name, results in all_results.items():
        for result in results:
            if "summary" not in result:
                continue

            summary = result["summary"]
            name = result.get("name", "unknown")

            # Extract percentile latencies from summary
            latencies_ms: list[float] = []

            median = summary.get("median_response_ms")
            if median is not None:
                latencies_ms.append(float(median))

            # Add p95 and p99 as approximations for distribution
            p95 = summary.get("p95_response_ms")
            if p95 is not None:
                latencies_ms.append(float(p95))

            p99 = summary.get("p99_response_ms")
            if p99 is not None:
                latencies_ms.append(float(p99))

            # Create ExperimentData
            experiment_data = ExperimentData(
                experiment_type=suite_name,
                profile=name,
                latencies_ms=latencies_ms,
                success_count=summary.get("total_requests", 0) - summary.get("failure_count", 0),
                failure_count=summary.get("failure_count", 0),
                metadata={
                    "requests_per_sec": summary.get("requests_per_sec", 0),
                    "avg_response_ms": summary.get("avg_response_ms", 0),
                    "duration_seconds": result.get("duration_seconds", 0),
                    "config": result.get("config", {}),
                },
            )
            data_list.append(experiment_data)

    return data_list


def load_data_from_csv_files(results_dir: Path) -> list[ExperimentData]:
    """
    Load experiment data directly from CSV files for richer time-series data.

    Args:
        results_dir: Path to experiment_results directory

    Returns:
        List of ExperimentData objects.
    """
    data_list: list[ExperimentData] = []

    # Iterate through subdirectories
    for suite_dir in ["throughput", "resilience", "scalability"]:
        suite_path = results_dir / suite_dir
        if not suite_path.exists():
            continue

        # Find all stats files
        stats_files = list(suite_path.glob("*_stats.csv"))
        for stats_file in stats_files:
            # Get corresponding history file
            history_file = stats_file.with_name(
                stats_file.name.replace("_stats.csv", "_stats_history.csv")
            )

            # Extract experiment name from filename
            name = stats_file.stem.replace("_stats", "")

            try:
                exp_data = ExperimentData.from_locust_csv(
                    stats_file,
                    history_file if history_file.exists() else None,
                )
                # Override the generic profile with actual name
                exp_data.experiment_type = suite_dir
                exp_data.profile = name
                data_list.append(exp_data)
                print(f"Loaded: {name}")
            except Exception as e:
                print(f"Error loading {stats_file}: {e}")

    return data_list


def generate_charts(results_dir: Path, output_dir: Path) -> None:
    """
    Generate all charts from experiment results.

    Args:
        results_dir: Path to experiment_results directory
        output_dir: Path to save generated charts
    """
    print("Loading experiment data from CSV files...")
    data_list = load_data_from_csv_files(results_dir)

    if not data_list:
        print("No data loaded from CSV files, trying JSON...")
        json_path = results_dir / "experiment_summary.json"
        if json_path.exists():
            data_list = load_experiment_data_from_json(json_path)

    if not data_list:
        print("ERROR: No experiment data found!")
        return

    print(f"\nLoaded {len(data_list)} experiments")

    # Create output directory
    charts_dir = output_dir / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)

    print(f"\nGenerating charts in: {charts_dir}")

    # Create chart generator
    generator = ExperimentChartGenerator(data_list)

    # Generate all charts
    try:
        generator.generate_all(charts_dir)
        print("\nCharts generated successfully!")

        # Generate HTML report
        report_path = output_dir / "charts_report.html"
        generator.generate_html_report(report_path)
        print(f"HTML report generated: {report_path}")

    except Exception as e:
        print(f"Error generating charts: {e}")
        import traceback
        traceback.print_exc()
    finally:
        generator.close()

    # List generated files
    print("\nGenerated files:")
    for f in sorted(charts_dir.iterdir()):
        print(f"  - {f.name}")
    if (output_dir / "charts_report.html").exists():
        print(f"  - charts_report.html")


if __name__ == "__main__":
    # Default paths
    project_root = Path(__file__).parent.parent
    results_dir = project_root / "experiment_results"
    output_dir = results_dir

    if not results_dir.exists():
        print(f"Error: Results directory not found: {results_dir}")
        sys.exit(1)

    generate_charts(results_dir, output_dir)

