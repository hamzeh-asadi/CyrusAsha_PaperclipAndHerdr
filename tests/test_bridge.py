"""Bridge smoke tests using real curl/jq and no live agents or credentials."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

BRIDGE = Path(__file__).resolve().parents[1] / "bridge.sh"


class Board(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'[{"id":"t1","title":"Test ticket","status":"todo"}]')

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.writes.append((self.command, self.path, body))
        self.send_response(self.server.checkout_status if self.path.endswith("/checkout") else 200)
        self.end_headers()
        self.wfile.write(b"{}")

    do_PATCH = do_POST

    def log_message(self, *args):
        pass


@unittest.skipUnless(os.name == "posix" and all(shutil.which(k) for k in ("bash", "curl", "jq")), "requires Bash, curl and jq")
class BridgeTests(unittest.TestCase):
    def test_dispatch_outcomes(self):
        with tempfile.TemporaryDirectory() as tmp, HTTPServer(("127.0.0.1", 0), Board) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                herdr = Path(tmp, "herdr")
                herdr.write_text('''#!/bin/sh
case "$2" in
 prompt) exit "$PROMPT_RC";;
 get) echo '{"result":{"agent":{"agent_status":"idle"}}}';;
 read) echo "sample output"; exit "$READ_RC";;
 send-text|send-keys) exit 0;;
 *) exit 1;;
esac
''')
                herdr.chmod(0o755)
                Path(tmp, "sleep").write_text("#!/bin/sh\nexit 0\n")
                Path(tmp, "sleep").chmod(0o755)
                # Only a successful, readable dispatch may advance the ticket.
                for code, mode, prompt, read, success, advanced in [
                    (200, "agent", 0, 0, True, True), (409, "agent", 0, 0, True, False),
                    (401, "agent", 0, 0, False, False), (200, "agent", 1, 0, False, False),
                    (200, "agent", 0, 1, False, False), (200, "pane", 0, 1, False, False),
                ]:
                    with self.subTest(checkout=code, mode=mode, prompt=prompt, read=read):
                        server.checkout_status, server.writes = code, []
                        env = dict(os.environ, PATH=tmp + os.pathsep + os.environ["PATH"],
                                   PAPERCLIP_API_URL=f"http://127.0.0.1:{server.server_port}",
                                   PAPERCLIP_API_KEY="test-only", PAPERCLIP_COMPANY_ID="c1", PAPERCLIP_AGENT_ID="a1",
                                   HERDR_TARGET="worker", HERDR_MODE=mode, PROMPT_RC=str(prompt), READ_RC=str(read))
                        result = subprocess.run(["bash", BRIDGE], env=env, capture_output=True, text=True, timeout=10)
                        self.assertEqual(result.returncode == 0, success, result.stderr)
                        self.assertEqual(any(m == "PATCH" for m, _, _ in server.writes), advanced)
                        if code != 200:
                            self.assertEqual(len(server.writes), 1)
            finally:
                server.shutdown()
                thread.join()


if __name__ == "__main__":
    unittest.main(verbosity=2)
