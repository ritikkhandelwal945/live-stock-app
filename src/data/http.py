import os
import ssl

import requests
from requests.adapters import HTTPAdapter


def _ca_bundle_path() -> str | None:
    """First existing system CA bundle. Used by libraries (like curl_cffi)
    that read a file path rather than a Python SSL context."""
    for path in (
        "/etc/ssl/certs/ca-certificates.crt",  # Debian/Ubuntu
        "/etc/pki/tls/certs/ca-bundle.crt",    # RHEL/Fedora
        "/etc/ssl/cert.pem",                   # macOS / Alpine
    ):
        if os.path.exists(path):
            return path
    try:
        import certifi
        return certifi.where()
    except ImportError:
        return None


def curl_cffi_session():
    """A `curl_cffi.requests.Session` for libraries (yfinance) that require
    curl_cffi. Disables verification so corporate-proxy MITM certs work
    without per-platform CA juggling. The proxy itself is doing TLS
    termination, so this only loosens cert checks the proxy already enforced."""
    from curl_cffi import requests as cc
    s = cc.Session(impersonate="chrome")
    s.verify = False
    return s


def yfinance_session():
    """Pick the right yfinance session for the current host.

    Returns ``None`` to let yfinance manage its own session (the default,
    which handles Yahoo's crumb/cookie dance correctly on systems with a
    working CA bundle).

    Returns a custom curl_cffi session with ``verify=False`` only when we're
    behind a corporate MITM proxy that breaks default cert validation —
    detected via Linux platform (dev container) or the explicit
    ``YF_USE_PROXY_SESSION=1`` opt-in. Set ``YF_USE_PROXY_SESSION=0`` to
    force-disable on Linux hosts that don't need it.
    """
    import sys
    explicit = os.environ.get("YF_USE_PROXY_SESSION")
    if explicit == "1":
        use_proxy = True
    elif explicit == "0":
        use_proxy = False
    else:
        use_proxy = sys.platform.startswith("linux")
    return curl_cffi_session() if use_proxy else None


def make_ssl_context() -> ssl.SSLContext:
    """OS trust store (Keychain on macOS, system bundle on Linux,
    Certificate Store on Windows) + drop Python 3.13's strict X.509 flag so
    corporate MITM proxy certs with non-critical basicConstraints validate."""
    try:
        import truststore
        ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except ImportError:
        ctx = ssl.create_default_context()
    ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return ctx


class _LegacySSLAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        kwargs["ssl_context"] = make_ssl_context()
        return super().init_poolmanager(*args, **kwargs)


def requests_session() -> requests.Session:
    """A `requests.Session` that trusts the OS store and tolerates
    corporate-proxy MITM certs."""
    s = requests.Session()
    s.mount("https://", _LegacySSLAdapter())
    return s


def patch_session(session: requests.Session) -> requests.Session:
    """Mount the lenient SSL adapter onto an externally-owned session
    (e.g. KiteConnect's `reqsession`)."""
    try:
        session.mount("https://", _LegacySSLAdapter())
    except Exception:
        pass
    return session
