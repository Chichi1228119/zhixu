"""Canonical web origins: scheme, hostname and effective port."""
from urllib.parse import urlsplit


def canonical_origin(value):
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in {'http', 'https'} or not parsed.hostname
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path not in {'', '/'}):
            return None
        port = parsed.port if parsed.port is not None else (443 if parsed.scheme == 'https' else 80)
        if not 1 <= port <= 65535:
            return None
        return parsed.scheme, parsed.hostname, port
    except ValueError:
        return None
