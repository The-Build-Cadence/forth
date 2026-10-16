#!/usr/bin/env python3
"""Privately store the second account's tunnel runtime key and start its service."""
import getpass
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    if not sys.stdin.isatty():
        raise SystemExit('Run this script in an interactive terminal; never pass a key as an argument.')
    key = getpass.getpass('Second OpenAI account runtime API key (hidden): ').strip()
    if not key.startswith('sk-') or any(char.isspace() for char in key):
        raise SystemExit('Expected an OpenAI runtime API key. Nothing changed.')
    directory = Path.home() / '.local/state/forth'
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.tunnel-key-', dir=directory)
    try:
        with os.fdopen(fd, 'w') as output:
            output.write(key)
        os.replace(temporary, directory / 'tunnel-secondary.key')
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    del key
    subprocess.run(['systemctl', '--user', 'enable', 'forth-secondary-tunnel.service'], check=True)
    subprocess.run(['systemctl', '--user', 'restart', 'forth-secondary-tunnel.service'], check=True)
    print('Credential saved with owner-only access; second tunnel service started.')
    print('Connection readiness still needs verification. Tell Codex that this step is complete.')


if __name__ == '__main__':
    main()
