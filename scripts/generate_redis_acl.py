#!/usr/bin/env python3
"""Generate local Redis ACL files and matching bot secret files.

Explicit opt-in helper; never runs automatically on bot startup or in a
production deployment. It refuses to overwrite any existing credential.
"""
import argparse
import os
from pathlib import Path
from secrets import token_urlsafe

ACL_USERNAME = "filebot"


def generate(output_dir: Path) -> tuple[str, ...]:
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    output_dir.chmod(0o700)
    files = (
        "redis-cache.password", "redis-cache.acl",
        "redis-state.password", "redis-state.acl",
    )
    if any((output_dir / filename).exists() or
           (output_dir / filename).is_symlink() for filename in files):
        raise FileExistsError("Refusing to replace existing Redis credentials")

    # Directory mode 0700 protects host-side secrets. File mode 0644 ensures
    # containers running as nonroot can read Compose bind-mounted secrets.
    # Docker Compose restricts which *services* receive each secret.
    generated = []
    try:
        for prefix in ("redis-cache", "redis-state"):
            password = token_urlsafe(48)
            values = {
                f"{prefix}.password": password + "\n",
                f"{prefix}.acl": (
                    "user default off\n"
                    f"user {ACL_USERNAME} on >{password} ~* &* +@all -@dangerous\n"
                ),
            }
            for name, value in values.items():
                path = output_dir / name
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
                if hasattr(os, "O_NOFOLLOW"):
                    flags |= os.O_NOFOLLOW
                fd = os.open(path, flags, 0o600)
                generated.append(path)
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(value)
                path.chmod(0o644)
    except Exception:
        for path in generated:
            path.unlink(missing_ok=True)
        raise
    return files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=".secrets")
    args = parser.parse_args()
    result = generate(Path(args.output_dir))
    print("Generated four credential files in a private directory.")
    print("Names:", ", ".join(result))
    print("No passwords were printed. Never add the directory to Git.")


if __name__ == "__main__":
    main()
