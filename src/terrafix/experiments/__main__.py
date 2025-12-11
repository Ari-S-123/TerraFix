"""
Entry point for running TerraFix experiments from command line.

Usage:
    python -m terrafix.experiments run --type throughput
    python -m terrafix.experiments run --type resilience --failure-rate 0.2
    python -m terrafix.experiments report --input results.json
"""

from .cli import main

if __name__ == "__main__":
    main()
