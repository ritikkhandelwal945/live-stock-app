import os
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from dotenv import load_dotenv
from kiteconnect import KiteConnect

from src.auth.token_store import save_token, load_token
from src.data.http import patch_session

load_dotenv()


def _patch(kite: KiteConnect) -> KiteConnect:
    patch_session(kite.reqsession)
    return kite

CALLBACK_PORT = 5678
CALLBACK_PATH = "/callback"


class _TokenCaptureHandler(BaseHTTPRequestHandler):
    request_token: str | None = None

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == CALLBACK_PATH:
            params = parse_qs(parsed.query)
            status = params.get("status", [None])[0]
            if status == "success":
                _TokenCaptureHandler.request_token = params.get("request_token", [None])[0]
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(b"<h2>Login successful! You can close this tab.</h2>")
            else:
                self.send_response(400)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(b"<h2>Login failed. Please try again.</h2>")
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # Suppress HTTP logs


def get_kite_client() -> KiteConnect:
    api_key = os.environ.get("KITE_API_KEY", "")
    if not api_key:
        raise RuntimeError("KITE_API_KEY not set. Copy .env.example to .env and fill in your credentials.")
    return _patch(KiteConnect(api_key=api_key))


def get_authenticated_kite() -> KiteConnect:
    api_key = os.environ.get("KITE_API_KEY", "")
    if not api_key:
        raise RuntimeError("KITE_API_KEY not set.")

    token = load_token()
    if token:
        kite = _patch(KiteConnect(api_key=api_key))
        kite.set_access_token(token)
        return kite

    raise RuntimeError(
        "No valid access token found. Run 'stock-app auth' to log in first."
    )


def login(manual: bool = False) -> KiteConnect:
    api_key = os.environ.get("KITE_API_KEY", "")
    api_secret = os.environ.get("KITE_API_SECRET", "")
    if not api_key or not api_secret:
        raise RuntimeError(
            "KITE_API_KEY and KITE_API_SECRET must be set. "
            "Copy .env.example to .env and fill in your credentials."
        )

    kite = _patch(KiteConnect(api_key=api_key))
    login_url = kite.login_url()

    if manual:
        print(f"\nOpen this URL in your browser:\n{login_url}")
        print(f"\nAfter login, you'll be redirected. Copy the 'request_token' from the URL.")
        request_token = input("Paste request_token here: ").strip()
    else:
        print(f"\nOpening browser for Zerodha login...")
        print(f"If browser doesn't open, visit: {login_url}\n")
        webbrowser.open(login_url)

        print(f"Waiting for login callback on http://127.0.0.1:{CALLBACK_PORT}{CALLBACK_PATH} ...")
        server = HTTPServer(("127.0.0.1", CALLBACK_PORT), _TokenCaptureHandler)
        _TokenCaptureHandler.request_token = None
        while _TokenCaptureHandler.request_token is None:
            server.handle_request()
        server.server_close()
        request_token = _TokenCaptureHandler.request_token

    if not request_token:
        raise RuntimeError("Failed to obtain request_token from Zerodha login.")

    session = kite.generate_session(request_token, api_secret=api_secret)
    access_token = session["access_token"]
    save_token(access_token)
    kite.set_access_token(access_token)

    print("Login successful! Token saved for today.")
    return kite
