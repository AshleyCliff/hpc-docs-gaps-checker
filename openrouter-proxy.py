#!/usr/bin/env python3
"""Host-side OpenRouter proxy: injects the API key so the workshop never sees it."""
import http.client, os, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAM, LISTEN = "openrouter.ai", ("127.0.0.1", 8317)

# Deliberately NOT OPENROUTER_API_KEY: Zed reads that name for its own model
# access, and a shared variable means one tool's key silently overrides the
# other's. Keep the audit's key separate so spend limits stay attributable.
KEY_VAR = "WORKSHOP_OPENROUTER_API_KEY"
KEY = (os.environ.get(KEY_VAR) or "").strip()
if not KEY:
    sys.exit(f"{KEY_VAR} is not set")
DROP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
        "te", "trailers", "transfer-encoding", "upgrade", "host",
        "content-length", "authorization"}

class Server(ThreadingHTTPServer):
    daemon_threads = True      # a stalled request must not outlive the process
    allow_reuse_address = True # rebind immediately after restart, no TIME_WAIT
    request_queue_size = 128   # default of 5 wedges under abandoned connections


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.command, self.path))

    def proxy(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        headers = {k: v for k, v in self.headers.items() if k.lower() not in DROP}
        headers["Host"] = UPSTREAM
        headers["Authorization"] = "Bearer " + KEY
        if body is not None:
            headers["Content-Length"] = str(len(body))
        conn = http.client.HTTPSConnection(UPSTREAM, 443, timeout=600)
        try:
            conn.request(self.command, self.path, body=body, headers=headers)
            upstream = conn.getresponse()
            self.send_response(upstream.status, upstream.reason)
            for k, v in upstream.getheaders():
                if k.lower() not in DROP:
                    self.send_header(k, v)
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            while True:
                chunk = upstream.read1(8192)   # read1: never buffer a stream
                if not chunk:
                    break
                self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk))
                self.wfile.flush()
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        finally:
            conn.close()

    do_GET = do_POST = do_PUT = do_DELETE = proxy

# Enough to tell the intended key from a stale or wrong one, without
# printing the secret.
print(
    f"listening on {LISTEN[0]}:{LISTEN[1]} -> {UPSTREAM}  "
    f"[{KEY_VAR}: {len(KEY)} chars, ends ...{KEY[-4:]}]",
    file=sys.stderr,
)
try:
    Server(LISTEN, Handler).serve_forever()
except KeyboardInterrupt:
    pass
