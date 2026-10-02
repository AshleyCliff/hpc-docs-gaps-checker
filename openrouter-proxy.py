#!/usr/bin/env python3
"""Host-side OpenRouter proxy: injects the API key so the workshop never sees it.

Also acts as a narrowly-scoped HTTP CONNECT proxy, so the offline container can
reach a short allowlist of hosts it genuinely needs -- currently just OpenCode's
model catalogue. CONNECT relays encrypted bytes without decrypting them, so this
needs no certificate authority and cannot read the tunnelled traffic.
"""
import http.client, os, select, socket, sys, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAM, LISTEN = "openrouter.ai", ("127.0.0.1", 8317)

# Hosts the container may reach via CONNECT. Keep this list as short as the
# container's actual needs: everything here is a hole in an otherwise offline
# container, and this process reads seven repositories of third-party content.
# Port 443 only -- no plaintext, no arbitrary ports.
CONNECT_ALLOW = {"models.opencode.ai", "models.dev", "api.models.dev"}

# Hosts reachable over PLAIN HTTP via absolute-URI forward proxying, for apt.
# The container is offline, so installing a package (gdb, strace, build deps)
# otherwise needs a new hole in the LXD egress block; this keeps it here, on
# the host, logged and allowlisted, alongside every other exception.
#
# Why plaintext is acceptable for exactly this: apt packages and their indexes
# are GPG-signed and verified against /usr/share/keyrings/*.gpg inside the
# container. A tampered payload fails signature verification and apt refuses
# it, so transport confidentiality is not what protects integrity here. This
# is why Ubuntu ships http:// mirrors by default. Do NOT extend this list to
# hosts whose payloads are not independently signed.
HTTP_ALLOW = {"archive.ubuntu.com", "security.ubuntu.com",
              "ports.ubuntu.com", "esm.ubuntu.com"}

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

    # Timestamped because an untimestamped log cannot separate one run from the
    # next, which cost a full afternoon of misdiagnosis once.
    #
    # `quiet` suppresses this for a request already logged with a reason by a
    # refusal path: send_error() calls log_error() -> log_message(), which
    # otherwise prints the same line twice more under the explicit REFUSED.
    def log_message(self, fmt, *args):
        if getattr(self, "quiet", False):
            return
        sys.stderr.write(
            "%s %s %s\n" % (time.strftime("%H:%M:%S"), self.command, self.path)
        )

    def proxy(self):
        # An absolute-URI request line (GET http://host/path) means the client is
        # using this as a forward proxy -- apt does. A model call arrives as an
        # origin-form path (/api/v1/...). Dispatch on that BEFORE touching
        # headers, because the model path below injects the API key and must
        # never run for a third-party host.
        if self.path.startswith(("http://", "https://")):
            return self.forward_plain()

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
        except (BrokenPipeError, ConnectionResetError):
            # The client went away mid-stream. Routine, not an error: it happens
            # whenever an `opencode run` is killed while a reply is in flight --
            # which `stall-rate.sh` does deliberately on every attempt.
            #
            # Logged as one line rather than left to propagate, because
            # ThreadingHTTPServer prints a 15-line traceback per occurrence and
            # this log is the primary diagnostic for the startup stall. Thirty
            # tracebacks from one measurement batch bury anything real.
            sys.stderr.write(
                "%s %s %s CLIENT GONE (disconnected mid-stream)\n"
                % (time.strftime("%H:%M:%S"), self.command, self.path)
            )
            self.close_connection = True
        finally:
            conn.close()

    # Plain-HTTP forward proxying for allowlisted hosts. Deliberately NOT part
    # of proxy() above: no API key is injected here, and no header is rewritten
    # to point at OpenRouter.
    def forward_plain(self):
        scheme, _, rest = self.path.partition("://")
        hostport, _, path = rest.partition("/")
        host, _, port = hostport.partition(":")
        path = "/" + path

        if scheme != "http" or host not in HTTP_ALLOW:
            sys.stderr.write(
                "%s %s %s REFUSED (not in HTTP_ALLOW)\n"
                % (time.strftime("%H:%M:%S"), self.command, self.path)
            )
            self.quiet = True
            self.send_error(403, "host not permitted")
            return

        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        headers = {k: v for k, v in self.headers.items() if k.lower() not in DROP}
        headers["Host"] = hostport
        if body is not None:
            headers["Content-Length"] = str(len(body))

        try:
            conn = http.client.HTTPConnection(host, int(port or 80), timeout=120)
            conn.request(self.command, path, body=body, headers=headers)
            upstream = conn.getresponse()
        except OSError as e:
            sys.stderr.write(
                "%s %s %s FAILED (%s)\n"
                % (time.strftime("%H:%M:%S"), self.command, self.path, e)
            )
            self.send_error(502, "upstream unreachable")
            return

        # Read the whole body, then relay it with an explicit Content-Length.
        #
        # Deliberately NOT chunked, unlike proxy() above. apt pipelines GETs
        # over one persistent HTTP/1.1 connection and its `http` method wants
        # length-delimited bodies; serving it chunked leaves apt-get and its
        # store/gpgv helpers blocked in poll() with zero CPU, having written
        # nothing -- an indefinite hang, not a slow transfer.
        #
        # Buffering is acceptable here because these are package indexes and
        # .debs (tens of MB), and correctness matters more than peak memory.
        # The model path keeps streaming, because token streaming needs it.
        try:
            payload = upstream.read()
        except OSError as e:
            sys.stderr.write(
                "%s %s %s TRUNCATED (%s)\n"
                % (time.strftime("%H:%M:%S"), self.command, self.path, e)
            )
            conn.close()
            return
        finally:
            conn.close()

        # Same client-disconnect handling as proxy(): apt abandons connections
        # when interrupted, and an unhandled BrokenPipeError here would bury the
        # log in tracebacks just as readily.
        try:
            self.send_response(upstream.status, upstream.reason)
            for k, v in upstream.getheaders():
                if k.lower() not in DROP:
                    self.send_header(k, v)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(payload)
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            sys.stderr.write(
                "%s %s %s CLIENT GONE (disconnected)\n"
                % (time.strftime("%H:%M:%S"), self.command, self.path)
            )
            self.close_connection = True

    do_GET = do_POST = do_PUT = do_DELETE = do_HEAD = proxy

    # CONNECT: relay raw encrypted bytes to an allowlisted host. No TLS is
    # terminated here, so no CA is needed and the payload stays unreadable to
    # this process -- it is a dumb pipe, not an interceptor.
    #
    # Exists because OpenCode fetches its model catalogue over https:// from a
    # hardcoded URL. The container is otherwise offline, and an unreachable
    # catalogue makes OpenCode hang at startup. Letting the fetch *succeed*
    # removes the failure path entirely. Note the host is CDN-backed, so its IPs
    # rotate -- which is why this is allowlisted by name here rather than by CIDR
    # in an LXD ACL.
    def do_CONNECT(self):
        host, _, port = self.path.partition(":")
        if host not in CONNECT_ALLOW or port != "443":
            sys.stderr.write(
                "%s CONNECT %s REFUSED (not in allowlist)\n"
                % (time.strftime("%H:%M:%S"), self.path)
            )
            self.quiet = True
            self.send_error(403, "host not permitted")
            return
        try:
            upstream = socket.create_connection((host, 443), timeout=30)
        except OSError as e:
            sys.stderr.write(
                "%s CONNECT %s FAILED (%s)\n" % (time.strftime("%H:%M:%S"), self.path, e)
            )
            self.send_error(502, "upstream unreachable")
            return
        self.send_response(200, "Connection Established")
        self.end_headers()
        client = self.connection
        with upstream:
            while True:
                ready, _, _ = select.select([client, upstream], [], [], 30)
                if not ready:
                    break
                for src in ready:
                    dst = upstream if src is client else client
                    try:
                        data = src.recv(8192)
                    except OSError:
                        return
                    if not data:
                        return
                    try:
                        dst.sendall(data)
                    except OSError:
                        return

# Enough to tell the intended key from a stale or wrong one, without
# printing the secret.
print(
    f"listening on {LISTEN[0]}:{LISTEN[1]} -> {UPSTREAM}  "
    f"[{KEY_VAR}: {len(KEY)} chars, ends ...{KEY[-4:]}]  "
    f"CONNECT allowlist: {','.join(sorted(CONNECT_ALLOW))}  "
    f"HTTP allowlist: {','.join(sorted(HTTP_ALLOW))}",
    file=sys.stderr,
)
try:
    Server(LISTEN, Handler).serve_forever()
except KeyboardInterrupt:
    pass
