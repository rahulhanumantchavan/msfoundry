"""Explicit offline loopback examples, never an automatic real-provider fallback."""

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from byoe.contracts import strict_json_loads
from examples.plugins import contains_expected


class MockHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= 1024 * 1024:
            self.send_error(413)
            return
        try:
            body = strict_json_loads(self.rfile.read(length))
            if self.path == "/evaluate":
                result = contains_expected(body["case"], body.get("options", {}))
            elif self.path == "/chat/completions":
                # Explicit mock protocol test, NOT a real model or rubric interpreter.
                payload = strict_json_loads(body["messages"][-1]["content"])
                if not isinstance(payload["rubric"], str) or not payload["rubric"].strip():
                    raise ValueError("A rubric is required")
                judged = contains_expected(payload["case"], {})
                judged.update(schema_version="1.0", metadata={"explicit_mock": True})
                result = {
                    "id": "explicit-offline-mock",
                    "object": "chat.completion",
                    "created": 0,
                    "model": "explicit-offline-mock",
                    "choices": [{
                        "index": 0,
                        "message": {"role": "assistant", "content": json.dumps(judged)},
                        "finish_reason": "stop",
                    }],
                }
            elif self.path == "/target":
                result = {"response": "Mock response: " + body["query"]}
            else:
                self.send_error(404)
                return
            encoded = json.dumps(result, allow_nan=False).encode("utf-8")
        except (ValueError, KeyError, TypeError, IndexError):
            self.send_error(400)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8099)
    args = parser.parse_args()
    with ThreadingHTTPServer(("127.0.0.1", args.port), MockHandler) as server:
        print(f"Explicit mock server: http://127.0.0.1:{server.server_port}", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()