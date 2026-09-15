"""Fail the build if a published artifact contains anything secret-shaped.

This is a backstop, not the primary defence. The primary defence is the field
allowlist in ``radar.export_public``: internal state never reaches ``dist``
because it is not on the list of fields the exporter copies.

This check exists because an allowlist is only as good as its last edit. If
someone adds a field to the allowlist by mistake, the leak would otherwise ship
silently and be visible to anyone who opens the browser dev tools. Turning that
into a red CI job is the difference between a caught mistake and an incident.

Runs as ``python -m tests.scan_secrets dist``.

Deliberately conservative: this looks for *shapes* that only ever appear in
credentials, and skips the known-safe placeholder text the site legitimately
ships (the CC Switch preview documents where a key goes without including one).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Extensions worth reading. Binary assets are skipped: a PNG cannot leak a key
# in a greppable form, and reading them wastes time.
TEXT_SUFFIXES = {
    ".html",
    ".htm",
    ".json",
    ".js",
    ".mjs",
    ".css",
    ".svg",
    ".md",
    ".txt",
    ".xml",
    ".webmanifest",
    ".yml",
    ".yaml",
}

# A very large file in dist is a data dump, not a page. Skip rather than
# spend minutes scanning a 50 MB JSON with dozens of patterns.
MAX_BYTES = 12 * 1024 * 1024

# Each pattern is (name, regex, explanation). The explanation is printed on a
# hit so the person reading CI does not have to guess what matched.
PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    (
        "openai-style key",
        re.compile(r"\bsk-(?:proj-|live-|test-)?[A-Za-z0-9_\-]{20,}"),
        "OpenAI/Anthropic style secret key",
    ),
    (
        "anthropic key",
        re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}"),
        "Anthropic API key",
    ),
    (
        "google api key",
        re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}"),
        "Google API key",
    ),
    (
        "github token",
        re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}"),
        "GitHub personal access / app token",
    ),
    (
        "github fine-grained token",
        re.compile(r"\bgithub_pat_[A-Za-z0-9_]{30,}"),
        "GitHub fine-grained token",
    ),
    (
        "groq key",
        re.compile(r"\bgsk_[A-Za-z0-9]{30,}"),
        "Groq API key",
    ),
    (
        "openrouter key",
        re.compile(r"\bsk-or-v1-[A-Za-z0-9]{30,}"),
        "OpenRouter API key",
    ),
    (
        "huggingface token",
        re.compile(r"\bhf_[A-Za-z0-9]{30,}"),
        "Hugging Face token",
    ),
    (
        "aws access key id",
        re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
        "AWS access key id",
    ),
    (
        "private key block",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----"),
        "PEM private key",
    ),
    (
        "slack token",
        re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}"),
        "Slack token",
    ),
    (
        "jwt",
        re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),
        "JSON Web Token",
    ),
    (
        "bearer literal",
        # `Bearer ${key}` and `Bearer YOUR_KEY` are documentation, not leaks.
        re.compile(r"Bearer\s+[A-Za-z0-9_\-]{32,}"),
        "literal bearer credential",
    ),
]

# Lines containing any of these are documentation about keys rather than keys.
# The site intentionally explains where a user types their own key.
ALLOW_LINE_MARKERS = (
    "YOUR_API_KEY",
    "YOUR_KEY",
    "your-api-key",
    "your_api_key",
    "<api_key>",
    "<API_KEY>",
    "${",
    "{{",
    "REDACTED",
    "PLACEHOLDER",
    "example.com",
    "sk-...",
    "sk-xxx",
    "xxxxx",
    "apiKey: null",
    '"apiKey":null',
)


def should_scan(path: Path) -> bool:
    if path.suffix.lower() not in TEXT_SUFFIXES:
        return False
    try:
        return path.stat().st_size <= MAX_BYTES
    except OSError:
        return False


def is_allowed(line: str) -> bool:
    return any(marker.lower() in line.lower() for marker in ALLOW_LINE_MARKERS)


def scan_file(path: Path) -> list[str]:
    findings: list[str] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return findings

    for line_number, line in enumerate(text.splitlines(), start=1):
        if is_allowed(line):
            continue
        for name, pattern, explanation in PATTERNS:
            match = pattern.search(line)
            if not match:
                continue
            # Never print the match itself. A CI log is a public place, and
            # echoing the secret would complete the leak this check exists to
            # prevent. Report only the shape and the location.
            findings.append(
                f"{path}:{line_number}: [{name}] {explanation} "
                f"(matched {len(match.group(0))} chars, not printed)"
            )
    return findings


def main(argv: list[str]) -> int:
    targets = [Path(a) for a in argv[1:]]
    if not targets:
        print("usage: python -m tests.scan_secrets <dir-or-file> [...]")
        return 2

    findings: list[str] = []
    scanned = 0

    for target in targets:
        if not target.exists():
            print(f"note: {target} does not exist; skipping")
            continue
        walker = target.rglob("*") if target.is_dir() else [target]
        for path in walker:
            if not path.is_file() or not should_scan(path):
                continue
            scanned += 1
            findings.extend(scan_file(path))

    if findings:
        print(f"FAIL  {len(findings)} secret-shaped string(s) in {scanned} scanned file(s)\n")
        for line in findings[:50]:
            print("  -", line)
        if len(findings) > 50:
            print(f"  ... and {len(findings) - 50} more")
        print(
            "\nIf this is a false positive, add the line's safe marker to "
            "ALLOW_LINE_MARKERS in tests/scan_secrets.py. If it is real, the "
            "exporter's field allowlist needs fixing before this can pass."
        )
        return 1

    print(f"ok    no secret-shaped strings in {scanned} scanned file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
