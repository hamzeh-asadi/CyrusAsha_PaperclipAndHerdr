"""Exercise discovery against an installed Herdr in an isolated, empty session.

Usage: python tests/smoke_herdr_session.py <absolute path to herdr[.exe]>
No dashboard .env, board, provider, agent prompt, or existing user session.
"""

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dashboard"))
import herdr_worker as herdr  # noqa: E402


def check(binary, directory):
    home = Path(directory)
    config = home / "herdr"
    config.mkdir()
    (config / "config.toml").write_text(
        "onboarding = false\n[update]\nversion_check = false\nmanifest_check = false\n", encoding="utf-8"
    )
    # Herdr respects XDG_CONFIG_HOME on native Windows too. Do not attach to
    # a user's pipes, load their config, or hand run credentials to the server.
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("HERDR_", "PAPERCLIP_"))}
    env.update(
        XDG_CONFIG_HOME=directory,
        XDG_STATE_HOME=directory,
        XDG_RUNTIME_DIR=directory,
        HERDR_DESK_EXE=binary,
        HERDR_SESSION="default",
    )
    with patch.dict(os.environ, env, clear=True):
        assert not any(s["running"] for s in herdr.live_sessions()), "expected an isolated config root"
        try:
            herdr.live_targets("default")
        except RuntimeError as exc:
            assert exc.args[0].key == "err.herdrStopped", exc
        else:
            raise AssertionError("stopped server was reported as an empty agent list")
        name = "desk-smoke"
        proc = subprocess.Popen(
            [herdr.herdr_binary(), "--session", name, "server"],
            cwd=home,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
        )
        try:
            deadline = time.monotonic() + 30
            while not any(s["name"] == name and s["running"] for s in herdr.live_sessions()):
                if proc.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError("isolated named server did not become ready")
                time.sleep(0.2)
            # Parent still has HERDR_SESSION=default; the selected namespace must win.
            assert herdr.live_targets(name) == [], "a shell is not a detected agent"
            print("Real Herdr: stopped default, running named session, zero detected agents. No dispatch.")
        finally:
            if proc.poll() is None:
                try:
                    herdr.cli_text("server", "stop", session=name)
                    proc.wait(timeout=10)
                finally:
                    if proc.poll() is None:
                        proc.kill()  # only the child created above
                        proc.wait(timeout=5)


if __name__ == "__main__":
    if len(sys.argv) != 2 or not Path(sys.argv[1]).is_absolute():
        sys.exit(__doc__)
    with tempfile.TemporaryDirectory(prefix="desk herdr ") as tmp:
        check(sys.argv[1], tmp)
