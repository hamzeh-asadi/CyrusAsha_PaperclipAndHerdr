"""Portable Paperclip `process` worker. Uses the per-run identity, NEVER dashboard/.env.

Only Herdr's agent API can receive text. An unrecognised TUI (or a bare shell)
uses the manual handoff in the desk instead; no raw keystrokes go to panes.
"""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote, urlencode

from desk_text import Message
from paperclip_client import PaperclipError, request_json, request_human_review


def herdr_binary():
    """No shell, PATH edits or executable supplied by a web request."""
    preferred = os.environ.get("HERDR_DESK_EXE")
    name = "herdr.exe" if os.name == "nt" else "herdr"
    if preferred:
        path = Path(preferred)
        if not path.is_absolute() or path.name.casefold() != name or not path.is_file():
            raise RuntimeError(Message("err.herdrExe"))
        return str(path)
    binary = shutil.which(name)
    if os.name == "nt" and os.getenv("LOCALAPPDATA"):
        # The installer adds a versioned directory to PATH. Save its stable alias
        # when it points to that same release, or use it if PATH predates install.
        alias = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "Herdr" / "bin" / name
        try:
            if alias.is_file() and (not binary or alias.samefile(binary)):
                return str(alias)
        except OSError:
            pass  # e.g. an update rotated the alias during lookup
    if binary:
        return os.path.abspath(binary)
    raise RuntimeError(Message("err.herdrMissing"))


def safe_session(name):
    """True for a Herdr session name that is safe as a single CLI argument."""
    return (
        isinstance(name, str)
        and name not in (".", "..")
        and re.fullmatch(r"[a-zA-Z0-9._-]{1,64}", name) is not None
    )


def _cli_failure(result):
    """Map a failed Herdr call to fixed copy; never echo stderr or prompt text."""
    # Never echo stderr, the prompt argv, filesystem paths or terminal output.
    known = {
        "server_not_running": "err.herdrStopped",
        "protocol_mismatch": "err.herdrProtocol",
        "permission_denied": "err.herdrAccess",
    }
    for stream in (result.stdout, result.stderr):
        try:
            error = json.loads(stream)["error"]
            if isinstance(error, dict) and isinstance(error.get("code"), str) and error["code"] in known:
                return Message(known[error["code"]])
        except (TypeError, ValueError, KeyError, IndexError):
            pass
    reason = (result.stderr or "").lower()
    if "access is denied" in reason or "permission denied" in reason or "os error 5)" in reason:
        return Message("err.herdrAccess")
    if result.returncode == 2 and any(
        word in reason for word in ("usage:", "unrecognized", "unknown command", "unknown option")
    ):
        return Message("err.herdrVersion")
    return Message("err.herdrExit", code=str(result.returncode))


