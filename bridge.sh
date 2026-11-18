#!/usr/bin/env bash
# Paperclip -> Herdr bridge. Run by Paperclip's "process" adapter on every heartbeat.
# Needs: bash, curl, jq, herdr (same OS user as the running herdr server).
#
# Set per agent in adapterConfig.env:
#   HERDR_TARGET   agent name or pane id in herdr (e.g. agy-worker or w1:p2)
#   HERDR_MODE     "agent" (herdr recognises the agent) or "pane" (unrecognised TUI, e.g. Freebuff)
#   WAIT_MS        max time for one task, default 1800000 (30 min)
#   QUIET_SEC      pane mode: seconds of unchanged screen that count as "finished", default 45
#   DONE_STATUS    status to set afterwards, default in_review
set -euo pipefail

: "${PAPERCLIP_API_URL:?}" "${PAPERCLIP_API_KEY:?}" "${PAPERCLIP_AGENT_ID:?}" "${PAPERCLIP_COMPANY_ID:?}"
: "${HERDR_TARGET:?set HERDR_TARGET in adapterConfig.env}"
MODE="${HERDR_MODE:-agent}"
WAIT_MS="${WAIT_MS:-1800000}"
QUIET_SEC="${QUIET_SEC:-45}"
DONE_STATUS="${DONE_STATUS:-in_review}"

api() { # api METHOD PATH [JSON]
  local method="$1" path="$2" body="${3:-}"
  curl -sS --fail-with-body -X "$method" "$PAPERCLIP_API_URL$path" \
    -H "Authorization: Bearer $PAPERCLIP_API_KEY" \
    -H "X-Paperclip-Run-Id: ${PAPERCLIP_RUN_ID:-}" \
    -H "Content-Type: application/json" ${body:+-d "$body"}
}

# 1) inbox: first in_progress, otherwise first todo
issues=$(api GET "/api/companies/$PAPERCLIP_COMPANY_ID/issues?assigneeAgentId=$PAPERCLIP_AGENT_ID&status=todo,in_progress")
issue=$(jq -c '(if type=="array" then . else (.issues // .data // []) end)
               | (map(select(.status=="in_progress")) + map(select(.status=="todo"))) | .[0] // empty' <<<"$issues")
if [ -z "$issue" ]; then echo "no assigned work"; exit 0; fi
id=$(jq -r '.id' <<<"$issue")
title=$(jq -r '.title // ""' <<<"$issue")
desc=$(jq -r '.description // ""' <<<"$issue")
echo "task $id: $title"

# 2) checkout (409 = someone else owns it -> stop, never retry).
#    "in_progress" is included so a task left behind by a crashed run is re-claimed by this run.
if ! api POST "/api/issues/$id/checkout" \
     "$(jq -n --arg a "$PAPERCLIP_AGENT_ID" '{agentId:$a,expectedStatuses:["todo","backlog","blocked","in_review","in_progress"]}')" >/dev/null; then
  echo "checkout refused, skipping"; exit 0
fi

# 3) hand the task to the agent living in herdr (single line: TUIs submit on newline)
code=$(printf '%s' "$id" | tr -cd 'a-zA-Z0-9' | cut -c1-8)
MARKER="PAPERCLIP_DONE_${code}"
prompt=$(printf 'Task: %s. Details: %s. When completely finished, write a short summary of what you changed, then a final line made of these two parts joined with no space between them: PAPERCLIP_DONE_ and %s. Do not write that joined word before you are finished.' "$title" "$desc" "$code" | tr '\r\n' '  ')

if [ "$MODE" = "agent" ]; then
  herdr agent prompt "$HERDR_TARGET" "$prompt" --wait --timeout "$WAIT_MS" || echo "herdr wait ended abnormally (blocked/timeout)"
  state=$(herdr agent get "$HERDR_TARGET" 2>/dev/null | jq -r '.result.agent.agent_status // "unknown"' || echo unknown)
  out=$(herdr agent read "$HERDR_TARGET" --source recent-unwrapped --lines 120 || true)
else
  herdr pane send-text "$HERDR_TARGET" "$prompt"
  sleep 1
  herdr pane send-keys "$HERDR_TARGET" enter
  # no agent detection for unknown TUIs: "finished" = the agent printed MARKER,
  # or (fallback) the screen stayed unchanged for QUIET_SEC
  deadline=$(( $(date +%s) + WAIT_MS / 1000 )); last=""; same_since=$(date +%s); state="timeout"
  sleep 10
  while [ "$(date +%s)" -lt "$deadline" ]; do
    recent=$(herdr pane read "$HERDR_TARGET" --source recent-unwrapped --lines 200 || true)
    if grep -qF "$MARKER" <<<"$recent"; then state="done"; sleep 3; break; fi
    cur=$(herdr pane read "$HERDR_TARGET" --source visible || true)
    if [ "$cur" != "$last" ]; then last="$cur"; same_since=$(date +%s); fi
    if [ $(( $(date +%s) - same_since )) -ge "$QUIET_SEC" ]; then state="quiet"; break; fi
    sleep 5
  done
  out=$(herdr pane read "$HERDR_TARGET" --source recent-unwrapped --lines 120 || true)
fi

# 4) report back
comment=$(printf 'Herdr target `%s` finished with state **%s**.\n\n````text\n%s\n````' "$HERDR_TARGET" "$state" "$out")
api POST "/api/issues/$id/comments" "$(jq -n --arg b "$comment" '{body:$b}')" >/dev/null

case "$state" in
  idle|done|quiet) api PATCH "/api/issues/$id" "$(jq -n --arg s "$DONE_STATUS" '{status:$s}')" >/dev/null ;;
  *) echo "state=$state: leaving task open for a human"; exit 1 ;;
esac
echo "reported"
