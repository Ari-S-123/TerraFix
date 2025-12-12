#!/usr/bin/env python3
"""
Regenerate HTML summary from existing JSON experiment results.

This script reads the experiment_summary.json file and regenerates the HTML
summary report, fixing any encoding issues that may have occurred during
the original generation on Windows systems.
"""

import json
from datetime import datetime
from pathlib import Path


def regenerate_html(json_path: Path, html_path: Path) -> None:
    """
    Regenerate HTML summary report from JSON data.

    Args:
        json_path: Path to the experiment_summary.json file.
        html_path: Path where the HTML report should be written.
    """
    # Load existing results
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    all_results = data["experiments"]
    original_timestamp = data.get("timestamp", "Unknown")

    # Generate HTML content
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
        <p>Original run: {original_timestamp}</p>
        <p>Report regenerated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>
    """

    for suite_name, results in all_results.items():
        html_content += f"<h2>{suite_name.title()} Experiments</h2>"

        for result in results:
            status_class = "success" if result.get("status") == "completed" else "failed"
            html_content += f"""
            <div class="experiment-card {status_class}">
                <h3>{result.get("name", "Unknown")}</h3>
                <p>Status: <strong>{result.get("status", "unknown")}</strong></p>
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
                        <td class="metric">{summary.get("total_requests", 0):,}</td>
                    </tr>
                    <tr>
                        <td>Failures</td>
                        <td class="metric">{summary.get("failure_count", 0):,}</td>
                    </tr>
                    <tr>
                        <td>Requests/sec</td>
                        <td class="metric">{summary.get("requests_per_sec", 0):.1f}</td>
                    </tr>
                    <tr>
                        <td>Median Response (ms)</td>
                        <td class="metric">{summary.get("median_response_ms", 0):.0f}</td>
                    </tr>
                    <tr>
                        <td>P95 Response (ms)</td>
                        <td class="metric">{summary.get("p95_response_ms", 0):.0f}</td>
                    </tr>
                    <tr>
                        <td>P99 Response (ms)</td>
                        <td class="metric">{summary.get("p99_response_ms", 0):.0f}</td>
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

    # Write with UTF-8 encoding to properly handle emojis
    html_path.write_text(html_content, encoding="utf-8")
    print(f"HTML report regenerated successfully: {html_path}")


if __name__ == "__main__":
    # Default paths relative to project root
    project_root = Path(__file__).parent.parent
    json_path = project_root / "experiment_results" / "experiment_summary.json"
    html_path = project_root / "experiment_results" / "experiment_summary.html"

    if not json_path.exists():
        print(f"Error: JSON file not found at {json_path}")
        exit(1)

    regenerate_html(json_path, html_path)

