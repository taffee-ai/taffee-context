#!/usr/bin/env python3
"""
GitBlobReader: Safe, commit-pinned source code retrieval via git blob.
Ensures zero working tree modification and enforces strict path traversal
and command injection defenses.
"""

import os
import re
import subprocess
import logging
from typing import List

logger = logging.getLogger(__name__)

class GitBlobReader:
    def __init__(self, repo_path: str):
        """
        Initialize reader for a local Git repository.
        
        Args:
            repo_path: Absolute or relative path to git repository root.
            
        Raises:
            ValueError: If repo_path is not an existing git repository.
        """
        self.repo_path = os.path.abspath(os.path.normpath(repo_path))
        git_dir = os.path.join(self.repo_path, ".git")
        if not (os.path.isdir(git_dir) or os.path.isfile(git_dir)):
            raise ValueError(f"Not a git repository: {repo_path}")

    def fetch_lines(self,
                    commit_sha: str,
                    file_path: str,
                    start_line: int,
                    end_line: int) -> List[str]:
        """
        Fetch committed source lines at a pinned commit SHA.
        
        Args:
            commit_sha: Full 40-character hex commit SHA.
            file_path: Repository-relative file path (e.g., 'src/auth.ts').
            start_line: 1-indexed start line (inclusive).
            end_line: 1-indexed end line (inclusive).
            
        Returns:
            List of source lines (without trailing newlines), or [] on error.
            
        Raises:
            ValueError: If commit_sha is malformed or file_path attempts traversal.
        """
        # Validate commit format strictly (40 hex characters)
        if not commit_sha or not re.match(r"^[a-f0-9]{40}$", commit_sha):
            raise ValueError(f"Invalid commit SHA: {commit_sha}")

        # Path traversal defense
        # Disallow empty, absolute, or paths with '..' traversal components
        if not file_path or file_path.startswith("/") or file_path.startswith("\\"):
            raise ValueError(f"Path traversal detected: {file_path}")

        # Normalize and ensure resolved target stays inside self.repo_path
        abs_target = os.path.abspath(os.path.join(self.repo_path, file_path))
        # Add trailing separator for prefix check to prevent repo-adjacent match
        repo_prefix = self.repo_path if self.repo_path.endswith(os.sep) else (self.repo_path + os.sep)
        if not abs_target.startswith(repo_prefix):
            raise ValueError(f"Path traversal detected: {file_path}")

        if start_line > end_line:
            return []

        # Execute git show using argument-list only (shell=False prevents command injection)
        cmd = [
            "git",
            "-c", "safe.directory=*",
            "-C", self.repo_path,
            "show",
            f"{commit_sha}:{file_path}"
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=5,
                shell=False
            )
            if result.returncode != 0:
                logger.warning("Git blob read failed (%s:%s): %s", commit_sha, file_path, result.stderr.strip())
                return []

            # Split lines matching chunker.ts logic (CRLF, CR, LF only; drop one trailing empty)
            raw_text = result.stdout
            lines = re.split(r'\r\n|\r|\n', raw_text)
            if lines and lines[-1] == '':
                lines.pop()

            start_idx = max(0, start_line - 1)
            end_idx = min(len(lines), end_line)
            if start_idx >= len(lines) or start_idx >= end_idx:
                return []
            return lines[start_idx:end_idx]

        except subprocess.TimeoutExpired:
            logger.error("Git blob read timed out (%s:%s)", commit_sha, file_path)
            return []
        except Exception as e:
            logger.error("Git blob read error: %s", e)
            return []
