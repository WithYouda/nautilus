from __future__ import annotations

import socket
import subprocess


def wsl_ip() -> str:
    """Return the address Windows can use to reach this WSL2 service."""
    try:
        result = subprocess.run(
            ["ip", "-4", "route", "get", "1.1.1.1"],
            capture_output=True,
            text=True,
            check=True,
            timeout=2,
        )
        fields = result.stdout.split()
        if "src" in fields:
            candidate = fields[fields.index("src") + 1]
            if candidate:
                return candidate
    except (OSError, subprocess.SubprocessError, ValueError):
        pass

    try:
        addresses = socket.gethostbyname_ex(socket.gethostname())[2]
        for address in addresses:
            if not address.startswith("127."):
                return address
    except socket.gaierror:
        pass
    return "unavailable"
