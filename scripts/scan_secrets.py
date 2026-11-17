"""
Scans files tracked by git (and, with --history, every committed version) for
things that look like secrets. Prints file:line and the KIND of match only,
never the matched value.

    python scripts/scan_secrets.py            # tracked files
    python scripts/scan_secrets.py --history  # whole git history (slower)

Exit code 1 when something is found.
"""
import re
import subprocess
import sys

PATTERNS = {
    "groq key": re.compile(r"gsk_[A-Za-z0-9]{20,}"),
    "openai key": re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{32,}"),
    "github token": re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
    "aws access key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "jwt secret assignment": re.compile(r"JWT_SECRET\s*=\s*['\"]?[A-Za-z0-9_\-+/=]{16,}"),
    # placeholders such as kf_password / yourpassword / <password> are allowed
    "password in database url": re.compile(
        r"postgres(?:ql)?(?:\+\w+)?://[^:\s/]+:(?![^@\s]*(?:pass|your|change|example|<))[^@\s]{4,}@",
        re.IGNORECASE),
}
SKIP_SUFFIXES = (".png", ".jpg", ".jpeg", ".pdf", ".ico", ".lock", ".onnx")
ALLOW_FILES = {"scripts/scan_secrets.py"}


def git(*args) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", check=True).stdout


def scan_text(label: str, text: str) -> int:
    found = 0
    for number, line in enumerate(text.splitlines(), start=1):
        for kind, pattern in PATTERNS.items():
            if pattern.search(line):
                print(f"{label}:{number}: looks like a {kind}")
                found += 1
    return found


def main() -> int:
    found = 0
    tracked = [f for f in git("ls-files").splitlines()
               if f not in ALLOW_FILES and not f.lower().endswith(SKIP_SUFFIXES)]
    for name in tracked:
        try:
            with open(name, encoding="utf-8", errors="replace") as handle:
                found += scan_text(name, handle.read())
        except OSError:
            continue

    env_in_history = git("log", "--all", "--oneline", "--", "backend/.env", "frontend/.env.local").strip()
    if env_in_history:
        print("backend/.env or frontend/.env.local appears in git history:")
        print(env_in_history)
        found += 1

    if "--history" in sys.argv:
        for commit in git("rev-list", "--all").split():
            for name in git("diff-tree", "--no-commit-id", "--name-only", "-r", commit).splitlines():
                if name in ALLOW_FILES or name.lower().endswith(SKIP_SUFFIXES):
                    continue
                try:
                    content = git("show", f"{commit}:{name}")
                except subprocess.CalledProcessError:
                    continue
                found += scan_text(f"{commit[:8]}:{name}", content)

    print("no secrets found" if not found else f"{found} possible secret(s) found")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
