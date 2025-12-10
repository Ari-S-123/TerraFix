"""
Secure Git operations using credential helpers.

This module provides secure repository cloning without exposing tokens in
process arguments, command-line history, or environment variables visible
to other processes.

Security considerations:
- Uses GIT_ASKPASS credential helper to provide authentication
- Tokens are passed via temporary script files with restricted permissions
- Credential scripts are cleaned up immediately after use
- Error messages are sanitized to prevent token leakage in logs

Usage:
    from terrafix.secure_git import SecureGitClient

    client = SecureGitClient(github_token="ghp_...")
    repo_path = client.clone_repository(
        repo_full_name="org/terraform-repo",
        target_path=Path("/tmp/repo"),
        branch="main"
    )
"""

import os
import platform
import stat
import subprocess
import tempfile
from pathlib import Path

from terrafix.errors import GitHubError
from terrafix.logging_config import get_logger, log_with_context

logger = get_logger(__name__)


class SecureGitClient:
    """
    Git client that handles authentication securely.

    Uses Git credential helpers to provide authentication without
    exposing tokens in process arguments or environment variables
    visible to other processes.

    The client creates temporary credential helper scripts that are
    immediately deleted after use.

    Attributes:
        _token: GitHub personal access token (private to prevent logging)
    """

    def __init__(self, github_token: str) -> None:
        """
        Initialize secure Git client.

        Args:
            github_token: GitHub PAT with repo scope

        Example:
            >>> client = SecureGitClient(github_token="ghp_...")
        """
        self._token: str = github_token

        log_with_context(
            logger,
            "info",
            "Initialized secure Git client",
        )

    def clone_repository(
        self,
        repo_full_name: str,
        target_path: Path,
        branch: str = "main",
        depth: int = 1,
    ) -> Path:
        """
        Clone a GitHub repository securely.

        Uses a temporary credential helper script to provide
        authentication without exposing the token in process listings
        or command-line history.

        Args:
            repo_full_name: Repository in "owner/repo" format
            target_path: Directory to clone into
            branch: Branch to clone (default: "main")
            depth: Clone depth (default: 1 for shallow clone)

        Returns:
            Path to cloned repository

        Raises:
            GitHubError: If clone operation fails

        Example:
            >>> repo_path = client.clone_repository(
            ...     "org/terraform-repo",
            ...     Path("/tmp/repo"),
            ...     branch="main"
            ... )
        """
        clone_url = f"https://github.com/{repo_full_name}.git"

        # Create platform-appropriate credential helper script
        cred_script_path = self._create_credential_script()

        try:
            # Configure environment for secure credential passing
            env = os.environ.copy()
            env["GIT_ASKPASS"] = str(cred_script_path)
            env["GIT_TERMINAL_PROMPT"] = "0"  # Disable interactive prompts

            # Build clone command
            cmd = [
                "git", "clone",
                "--depth", str(depth),
                "--branch", branch,
                "--single-branch",
                clone_url,
                str(target_path),
            ]

            log_with_context(
                logger,
                "info",
                "Cloning repository",
                repo=repo_full_name,
                branch=branch,
                depth=depth,
            )

            result = subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
            )

            if result.returncode != 0:
                # Sanitize error message to remove any token traces
                error_msg = self._sanitize_output(result.stderr)
                log_with_context(
                    logger,
                    "error",
                    "Git clone failed",
                    repo=repo_full_name,
                    error=error_msg,
                )
                raise GitHubError(
                    f"Git clone failed: {error_msg}",
                    retryable=True,
                )

            log_with_context(
                logger,
                "info",
                "Successfully cloned repository",
                repo=repo_full_name,
                path=str(target_path),
            )

            return target_path

        except subprocess.TimeoutExpired:
            log_with_context(
                logger,
                "error",
                "Git clone timed out",
                repo=repo_full_name,
            )
            raise GitHubError(
                f"Git clone timed out for {repo_full_name}",
                retryable=True,
            )

        except FileNotFoundError:
            log_with_context(
                logger,
                "error",
                "Git command not found",
            )
            raise GitHubError(
                "Git command not found. Please install git.",
                retryable=False,
            )

        finally:
            # Always clean up credential script
            self._cleanup_credential_script(cred_script_path)

    def _create_credential_script(self) -> Path:
        """
        Create temporary credential helper script.

        Creates a platform-appropriate script that outputs credentials
        in the format expected by Git's credential helper system.

        Returns:
            Path to the temporary credential script

        Note:
            On Unix systems, the script is a shell script.
            On Windows, it's a batch file.
        """
        is_windows = platform.system() == "Windows"

        if is_windows:
            # Windows batch script
            suffix = ".bat"
            script_content = f"""@echo off
echo username=x-access-token
echo password={self._token}
"""
        else:
            # Unix shell script
            suffix = ".sh"
            script_content = f"""#!/bin/sh
echo "username=x-access-token"
echo "password={self._token}"
"""

        # Create temporary file with restricted permissions
        fd, script_path = tempfile.mkstemp(suffix=suffix, prefix="terrafix_cred_")
        
        try:
            # Write script content
            _ = os.write(fd, script_content.encode("utf-8"))
        finally:
            os.close(fd)

        # Make script executable (Unix only, no-op on Windows)
        if not is_windows:
            os.chmod(script_path, stat.S_IRWXU)  # 0o700 - owner only

        return Path(script_path)

    def _cleanup_credential_script(self, script_path: Path) -> None:
        """
        Securely delete credential script.

        Args:
            script_path: Path to the credential script to delete
        """
        try:
            if script_path.exists():
                # Overwrite with zeros before deletion (defense in depth)
                try:
                    with open(script_path, "wb") as f:
                        _ = f.write(b"\x00" * 1024)
                except Exception:
                    pass  # Best effort overwrite

                script_path.unlink()

        except OSError as e:
            log_with_context(
                logger,
                "warning",
                "Failed to cleanup credential script",
                error=str(e),
            )

    def _sanitize_output(self, output: str) -> str:
        """
        Remove sensitive information from Git output.

        Args:
            output: Raw Git command output

        Returns:
            Sanitized output with token removed
        """
        if not output:
            return ""

        # Replace token if it appears in output
        sanitized = output.replace(self._token, "[REDACTED]")

        # Also redact any x-access-token patterns
        import re
        sanitized = re.sub(
            r"x-access-token:[^\s@]+",
            "x-access-token:[REDACTED]",
            sanitized,
        )

        return sanitized

    def pull_latest(
        self,
        repo_path: Path,
        branch: str = "main",
    ) -> None:
        """
        Pull latest changes from remote.

        Securely fetches and merges changes from the remote repository.

        Args:
            repo_path: Path to local repository
            branch: Branch to pull (default: "main")

        Raises:
            GitHubError: If pull operation fails

        Example:
            >>> client.pull_latest(Path("/tmp/repo"), branch="main")
        """
        cred_script_path = self._create_credential_script()

        try:
            env = os.environ.copy()
            env["GIT_ASKPASS"] = str(cred_script_path)
            env["GIT_TERMINAL_PROMPT"] = "0"

            result = subprocess.run(
                ["git", "pull", "origin", branch],
                cwd=str(repo_path),
                env=env,
                capture_output=True,
                text=True,
                timeout=120,
            )

            if result.returncode != 0:
                error_msg = self._sanitize_output(result.stderr)
                raise GitHubError(
                    f"Git pull failed: {error_msg}",
                    retryable=True,
                )

            log_with_context(
                logger,
                "info",
                "Pulled latest changes",
                repo_path=str(repo_path),
                branch=branch,
            )

        except subprocess.TimeoutExpired:
            raise GitHubError(
                "Git pull timed out",
                retryable=True,
            )

        finally:
            self._cleanup_credential_script(cred_script_path)

