"""Secret scanning utilities for gh-readme-pipeline.

Addresses: M5 (pre/post secret scanning).

Two public functions:

    scan_repo_for_risky_files(repo_dir: Path) -> list[Path]
        Returns a sorted list of paths matching known-risky file patterns.

    scan_text_for_secrets(s: str) -> list[str]
        Returns a list of matched substrings (exact text from input) that
        resemble secrets.  Returns an empty list when no secrets are found.

Design notes
------------
- Filesystem globs use Path.rglob for recursive traversal.
- Regex patterns are compiled once at module import time.
- Each matched substring is the literal text extracted from the input.
- The generic api_key/secret/token pattern requires a value of ≥ 16
  characters inside single or double quotes to avoid false positives on
  prose that merely contains words like "token" or "secret".
"""
import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Risky file patterns
# ---------------------------------------------------------------------------

# Glob patterns matched against the entire repo tree.
# Directories (.aws/**, .ssh/**) are expressed as recursive globs.
_RISKY_GLOBS: list[str] = [
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "credentials.json",
    ".aws/**",
    ".ssh/**",
]


def scan_repo_for_risky_files(repo_dir: Path) -> list[Path]:
    """Return a sorted list of paths inside *repo_dir* matching risky patterns.

    Patterns searched:
    - ``.env``, ``.env.*``  (dotenv files)
    - ``*.pem``, ``*.key``  (certificate / private key files)
    - ``credentials.json``  (GCP / generic credentials)
    - ``.aws/**``           (AWS credentials directory)
    - ``.ssh/**``           (SSH key directory)

    Args:
        repo_dir: Root directory of the cloned repository.

    Returns:
        Sorted list of absolute Path objects for every matching file.
        Directories themselves are excluded; only files are returned.
    """
    found: set[Path] = set()
    for pattern in _RISKY_GLOBS:
        for match in repo_dir.rglob(pattern):
            if match.is_file():
                found.add(match)
    return sorted(found)


# ---------------------------------------------------------------------------
# Secret text patterns
# ---------------------------------------------------------------------------

# Each tuple: (compiled pattern, description)
# Patterns return the full matching substring so the caller can display it.
_SECRET_PATTERNS: list[re.Pattern] = [
    # AWS access key: AKIA followed by exactly 16 uppercase letters/digits
    re.compile(r'AKIA[0-9A-Z]{16}'),

    # GitHub token variants: ghp_, gho_, ghu_, ghs_, ghr_ + ≥36 alphanumeric chars
    re.compile(r'gh[pousr]_[A-Za-z0-9]{36,}'),

    # OpenAI key: sk- or sk-proj- followed by ≥20 alphanumeric chars
    re.compile(r'sk-[A-Za-z0-9\-]{20,}'),

    # Private key PEM header
    re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----'),

    # Generic: api_key / api-key / secret / token followed by = or : and a
    # quoted value of ≥ 16 alphanumeric/underscore/hyphen characters.
    # Case-insensitive on the keyword side.
    re.compile(
        r'(?i)(?:api[_-]?key|secret|token)\s*[=:]\s*[\'"][A-Za-z0-9_\-]{16,}[\'"]'
    ),
]


def scan_text_for_secrets(s: str) -> list[str]:
    """Return a list of secret-like substrings found in *s*.

    Each element in the returned list is the exact matched substring from
    the input string, not a pattern name.  Callers can display these
    directly in warnings.

    Patterns searched:
    - AWS access keys  (``AKIA[0-9A-Z]{16}``)
    - GitHub tokens    (``gh[pousr]_[A-Za-z0-9]{36,}``)
    - OpenAI keys      (``sk-[A-Za-z0-9-]{20,}``)
    - PEM private key headers
    - Generic api_key / secret / token assignments with quoted values ≥ 16 chars

    Intentional non-matches (no false positives):
    - Prose containing only the word "token" without an assignment.
    - Short quoted values (< 16 chars) next to key-like words.

    Args:
        s: The text to scan (e.g. new README content).

    Returns:
        List of matched substrings, possibly empty.
    """
    matches: list[str] = []
    for pattern in _SECRET_PATTERNS:
        for m in pattern.finditer(s):
            matches.append(m.group(0))
    return matches
