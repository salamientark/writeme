"""Tests for src/secrets.py — file scanning and text secret detection.

Phase 5: M5 (secret scan).

scan_repo_for_risky_files: uses real tmp dirs with fixture files.
scan_text_for_secrets: pure string matching, no I/O.

Return convention for scan_text_for_secrets:
    Returns a list of matched *substrings* from the input string.
    Each element is the exact matching text found.
"""
import os
import tempfile
import unittest
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers to build fixture directory trees
# ---------------------------------------------------------------------------

def _create_file(base: Path, rel_path: str) -> Path:
    """Create an empty file at base/rel_path (creates parent dirs)."""
    p = base / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.touch()
    return p


# ---------------------------------------------------------------------------
# scan_repo_for_risky_files
# ---------------------------------------------------------------------------

class TestScanRepoForRiskyFiles(unittest.TestCase):
    """scan_repo_for_risky_files returns sorted list of matching paths."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._repo_dir = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def _scan(self) -> list[Path]:
        from src.secrets import scan_repo_for_risky_files
        return scan_repo_for_risky_files(self._repo_dir)

    # -- .env files --

    def test_detects_dotenv(self):
        _create_file(self._repo_dir, ".env")
        result = self._scan()
        self.assertTrue(any(p.name == ".env" for p in result))

    def test_detects_dotenv_with_suffix(self):
        _create_file(self._repo_dir, ".env.local")
        result = self._scan()
        self.assertTrue(any(".env." in p.name for p in result))

    def test_detects_dotenv_production(self):
        _create_file(self._repo_dir, ".env.production")
        result = self._scan()
        self.assertTrue(any(p.name == ".env.production" for p in result))

    # -- key / cert files --

    def test_detects_pem_file(self):
        _create_file(self._repo_dir, "server.pem")
        result = self._scan()
        self.assertTrue(any(p.suffix == ".pem" for p in result))

    def test_detects_key_file(self):
        _create_file(self._repo_dir, "id_rsa.key")
        result = self._scan()
        self.assertTrue(any(p.suffix == ".key" for p in result))

    def test_detects_credentials_json(self):
        _create_file(self._repo_dir, "credentials.json")
        result = self._scan()
        self.assertTrue(any(p.name == "credentials.json" for p in result))

    # -- directory patterns --

    def test_detects_aws_directory(self):
        _create_file(self._repo_dir, ".aws/credentials")
        result = self._scan()
        self.assertTrue(any(".aws" in str(p) for p in result))

    def test_detects_ssh_directory(self):
        _create_file(self._repo_dir, ".ssh/id_rsa")
        result = self._scan()
        self.assertTrue(any(".ssh" in str(p) for p in result))

    def test_detects_nested_aws_config(self):
        _create_file(self._repo_dir, ".aws/config")
        result = self._scan()
        self.assertTrue(any(".aws" in str(p) for p in result))

    # -- return type and ordering --

    def test_returns_list(self):
        result = self._scan()
        self.assertIsInstance(result, list)

    def test_returns_sorted_list(self):
        _create_file(self._repo_dir, "z.key")
        _create_file(self._repo_dir, "a.pem")
        _create_file(self._repo_dir, ".env")
        result = self._scan()
        str_paths = [str(p) for p in result]
        self.assertEqual(str_paths, sorted(str_paths))

    def test_returns_path_objects(self):
        _create_file(self._repo_dir, ".env")
        result = self._scan()
        self.assertTrue(all(isinstance(p, Path) for p in result))

    def test_empty_dir_returns_empty_list(self):
        result = self._scan()
        self.assertEqual(result, [])

    def test_safe_file_not_included(self):
        _create_file(self._repo_dir, "README.md")
        _create_file(self._repo_dir, "main.py")
        result = self._scan()
        self.assertEqual(result, [])

    def test_multiple_risky_files_all_detected(self):
        _create_file(self._repo_dir, ".env")
        _create_file(self._repo_dir, "server.pem")
        _create_file(self._repo_dir, "credentials.json")
        result = self._scan()
        self.assertEqual(len(result), 3)


# ---------------------------------------------------------------------------
# scan_text_for_secrets
# ---------------------------------------------------------------------------

class TestScanTextForSecrets(unittest.TestCase):
    """scan_text_for_secrets returns list of matched substrings."""

    def _scan(self, text: str) -> list[str]:
        from src.secrets import scan_text_for_secrets
        return scan_text_for_secrets(text)

    # -- AWS Access Key --

    def test_detects_aws_access_key(self):
        text = "export AWS_KEY=AKIAIOSFODNN7EXAMPLE"
        result = self._scan(text)
        self.assertTrue(any("AKIA" in match for match in result))

    def test_aws_key_pattern_length(self):
        # AKIA + exactly 16 uppercase alphanumeric chars
        text = "AKIAIOSFODNN7EXAMP"  # AKIA + 14 chars = 18 total, too short
        result = self._scan(text)
        # This is only 18 chars total (AKIA + 14), should NOT match AKIA[0-9A-Z]{16}
        matching_aws = [m for m in result if m.startswith("AKIA")]
        self.assertEqual(len(matching_aws), 0)

    def test_aws_key_full_length_matches(self):
        # AKIA + 16 chars = 20 total
        text = "AKIAIOSFODNN7EXAMPLE"  # exactly 20 chars
        result = self._scan(text)
        self.assertTrue(any("AKIA" in m for m in result))

    # -- GitHub token --

    def test_detects_github_personal_token(self):
        text = "token: ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefgh12"
        result = self._scan(text)
        self.assertTrue(any(m.startswith("ghp_") for m in result))

    def test_detects_github_oauth_token(self):
        text = "gho_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefgh12"
        result = self._scan(text)
        self.assertTrue(any(m.startswith("gho_") for m in result))

    def test_detects_github_user_token(self):
        text = "ghu_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefgh12"
        result = self._scan(text)
        self.assertTrue(any(m.startswith("ghu_") for m in result))

    def test_detects_github_server_token(self):
        text = "ghs_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefgh12"
        result = self._scan(text)
        self.assertTrue(any(m.startswith("ghs_") for m in result))

    def test_detects_github_refresh_token(self):
        text = "ghr_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefgh12"
        result = self._scan(text)
        self.assertTrue(any(m.startswith("ghr_") for m in result))

    # -- OpenAI key --

    def test_detects_openai_key(self):
        text = "OPENAI_API_KEY=sk-ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef"
        result = self._scan(text)
        self.assertTrue(any(m.startswith("sk-") for m in result))

    def test_detects_openai_project_key(self):
        text = "sk-proj-ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij1234567890"
        result = self._scan(text)
        self.assertTrue(any("sk-" in m for m in result))

    # -- Private key header --

    def test_detects_rsa_private_key_header(self):
        text = "-----BEGIN RSA PRIVATE KEY-----\nMIIE..."
        result = self._scan(text)
        self.assertTrue(any("PRIVATE KEY" in m for m in result))

    def test_detects_ec_private_key_header(self):
        text = "-----BEGIN EC PRIVATE KEY-----"
        result = self._scan(text)
        self.assertTrue(any("PRIVATE KEY" in m for m in result))

    def test_detects_generic_private_key_header(self):
        text = "-----BEGIN PRIVATE KEY-----"
        result = self._scan(text)
        self.assertTrue(any("PRIVATE KEY" in m for m in result))

    # -- Generic api_key / secret / token patterns --

    def test_detects_api_key_equals_single_quote(self):
        text = "api_key = 'abcdefghijklmnopqrstuvwx'"
        result = self._scan(text)
        self.assertTrue(len(result) > 0, f"Expected match, got: {result}")

    def test_detects_secret_colon_double_quote(self):
        text = 'secret: "abcdefghijklmnopqrstuvwxyz"'
        result = self._scan(text)
        self.assertTrue(len(result) > 0, f"Expected match, got: {result}")

    def test_detects_token_assignment(self):
        text = "TOKEN = 'abcdefghijklmnopqrstuvwx12345'"
        result = self._scan(text)
        self.assertTrue(len(result) > 0)

    def test_detects_api_dash_key(self):
        text = "api-key = 'abcdefghijklmnopqrstuvwxyz'"
        result = self._scan(text)
        self.assertTrue(len(result) > 0)

    # -- Negative tests (no false positives) --

    def test_prose_token_word_no_value_is_clean(self):
        """The word 'token' in prose without an assignment value must NOT match."""
        text = (
            "This README explains how to use the authentication token. "
            "You will need a valid token to access the API. "
            "Tokens expire after 30 days."
        )
        result = self._scan(text)
        self.assertEqual(result, [], f"Unexpected matches: {result}")

    def test_empty_string_returns_empty(self):
        result = self._scan("")
        self.assertEqual(result, [])

    def test_normal_code_no_secrets(self):
        text = """
def greet(name: str) -> str:
    return f"Hello, {name}!"

if __name__ == "__main__":
    print(greet("world"))
"""
        result = self._scan(text)
        self.assertEqual(result, [])

    def test_short_values_not_matched_by_generic(self):
        """Generic pattern requires value >= 16 chars; shorter values ignored."""
        text = "api_key = 'short'"
        result = self._scan(text)
        # 'short' is 5 chars; should NOT match generic pattern
        generic_matches = [m for m in result if "api_key" in m.lower()]
        self.assertEqual(len(generic_matches), 0)

    def test_returns_list(self):
        result = self._scan("no secrets here")
        self.assertIsInstance(result, list)

    def test_multiple_secrets_in_text(self):
        # AWS key: AKIA + 16 uppercase alphanumeric = 20 chars total
        # GitHub token: ghp_ + 36+ alphanumeric chars
        text = (
            "AKIAIOSFODNN7EXAMPLE123456 and "
            "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef1234"
        )
        result = self._scan(text)
        self.assertGreaterEqual(len(result), 2)


if __name__ == "__main__":
    unittest.main()
