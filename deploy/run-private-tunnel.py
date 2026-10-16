#!/usr/bin/env python3
"""Run the private tunnel using Forth's existing OpenAI runtime credential."""
import os
from pathlib import Path
import subprocess

project = Path(__file__).resolve().parent.parent
result = subprocess.run(
    ['docker', 'compose', 'exec', '-T', 'web', 'python', '-c',
     'import os; os.environ.setdefault("DJANGO_SETTINGS_MODULE", "forth.settings"); '
     'from django.conf import settings; print(settings.OPENAI_API_KEY, end="")'],
    cwd=project, capture_output=True, text=True,
)
if result.returncode or not result.stdout.strip():
    raise SystemExit('Forth must be running with an OpenAI runtime credential before the tunnel starts.')
environment = os.environ.copy()
environment['CONTROL_PLANE_API_KEY'] = result.stdout.strip()
binary = Path.home() / '.local/share/forth-tunnel/tunnel-client'
os.execve(binary, [str(binary), 'run', '--profile', 'forth-private'], environment)
