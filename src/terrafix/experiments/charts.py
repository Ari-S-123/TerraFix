"""
Chart and graph generation for TerraFix experiment results.

This module provides visualization capabilities for load testing results,
generating charts for:
- Latency distributions (histograms, percentile plots)
- Throughput over time
- Success/failure rates
- Comparison across experiments
- Resource utilization (if available)

The charts can be exported as PNG images or displayed interactively.

Usage:
    from terrafix.experiments.charts import ExperimentChartGenerator

    generator = ExperimentChartGenerator(results)
    generator.generate_all("output/charts")

    # Or generate specific charts
    generator.plot_latency_distribution()
    generator.plot_throughput_timeline()
    generator.save_all("output/charts")

Requirements:
    - matplotlib>=3.7.0
    - numpy (for percentile calculations)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

# Import matplotlib with non-interactive backend for server-side rendering
import matplotlib

matplotlib.use("Agg")  # Must be before pyplot import

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.axes import Axes  # noqa: F401
from matplotlib.figure import Figure


@dataclass
class ChartConfig:
    """
    Configuration for chart generation.

    Attributes:
        figure_size: Default figure size in inches (width, height)
        dpi: Resolution for saved images
        style: Matplotlib style to use
        color_palette: List of colors for chart elements
        font_size: Base font size
        title_font_size: Font size for titles
        save_format: Image format for saved charts
    """

    figure_size: tuple[float, float] = (12, 8)
    dpi: int = 150
    style: str = "seaborn-v0_8-darkgrid"
    color_palette: list[str] = field(
        default_factory=lambda: [
            "#2ecc71",  # Green (success)
            "#e74c3c",  # Red (failure)
            "#3498db",  # Blue (primary)
            "#9b59b6",  # Purple (secondary)
            "#f39c12",  # Orange (warning)
            "#1abc9c",  # Teal (info)
        ]
    )
    font_size: int = 12
    title_font_size: int = 16
    save_format: str = "png"


@dataclass
class ExperimentData:
    """
    Structured experiment data for chart generation.

    Attributes:
        experiment_type: Type of experiment
        profile: Workload profile used
        timestamps: Time series data points
        latencies_ms: List of latency measurements
        throughput_series: Throughput over time
        success_count: Number of successful requests
        failure_count: Number of failed requests
        metadata: Additional experiment metadata
    """

    experiment_type: str
    profile: str
    timestamps: list[datetime] = field(default_factory=list)
    latencies_ms: list[float] = field(default_factory=list)
    throughput_series: list[tuple[datetime, float]] = field(default_factory=list)
    success_count: int = 0
    failure_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> ExperimentData:
        """
        Create ExperimentData from JSON data.

        Args:
            data: Dictionary from JSON file

        Returns:
            ExperimentData instance
        """
        return cls(
            experiment_type=data.get("experiment_type", "unknown"),
            profile=data.get("profile", "unknown"),
            latencies_ms=data.get("latencies_ms", []),
            success_count=data.get("counts", {}).get("processed", 0),
            failure_count=data.get("counts", {}).get("failed", 0),
            metadata=data.get("metadata", {}),
        )

    @classmethod
    def from_locust_csv(cls, stats_file: Path, history_file: Path | None = None) -> ExperimentData:
        """
        Create ExperimentData from Locust CSV output.

        Args:
            stats_file: Path to Locust stats CSV
            history_file: Optional path to stats history CSV

        Returns:
            ExperimentData instance
        """
        import csv

        latencies: list[float] = []
        success_count = 0
        failure_count = 0

        # Parse main stats file
        with stats_file.open() as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("Name") == "Aggregated":
                    success_count = int(row.get("Request Count", 0))
                    failure_count = int(row.get("Failure Count", 0))

                    # Extract percentiles
                    for pct in ["50%", "66%", "75%", "80%", "90%", "95%", "98%", "99%"]:
                        if pct in row:
                            latencies.append(float(row[pct]))

        # Parse history file for time series if available
        throughput_series: list[tuple[datetime, float]] = []
        if history_file and history_file.exists():
            with history_file.open() as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get("Name") == "Aggregated":
                        ts = datetime.fromtimestamp(float(row.get("Timestamp", 0)))
                        rps = float(row.get("Requests/s", 0))
                        throughput_series.append((ts, rps))

        return cls(
            experiment_type="locust",
            profile="load_test",
            latencies_ms=latencies,
            throughput_series=throughput_series,
            success_count=success_count,
            failure_count=failure_count,
        )


class ExperimentChartGenerator:
    """
    Generator for experiment visualization charts.

    Creates various charts from experiment results including
    latency distributions, throughput graphs, and comparison charts.

    Attributes:
        data: Experiment data to visualize
        config: Chart configuration
        figures: Generated figure objects
    """

    def __init__(
        self,
        data: ExperimentData | list[ExperimentData],
        config: ChartConfig | None = None,
    ) -> None:
        """
        Initialize chart generator.

        Args:
            data: Single experiment or list of experiments
            config: Optional chart configuration
        """
        self.data_list = [data] if isinstance(data, ExperimentData) else data
        self.config = config or ChartConfig()
        self.figures: dict[str, Figure] = {}

        # Apply matplotlib style
        try:
            plt.style.use(self.config.style)
        except OSError:
            plt.style.use("seaborn-v0_8")

    def plot_latency_distribution(self) -> Figure:
        """
        Create latency distribution histogram.

        Returns:
            Matplotlib Figure with latency histogram
        """
        fig, ax = plt.subplots(figsize=self.config.figure_size, dpi=self.config.dpi)

        for i, data in enumerate(self.data_list):
            if data.latencies_ms:
                color = self.config.color_palette[i % len(self.config.color_palette)]
                ax.hist(
                    data.latencies_ms,
                    bins=50,
                    alpha=0.7,
                    color=color,
                    label=f"{data.experiment_type} - {data.profile}",
                    edgecolor="black",
                    linewidth=0.5,
                )

        ax.set_xlabel("Latency (ms)", fontsize=self.config.font_size)
        ax.set_ylabel("Frequency", fontsize=self.config.font_size)
        ax.set_title("Response Latency Distribution", fontsize=self.config.title_font_size)
        ax.legend()
        ax.grid(True, alpha=0.3)

        fig.tight_layout()
        self.figures["latency_distribution"] = fig
        return fig

    def plot_latency_percentiles(self) -> Figure:
        """
        Create latency percentile chart (P50, P95, P99).

        Returns:
            Matplotlib Figure with percentile bars
        """
        fig, ax = plt.subplots(figsize=self.config.figure_size, dpi=self.config.dpi)

        percentiles = [50, 75, 90, 95, 99]
        x_positions = range(len(percentiles))
        width = 0.8 / len(self.data_list)

        for i, data in enumerate(self.data_list):
            if data.latencies_ms:
                sorted_latencies = sorted(data.latencies_ms)
                n = len(sorted_latencies)

                pct_values = []
                for p in percentiles:
                    idx = min(int(n * p / 100), n - 1)
                    pct_values.append(sorted_latencies[idx])

                color = self.config.color_palette[i % len(self.config.color_palette)]
                offset = (i - len(self.data_list) / 2) * width
                ax.bar(
                    [x + offset for x in x_positions],
                    pct_values,
                    width=width,
                    color=color,
                    label=f"{data.experiment_type} - {data.profile}",
                    alpha=0.8,
                )

        ax.set_xticks(x_positions)
        ax.set_xticklabels([f"P{p}" for p in percentiles])
        ax.set_xlabel("Percentile", fontsize=self.config.font_size)
        ax.set_ylabel("Latency (ms)", fontsize=self.config.font_size)
        ax.set_title("Latency Percentiles", fontsize=self.config.title_font_size)
        ax.legend()
        ax.grid(True, alpha=0.3, axis="y")

        fig.tight_layout()
        self.figures["latency_percentiles"] = fig
        return fig

    def plot_throughput_timeline(self) -> Figure:
        """
        Create throughput over time line chart.

        Returns:
            Matplotlib Figure with throughput timeline
        """
        fig, ax = plt.subplots(figsize=self.config.figure_size, dpi=self.config.dpi)

        for i, data in enumerate(self.data_list):
            if data.throughput_series:
                times = [t[0] for t in data.throughput_series]
                values = [t[1] for t in data.throughput_series]

                color = self.config.color_palette[i % len(self.config.color_palette)]
                ax.plot(
                    times,  # type: ignore[arg-type]
                    values,
                    color=color,
                    linewidth=2,
                    label=f"{data.experiment_type} - {data.profile}",
                    marker="o",
                    markersize=3,
                )

        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))  # type: ignore[no-untyped-call]
        ax.xaxis.set_major_locator(mdates.AutoDateLocator())  # type: ignore[no-untyped-call]
        fig.autofmt_xdate()

        ax.set_xlabel("Time", fontsize=self.config.font_size)
        ax.set_ylabel("Requests/second", fontsize=self.config.font_size)
        ax.set_title("Throughput Over Time", fontsize=self.config.title_font_size)
        ax.legend()
        ax.grid(True, alpha=0.3)

        fig.tight_layout()
        self.figures["throughput_timeline"] = fig
        return fig

    def plot_success_failure_pie(self) -> Figure:
        """
        Create success/failure pie chart.

        Returns:
            Matplotlib Figure with pie chart
        """
        fig, axes = plt.subplots(
            1,
            len(self.data_list),
            figsize=(self.config.figure_size[0], self.config.figure_size[1] / 2),
            dpi=self.config.dpi,
        )

        if len(self.data_list) == 1:
            axes = [axes]

        for _i, (ax, data) in enumerate(zip(axes, self.data_list, strict=False)):
            total = data.success_count + data.failure_count
            if total > 0:
                sizes = [data.success_count, data.failure_count]
                labels = [
                    f"Success\n({data.success_count})",
                    f"Failed\n({data.failure_count})",
                ]
                colors = [self.config.color_palette[0], self.config.color_palette[1]]
                explode = (0.02, 0.02)

                ax.pie(
                    sizes,
                    explode=explode,
                    labels=labels,
                    colors=colors,
                    autopct="%1.1f%%",
                    shadow=False,
                    startangle=90,
                )
                ax.set_title(
                    f"{data.experiment_type}\n{data.profile}",
                    fontsize=self.config.font_size,
                )
            else:
                ax.text(0.5, 0.5, "No data", ha="center", va="center")
                ax.set_title(f"{data.experiment_type}", fontsize=self.config.font_size)

        fig.suptitle("Success/Failure Distribution", fontsize=self.config.title_font_size)
        fig.tight_layout()
        self.figures["success_failure"] = fig
        return fig

    def plot_comparison_bar(self) -> Figure:
        """
        Create comparison bar chart across experiments.

        Returns:
            Matplotlib Figure with comparison bars
        """
        if len(self.data_list) < 2:
            return self.plot_latency_percentiles()

        fig, axes = plt.subplots(1, 2, figsize=self.config.figure_size, dpi=self.config.dpi)

        # Success rate comparison
        ax1 = axes[0]
        names = [f"{d.experiment_type}\n{d.profile}" for d in self.data_list]
        success_rates = []
        for d in self.data_list:
            total = d.success_count + d.failure_count
            rate = d.success_count / total * 100 if total > 0 else 0
            success_rates.append(rate)

        colors = [
            self.config.color_palette[i % len(self.config.color_palette)]
            for i in range(len(self.data_list))
        ]
        bars = ax1.bar(names, success_rates, color=colors, alpha=0.8)

        ax1.set_ylim(0, 105)
        ax1.set_ylabel("Success Rate (%)", fontsize=self.config.font_size)
        ax1.set_title("Success Rate Comparison", fontsize=self.config.title_font_size)
        ax1.axhline(y=95, color="red", linestyle="--", alpha=0.5, label="95% target")
        ax1.legend()

        # Add value labels on bars
        for bar, rate in zip(bars, success_rates, strict=False):
            ax1.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 1,
                f"{rate:.1f}%",
                ha="center",
                va="bottom",
                fontsize=self.config.font_size - 2,
            )

        # P99 latency comparison
        ax2 = axes[1]
        p99_values = []
        for d in self.data_list:
            if d.latencies_ms:
                sorted_lat = sorted(d.latencies_ms)
                idx = min(int(len(sorted_lat) * 0.99), len(sorted_lat) - 1)
                p99_values.append(sorted_lat[idx])
            else:
                p99_values.append(0)

        bars = ax2.bar(names, p99_values, color=colors, alpha=0.8)
        ax2.set_ylabel("P99 Latency (ms)", fontsize=self.config.font_size)
        ax2.set_title("P99 Latency Comparison", fontsize=self.config.title_font_size)

        # Add value labels on bars
        for bar, val in zip(bars, p99_values, strict=False):
            ax2.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + max(p99_values) * 0.02,
                f"{val:.0f}ms",
                ha="center",
                va="bottom",
                fontsize=self.config.font_size - 2,
            )

        fig.tight_layout()
        self.figures["comparison"] = fig
        return fig

    def plot_latency_heatmap(self) -> Figure:
        """
        Create latency heatmap showing distribution over time buckets.

        Returns:
            Matplotlib Figure with heatmap
        """
        # This requires time-bucketed latency data
        # For now, create a simplified version using synthetic time buckets

        fig, ax = plt.subplots(figsize=self.config.figure_size, dpi=self.config.dpi)

        if self.data_list and self.data_list[0].latencies_ms:
            data = self.data_list[0]
            n_buckets = min(20, len(data.latencies_ms) // 10)

            if n_buckets > 0:
                bucket_size = len(data.latencies_ms) // n_buckets
                heatmap_data = []

                for i in range(n_buckets):
                    start = i * bucket_size
                    end = start + bucket_size
                    bucket_latencies = data.latencies_ms[start:end]

                    # Calculate percentile distribution for this bucket
                    if bucket_latencies:
                        sorted_lat = sorted(bucket_latencies)
                        percentiles = [10, 25, 50, 75, 90, 95, 99]
                        row = []
                        for p in percentiles:
                            idx = min(int(len(sorted_lat) * p / 100), len(sorted_lat) - 1)
                            row.append(sorted_lat[idx])
                        heatmap_data.append(row)

                if heatmap_data:
                    import numpy as np

                    im = ax.imshow(
                        np.array(heatmap_data).T,
                        aspect="auto",
                        cmap="YlOrRd",
                        origin="lower",
                    )

                    ax.set_yticks(range(7))
                    ax.set_yticklabels(["P10", "P25", "P50", "P75", "P90", "P95", "P99"])
                    ax.set_xlabel("Time Bucket", fontsize=self.config.font_size)
                    ax.set_ylabel("Percentile", fontsize=self.config.font_size)
                    ax.set_title(
                        "Latency Distribution Over Time", fontsize=self.config.title_font_size
                    )

                    cbar = fig.colorbar(im, ax=ax)
                    cbar.set_label("Latency (ms)")

        fig.tight_layout()
        self.figures["latency_heatmap"] = fig
        return fig

    def generate_all(self, output_dir: str | Path | None = None) -> dict[str, Figure]:
        """
        Generate all available charts.

        Args:
            output_dir: Optional directory to save charts

        Returns:
            Dictionary of chart name to Figure
        """
        self.plot_latency_distribution()
        self.plot_latency_percentiles()
        self.plot_throughput_timeline()
        self.plot_success_failure_pie()

        if len(self.data_list) > 1:
            self.plot_comparison_bar()

        self.plot_latency_heatmap()

        if output_dir:
            self.save_all(output_dir)

        return self.figures

    def save_all(self, output_dir: str | Path) -> list[Path]:
        """
        Save all generated charts to directory.

        Args:
            output_dir: Directory to save charts

        Returns:
            List of saved file paths
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        saved_files: list[Path] = []

        for name, fig in self.figures.items():
            file_path = output_path / f"{name}.{self.config.save_format}"
            fig.savefig(
                file_path,
                format=self.config.save_format,
                dpi=self.config.dpi,
                bbox_inches="tight",
            )
            saved_files.append(file_path)
            print(f"Saved: {file_path}")

        return saved_files

    def generate_html_report(self, output_path: str | Path) -> Path:
        """
        Generate an HTML report with embedded charts.

        Args:
            output_path: Path for HTML file

        Returns:
            Path to generated HTML file
        """
        import base64
        from io import BytesIO

        output_path = Path(output_path)

        # Generate all charts
        self.generate_all()

        # Convert figures to base64 images
        chart_html = []
        for name, fig in self.figures.items():
            buf = BytesIO()
            fig.savefig(buf, format="png", dpi=self.config.dpi, bbox_inches="tight")
            buf.seek(0)
            img_base64 = base64.b64encode(buf.read()).decode("utf-8")
            chart_html.append(
                f'<div class="chart">'
                f"<h3>{name.replace('_', ' ').title()}</h3>"
                f'<img src="data:image/png;base64,{img_base64}" />'
                f"</div>"
            )

        # Generate summary statistics
        stats_html = []
        for data in self.data_list:
            total = data.success_count + data.failure_count
            success_rate = data.success_count / total * 100 if total > 0 else 0

            stats_html.append(f"""
            <div class="stats-card">
                <h3>{data.experiment_type} - {data.profile}</h3>
                <table>
                    <tr><td>Total Requests:</td><td>{total}</td></tr>
                    <tr><td>Successful:</td><td>{data.success_count}</td></tr>
                    <tr><td>Failed:</td><td>{data.failure_count}</td></tr>
                    <tr><td>Success Rate:</td><td>{success_rate:.1f}%</td></tr>
                </table>
            </div>
            """)

        # Build HTML document
        html_content = f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>TerraFix Load Test Report</title>
            <style>
                body {{
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                    margin: 0;
                    padding: 20px;
                    background-color: #f5f5f5;
                    color: #333;
                }}
                .container {{
                    max-width: 1400px;
                    margin: 0 auto;
                }}
                h1 {{
                    color: #2c3e50;
                    border-bottom: 3px solid #3498db;
                    padding-bottom: 10px;
                }}
                h2 {{
                    color: #34495e;
                    margin-top: 30px;
                }}
                .stats-container {{
                    display: flex;
                    flex-wrap: wrap;
                    gap: 20px;
                    margin-bottom: 30px;
                }}
                .stats-card {{
                    background: white;
                    border-radius: 8px;
                    padding: 20px;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                    flex: 1;
                    min-width: 250px;
                }}
                .stats-card h3 {{
                    margin-top: 0;
                    color: #3498db;
                }}
                .stats-card table {{
                    width: 100%;
                }}
                .stats-card td {{
                    padding: 5px 0;
                }}
                .stats-card td:last-child {{
                    text-align: right;
                    font-weight: bold;
                }}
                .charts-container {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(600px, 1fr));
                    gap: 20px;
                }}
                .chart {{
                    background: white;
                    border-radius: 8px;
                    padding: 20px;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                }}
                .chart h3 {{
                    margin-top: 0;
                    color: #2c3e50;
                }}
                .chart img {{
                    width: 100%;
                    height: auto;
                }}
                .timestamp {{
                    color: #7f8c8d;
                    font-size: 0.9em;
                    margin-bottom: 20px;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>🚀 TerraFix Load Test Report</h1>
                <p class="timestamp">Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>

                <h2>📊 Summary Statistics</h2>
                <div class="stats-container">
                    {"".join(stats_html)}
                </div>

                <h2>📈 Charts</h2>
                <div class="charts-container">
                    {"".join(chart_html)}
                </div>
            </div>
        </body>
        </html>
        """

        output_path.write_text(html_content)
        print(f"Generated HTML report: {output_path}")
        return output_path

    def close(self) -> None:
        """Close all figure resources."""
        for fig in self.figures.values():
            plt.close(fig)
        self.figures.clear()


def load_results_from_json(path: str | Path) -> ExperimentData:
    """
    Load experiment results from JSON file.

    Args:
        path: Path to JSON results file

    Returns:
        ExperimentData instance
    """
    path = Path(path)
    with path.open() as f:
        data = json.load(f)
    return ExperimentData.from_json(data)


def load_results_from_locust_csv(
    stats_path: str | Path,
    history_path: str | Path | None = None,
) -> ExperimentData:
    """
    Load experiment results from Locust CSV files.

    Args:
        stats_path: Path to Locust stats CSV
        history_path: Optional path to stats history CSV

    Returns:
        ExperimentData instance
    """
    return ExperimentData.from_locust_csv(
        Path(stats_path),
        Path(history_path) if history_path else None,
    )


def generate_report_from_files(
    result_files: list[str | Path],
    output_dir: str | Path,
    html: bool = True,
) -> None:
    """
    Generate charts and report from result files.

    Args:
        result_files: List of JSON or CSV result files
        output_dir: Directory for output
        html: Whether to generate HTML report
    """
    data_list: list[ExperimentData] = []

    for file_path in result_files:
        path = Path(file_path)
        if path.suffix == ".json":
            data_list.append(load_results_from_json(path))
        elif path.suffix == ".csv":
            data_list.append(load_results_from_locust_csv(path))
        else:
            print(f"Unknown file format: {path}")

    if not data_list:
        print("No valid result files found")
        return

    generator = ExperimentChartGenerator(data_list)

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Generate and save charts
    generator.generate_all(output_path)

    # Generate HTML report
    if html:
        generator.generate_html_report(output_path / "report.html")

    generator.close()