def cli_text(*args, timeout=8, session=None):
    """Run the Herdr CLI and return stdout, raising desk messages for known failures."""
    if session is not None and not safe_session(session):
        raise ValueError(Message("err.sessionName"))
    binary = herdr_binary()
    scope = [] if session is None else ["--session=" + session]
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("PAPERCLIP_")}
    try:
        result = subprocess.run(
            [binary, *scope, *args],
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            encoding="utf-8-sig",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(Message("err.herdrTimeout")) from None
    except PermissionError:
        raise RuntimeError(Message("err.herdrAccess")) from None
    except OSError:
        raise RuntimeError(Message("err.herdrStart")) from None
    if result.returncode:
        raise RuntimeError(_cli_failure(result))
    return result.stdout


def herdr(*args, timeout=8, session=None):
    """Run one Herdr subcommand and return its ``result`` object."""
    response = cli_text(*args, timeout=timeout, session=session)
    try:
        payload = json.loads(response)["result"]
        if not isinstance(payload, dict):
            raise ValueError
        return payload
    except (TypeError, ValueError, KeyError):
        raise RuntimeError(Message("err.herdrJson")) from None


def live_sessions():
    """List local Herdr sessions with only name, running and unreachable flags."""
    # session list is local metadata (no server required). Unlike agent list,
    # it returns a top-level sessions array, not an API {result: ...} envelope.
    try:
        rows = json.loads(cli_text("session", "list", "--json"))["sessions"]
        if not isinstance(rows, list) or not all(
            isinstance(r, dict) and safe_session(r.get("name")) and isinstance(r.get("running"), bool)
            for r in rows
        ):
            raise ValueError
        return [
            {"name": r["name"], "running": r["running"], "unreachable": bool(r.get("connection_error"))}
            for r in rows
        ]
    except (TypeError, KeyError, ValueError):
        raise RuntimeError(Message("err.sessionList")) from None


def safe_target(value):
    """True for a Herdr target or pane id that is safe as a single CLI argument."""
    return isinstance(value, str) and re.fullmatch(r"[\w][\w.:-]{0,119}", value) is not None


def live_targets(session=None):
    """Return the detected agents of one Herdr session as CLI targets."""
    records = herdr("agent", "list", session=session).get("agents")
    if not isinstance(records, list):
        raise RuntimeError(Message("err.herdrList"))
    targets = []
    for item in records:
        if not isinstance(item, dict):
            continue
        # A display label/kind is not a unique CLI target. Unnamed agents must
        # stay pinned to their terminal identity; pane numbers can be recycled.
        target = item.get("name") or item.get("pane_id")
        terminal = "" if item.get("name") else item.get("terminal_id")
        kind = item.get("agent")
        if (
            safe_target(target)
            and isinstance(terminal, str)
            and (item.get("name") or terminal)
            and isinstance(kind, str)
            and kind
        ):
            targets.append(
                {
                    "target": target,
                    "terminal": terminal,
                    "kind": kind,
                    "name": item.get("name"),
                    "pane_id": item.get("pane_id"),
                    "status": item.get("agent_status", "unknown"),
                }
            )
    return targets


def prompt_ready(info):
    """`interactive_ready` is a newer field; older Herdr servers omit it entirely."""
    return info.get("agent_status") in ("idle", "done") and info.get("interactive_ready") is not False


def bound_agent(target, terminal, kind, session=None):
    """Re-read the bound terminal and prove it still matches the saved binding."""
    if not safe_target(target):
        raise ValueError(Message("err.target"))
    info = herdr("agent", "get", target, session=session).get("agent")
    if (
        not isinstance(info, dict)
        or not info.get("terminal_id")
        or not kind
        or info.get("agent") != kind
        or (
            info.get("name") != target
            if not terminal
            else (info.get("pane_id") != target or info.get("terminal_id") != terminal)
        )
    ):
        raise RuntimeError(Message("err.herdrBinding"))
    return info


def select_work(board, company, agent, run_id):
    """Pick the one ready issue for this run, or None when nothing is ready."""
    # The process adapter does not always export TASK_ID. For an issue-scoped
    # wake, read the *actual* run, not the first item on the company's board.
    run = board("/api/heartbeat-runs/" + quote(run_id, safe=""))
    if (run.get("id"), run.get("companyId"), run.get("agentId")) != (run_id, company, agent):
        raise RuntimeError("Run identity mismatch; no prompt sent.")
    if any(
        run.get(k)
        for k in ("retryOfRunId", "processLossRetryCount", "scheduledRetryAttempt", "continuationAttempt")
    ):
        raise RuntimeError(
            "Automatic retry after an earlier attempt. Inspect the terminal before re-dispatching."
        )
    context = run.get("contextSnapshot") or {}
    task_id = (
        run.get("issueId")
        or context.get("issueId")
        or context.get("taskId")
        or os.getenv("PAPERCLIP_TASK_ID")
    )
    if task_id:
        if os.getenv("PAPERCLIP_TASK_ID", task_id) != task_id:
            raise RuntimeError("Inconsistent wake context; no prompt sent.")
        rows = [board("/api/issues/" + quote(task_id, safe=""))]
    elif run.get("invocationSource") == "on_demand" and run.get("triggerDetail") == "manual":
        query = urlencode({"assigneeAgentId": agent, "status": "todo"})
        rows = board(f"/api/companies/{quote(company, safe='')}/issues?{query}")
    else:
        return None
    for issue in rows:
        if (
            issue.get("companyId") == company
            and issue.get("assigneeAgentId") == agent
            and (not task_id or issue.get("id") == task_id)
            and (
                issue.get("status") == "todo"
                or (issue.get("status") == "in_progress" and issue.get("checkoutRunId") == run_id)
            )
        ):
            return issue
    return None


def run(target, terminal, kind, session=None):
    """Deliver this run's issue to the bound agent, then request human review."""
    if not safe_target(target):
        raise ValueError(Message("err.target"))
    company, agent, run_id, url, key = (
        os.environ["PAPERCLIP_" + name] for name in ("COMPANY_ID", "AGENT_ID", "RUN_ID", "API_URL", "API_KEY")
    )

    def board(path, method="GET", data=None):
        """Call Paperclip with this run's own credentials, never the dashboard's."""
        return request_json(url, path, method, key=key, run_id=run_id, data=data, timeout=15)

    issue = select_work(board, company, agent, run_id)
    if not issue:
        print("No assigned ready task.")
        return
    path = "/api/issues/" + quote(issue["id"], safe="")
    info = bound_agent(target, terminal, kind, session)
    if not prompt_ready(info):
        raise RuntimeError("Herdr target is not idle and ready. No prompt sent.")
    if issue["status"] == "todo":
        try:
            checked = board(path + "/checkout", "POST", {"agentId": agent, "expectedStatuses": ["todo"]})
        except PaperclipError as exc:
            if exc.status == 409:
                print("Task already claimed; no prompt sent.")
                return
            raise
        if not isinstance(checked, dict) or any(
            checked.get(k) != v
            for k, v in {
                "id": issue["id"],
                "companyId": company,
                "assigneeAgentId": agent,
                "checkoutRunId": run_id,
                "status": "in_progress",
            }.items()
        ):
            raise RuntimeError("Unconfirmed checkout. No prompt sent.")
        issue = checked
    text = f"Paperclip {issue.get('identifier') or issue['id']}: {issue['title']}. {issue.get('description') or ''}"
    text = re.sub(r"[\x00-\x1f\x7f-\x9f]+", " ", text)[:12000]
    # A blocked, timed out or vanished agent never marks an issue successful.
    try:
        end = herdr(
            "agent", "prompt", target, text, "--wait", "--timeout", "1800000", timeout=1810, session=session
        ).get("agent")
    except RuntimeError as exc:
        raise RuntimeError("Delivery outcome unknown. Inspect the terminal before retrying.") from exc
    if (
        not isinstance(end, dict)
        or not info.get("terminal_id")
        or end.get("terminal_id") != info["terminal_id"]
        or end.get("agent") != kind
    ):
        raise RuntimeError("Agent did not finish on the same terminal. Inspect Herdr; task left open.")
    if end.get("agent_status") not in ("idle", "done"):
        # Herdr reports a pane with a permission, question or trust dialog as blocked.
        raise RuntimeError(Message("err.herdrBlocked", target=target))
    try:
        request_human_review(board, path, run_id)
    except PaperclipError as exc:
        raise RuntimeError(
            f"Herdr finished. Repair the human review in Paperclip; do NOT repeat the prompt. {exc}"
        ) from exc
    print("Handoff complete; awaiting human review.")


if __name__ == "__main__":
    try:
        if sys.argv[1:] == ["manual"]:
            print("Manual agent: copy the assigned task from the desk into your running CLI. No prompt sent.")
        elif len(sys.argv) in (5, 6) and sys.argv[1] == "agent":
            run(*sys.argv[2:])
        else:
            raise ValueError("Invalid worker configuration")
    except (RuntimeError, OSError, ValueError, KeyError, TypeError) as error:
        sys.exit(f"Paperclip/Herdr: {error}")
