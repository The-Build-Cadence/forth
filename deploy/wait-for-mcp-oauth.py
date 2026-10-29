#!/usr/bin/env python3
"""Wait for private OAuth discovery before starting the tunnel after boot."""
import json
import sys
import time
from urllib.request import urlopen


def ready(base_url):
    for path, required in (
        ('/.well-known/oauth-protected-resource', ('resource', 'authorization_servers')),
        ('/.well-known/oauth-authorization-server', ('issuer', 'authorization_endpoint', 'token_endpoint')),
    ):
        with urlopen(base_url.rstrip('/') + path, timeout=5) as response:
            metadata = json.load(response)
        if not isinstance(metadata, dict) or not all(metadata.get(key) for key in required):
            return False
    return True


def main():
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        try:
            if ready(sys.argv[1]):
                print('Forth OAuth discovery is ready for the MCP tunnel.', flush=True)
                return 0
        except (OSError, ValueError):
            pass
        time.sleep(3)
    print('Forth OAuth discovery is unavailable; systemd will retry tunnel startup.', file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
