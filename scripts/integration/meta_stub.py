"""A stand-in for Meta's Graph API, so an integration run can read the exact
text the citizen would have received.

Uses the adapter's own documented test seam (`WHATSAPP_GRAPH_API_BASE_URL`),
which `WhatsAppAdapterTest` already relies on — no live Meta account, and the
gateway's real HTTP client, payload shaping and error handling all still run.

Records every send to sent.jsonl, one JSON object per line.
"""

import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sent.jsonl")


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8")
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            body = {"_unparseable": raw}
        with open(OUT, "a", encoding="utf-8") as f:
            f.write(json.dumps({"path": self.path, "body": body}) + "\n")

        wamid = "wamid.stub" + str(abs(hash(raw)))[:12]
        response = json.dumps({
            "messaging_product": "whatsapp",
            "contacts": [{"wa_id": body.get("to", "")}],
            "messages": [{"id": wamid}],
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    open(OUT, "w", encoding="utf-8").close()
    print("meta stub listening on 9099, recording to", OUT, flush=True)
    HTTPServer(("127.0.0.1", 9099), Handler).serve_forever()
