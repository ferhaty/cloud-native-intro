# A teaching example, not a production HTTP server.
from http.server import BaseHTTPRequestHandler, HTTPServer
import json, os, socket

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/healthz":
            body, content_type = b"ok", "text/plain; charset=utf-8"
        else:
            body = json.dumps({
                "orders": [],
                "served_by": socket.gethostname(),
                "version": os.getenv("APP_VERSION", "dev"),
            }).encode()
            content_type = "application/json"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.end_headers()
        self.wfile.write(body)

if __name__ == "__main__":
    HTTPServer(("", 8080), Handler).serve_forever()
