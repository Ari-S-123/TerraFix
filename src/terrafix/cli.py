"""
CLI interface for TerraFix.

Provides command-line interface for manual testing and operations.

Usage:
    python -m terrafix.cli process-once --failure-json failure.json
"""

import argparse
import json
import sys
from pathlib import Path

from terrafix.config import Settings, get_settings
from terrafix.github_pr_creator import GitHubPRCreator
from terrafix.logging_config import get_logger, log_with_context, setup_logging
from terrafix.orchestrator import process_failure
from terrafix.remediation_generator import TerraformRemediationGenerator
from terrafix.vanta_client import Failure, VantaClient

logger = get_logger(__name__)


def main() -> int:
    """
    CLI main entry point.

    Returns:
        Exit code (0 for success, 1 for error)
    """
    parser = argparse.ArgumentParser(
        description="TerraFix CLI - AI-Powered Terraform Compliance Remediation"
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # process-once command
    process_parser = subparsers.add_parser(
        "process-once",
        help="Process a single failure from JSON file",
    )
    _ = process_parser.add_argument(
        "--failure-json",
        type=str,
        required=True,
        help="Path to JSON file containing Vanta failure",
    )

    # stats command - parser not accessed directly but registered with subparsers
    _ = subparsers.add_parser(
        "stats",
        help="Show state store statistics",
    )

    # cleanup command
    cleanup_parser = subparsers.add_parser(
        "cleanup",
        help="Cleanup old state records",
    )
    _ = cleanup_parser.add_argument(
        "--retention-days",
        type=int,
        default=7,
        help="Days to retain records (default: 7)",
    )

    args = parser.parse_args()

    command: str | None = str(args.command) if args.command else None
    if not command:
        parser.print_help()
        return 1

    # Load configuration
    try:
        settings = get_settings()
    except Exception as e:
        print(f"Failed to load configuration: {e}", file=sys.stderr)
        return 1

    # Setup logging
    setup_logging(settings.log_level)

    # Execute command - command is guaranteed non-None at this point
    try:
        if command == "process-once":
            return cmd_process_once(args, settings)
        if command == "stats":
            return cmd_stats(args, settings)
        if command == "cleanup":
            return cmd_cleanup(args, settings)
        print(f"Unknown command: {command}", file=sys.stderr)
        return 1

    except Exception as e:
        log_with_context(
            logger,
            "error",
            "Command failed",
            command=command,
            error=str(e),
        )
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_process_once(args: argparse.Namespace, settings: Settings) -> int:
    """
    Process a single failure from JSON file.

    Args:
        args: Command arguments
        settings: Application settings

    Returns:
        Exit code
    """
    # Import here to avoid circular imports and allow StateStore usage
    from terrafix.redis_state_store import RedisStateStore

    # Load failure from JSON
    failure_json_arg: str = str(args.failure_json) if args.failure_json else ""
    if not failure_json_arg:
        print("Invalid failure-json argument", file=sys.stderr)
        return 1

    failure_path = Path(failure_json_arg)
    if not failure_path.exists():
        print(f"File not found: {failure_path}", file=sys.stderr)
        return 1

    with open(failure_path, "r") as f:
        failure_data: dict[str, object] = json.load(f)

    try:
        failure = Failure.model_validate(failure_data)
    except Exception as e:
        print(f"Invalid failure JSON: {e}", file=sys.stderr)
        return 1

    log_with_context(
        logger,
        "info",
        "Processing single failure",
        test_id=failure.test_id,
        resource_arn=failure.resource_arn,
    )

    # Initialize clients
    vanta = VantaClient(
        api_token=settings.vanta_api_token,
        base_url=settings.vanta_base_url,
    )

    generator = TerraformRemediationGenerator(
        model_id=settings.bedrock_model_id,
        region=settings.aws_region,
    )

    gh = GitHubPRCreator(github_token=settings.github_token)

    state_store = RedisStateStore(
        redis_url=settings.redis_url,
        ttl_days=settings.state_retention_days,
    )

    try:
        # Process failure
        result = process_failure(
            failure=failure,
            config=settings,
            state_store=state_store,
            vanta=vanta,
            generator=generator,
            gh=gh,
        )

        if result.success:
            if result.skipped:
                print("Failure was already processed (skipped)")
            else:
                print(f"Successfully created PR: {result.pr_url}")
            return 0
        else:
            print(f"Failed to process failure: {result.error}", file=sys.stderr)
            return 1

    finally:
        state_store.close()


def cmd_stats(
    args: argparse.Namespace,
    settings: Settings,
) -> int:
    _ = args  # Unused but part of CLI interface
    """
    Show state store statistics.

    Args:
        args: Command arguments
        settings: Application settings

    Returns:
        Exit code
    """
    from terrafix.redis_state_store import RedisStateStore

    state_store = RedisStateStore(
        redis_url=settings.redis_url,
        ttl_days=settings.state_retention_days,
    )

    try:
        stats = state_store.get_statistics()

        print("State Store Statistics:")
        print(f"  Total records: {stats.get('total', 0)}")
        print(f"  Pending: {stats.get('pending', 0)}")
        print(f"  In Progress: {stats.get('in_progress', 0)}")
        print(f"  Completed: {stats.get('completed', 0)}")
        print(f"  Failed: {stats.get('failed', 0)}")

        return 0

    finally:
        state_store.close()


def cmd_cleanup(args: argparse.Namespace, settings: Settings) -> int:
    """
    Cleanup old state records.

    Args:
        args: Command arguments
        settings: Application settings

    Returns:
        Exit code
    """
    from terrafix.redis_state_store import RedisStateStore

    state_store = RedisStateStore(
        redis_url=settings.redis_url,
        ttl_days=settings.state_retention_days,
    )

    retention_days_raw: object = getattr(args, "retention_days", 7)
    retention_days: int = int(str(retention_days_raw)) if retention_days_raw else 7
    try:
        deleted = state_store.cleanup_old_records(retention_days)
        print(f"Deleted {deleted} old records")
        return 0

    finally:
        state_store.close()


if __name__ == "__main__":
    sys.exit(main())

