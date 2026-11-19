"use strict";
const $ = (id) => document.getElementById(id);
const { t, text, copy } = DeskLocale;
let members = [],
  issues = [],
  liveTargets = [],
  sessions = [],
  targetScope = null,
  company = null,
  local = false,
  online = null;
let pendingPlan = null,
  loading = false,
  teamBusy = false,
  saving = false,
  scanning = false;
let targetListState = "initial",
  outputVersion = 0;
const inFlight = new Set();
const eligible = (a) => ["active", "idle", "running"].includes(a.status) && a.assignable !== false;
const isHermes = (a) => ["hermes_local", "hermes_gateway"].includes(a.adapterType);
const memberFor = (id) => members.find((a) => a.id === id);
const ref = (i) => i.identifier || i.id;
const stateName = (value) =>
  DeskLocale.has("state." + value) ? t("state." + value) : value || t("state.unknown");
const shortMode = (a) =>
  a.connection?.mode === "manual"
    ? t("team.shortManual")
    : a.connection?.mode === "agent"
      ? ["Herdr", a.connection.session, a.connection.target].filter(Boolean).join(" · ")
      : a.adapterType || "Paperclip";
function el(tag, cls, value) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (value != null) n.textContent = text(value);
  return n;
}
function btn(label, fn, cls = "ghost") {
  const b = el("button", cls, label);
  b.type = "button";
  b.addEventListener("click", fn);
  return b;
}
function boardLink(label, path) {
  const a = el("a", "link", t(label) + " ↗");
  a.href = company.boardUrl + "/" + path;
  a.target = "_blank";
  a.rel = "noopener noreferrer";
  return a;
}
// Keep the semantic copy for visible feedback and dialogs: a language switch can
// repaint it without replaying a request, clearing an error or rebuilding the form.
const bindings = new Map();
function paint(id, binding) {
  const n = $(id),
    value = text(binding.value);
  if (n instanceof HTMLTextAreaElement) {
    if (n.value !== value) n.value = value;
  } else n.textContent = value;
  if (binding.follow)
    n.append(
      " ",
      btn(t("msg.viewWork"), () => go("tasks"), "link"),
    );
}
function bind(id, value, follow = false) {
  const binding = { value, follow };
  bindings.set(id, binding);
  paint(id, binding);
}
function message(id, value, error = false, follow = false) {
  $(id).className = `message${error ? " warn" : ""}`;
  $(id).hidden = !text(value);
  bind(id, value, follow);
}
function status(value) {
  return el("span", "status " + (DeskLocale.has("state." + value) ? value : ""), stateName(value));
}
function person(a) {
  const row = el("div", "person"),
    info = el("div");
  const av = el(
    "span",
    "avatar",
    Array.from(a.name || "?")
      .slice(0, 2)
      .join(""),
  );
  av.setAttribute("aria-hidden", "true");
  const name = el("b", "", a.name);
  name.dir = "auto";
  info.append(name, el("small", "", shortMode(a)));
  row.append(av, info);
  return row;
}
function options(select, choices, placeholder) {
  const signature = JSON.stringify([placeholder, choices]);
  if (select.dataset.options === signature) return;
  const before = select.value;
  select.replaceChildren(new Option(placeholder, ""));
  choices.forEach(([id, label]) => select.add(new Option(label, id)));
  select.value = choices.some(([id]) => id === before) ? before : "";
  select.dataset.options = signature;
}
const errorCopy = (e) => e.detail ?? e.message;
async function api(path, data) {
  let res, value;
  try {
    res = await fetch(path, {
      method: data === undefined ? "GET" : "POST",
      cache: "no-store",
      headers: {
        "Accept-Language": document.documentElement.lang,
        ...(data === undefined ? {} : { "Content-Type": "application/json" }),
      },
      body: data === undefined ? undefined : JSON.stringify(data),
    });
    value = await res.json();
  } catch {
    throw Object.assign(new Error(), { detail: copy("msg.network") });
  }
  if (!res.ok) throw Object.assign(new Error(value.error || `HTTP ${res.status}`), { detail: value.i18n });
  return value;
}
function go(tab) {
  document.querySelectorAll("[data-page]").forEach((n) => (n.hidden = n.dataset.page !== tab));
  document.querySelectorAll("[data-tab]").forEach((n) => {
    n.classList.toggle("selected", n.dataset.tab === tab);
    if (n.dataset.tab === tab) n.setAttribute("aria-current", "page");
    else n.removeAttribute("aria-current");
  });
  if (tab === "team" && $("mode").value === "agent" && targetListState === "initial") scan();
}
async function refresh() {
  if (loading) return;
  loading = true;
  $("refresh").disabled = true;
  const errors = [];
  try {
    online = (await api("/health")).paperclip === true;
    if (!online) throw Object.assign(new Error(), { detail: copy("msg.offline") });
    const [roster, tickets] = await Promise.allSettled([api("/api/agents"), api("/api/tickets")]);
    if (roster.status === "fulfilled") {
      members = roster.value.agents;
      company = roster.value.company;
      local = roster.value.localControl;
    } else {
      members = [];
      company = null;
      local = false;
      errors.push(errorCopy(roster.reason));
    }
    if (tickets.status === "fulfilled") issues = tickets.value.tickets;
    else {
      issues = [];
      errors.push(errorCopy(tickets.reason));
    }
    if (company && !local) errors.push(copy("msg.readOnly"));
  } catch (e) {
    online = false;
    company = null;
    local = false;
    members = [];
    issues = [];
    errors.push(errorCopy(e));
  } finally {
    loading = false;
    $("refresh").disabled = false;
  }
  const unique = errors.filter((e, i) => errors.findIndex((other) => text(e) === text(other)) === i);
  message(
    "notice",
    unique.flatMap((e, i) => (i ? ["\n", e] : [e])),
    true,
  );
  render();
}
function render() {
  $("health").textContent = t(online == null ? "app.connecting" : online ? "app.online" : "app.offline");
  $("health").classList.toggle("online", online === true);
  $("company").textContent = company?.name || t("app.company");
  $("agentCount").textContent = text(members.length);
  $("taskCount").textContent = text(issues.length);
  $("teamPreview").replaceChildren(
    ...(members.length ? members.slice(0, 4).map(person) : [el("div", "empty", t("msg.firstMember"))]),
  );
  const parentWas = $("parent").value;
  options(
    $("parent"),
    issues.map((i) => [i.id, `${ref(i)} · ${i.titleWarning ? t("work.checkTitle") + " · " : ""}${i.title}`]),
    t("plan.newParent"),
  );
  if (parentWas && !$("parent").value && !pendingPlan) message("planFeedback", copy("msg.parentGone"), true);
  syncParent();
  const choices = members.filter(eligible).map((a) => [a.id, a.name]);
  document.querySelectorAll(".assignee").forEach((s) => options(s, choices, t("step.select")));
  options(
    $("filter"),
    members.map((a) => [a.id, a.name]),
    t("work.all"),
  );
  $("savePlan").textContent = t(pendingPlan && !saving ? "msg.retry" : "plan.save");
  $("savePlan").disabled = saving || !local || (!pendingPlan && !choices.length);
  updateEnroll();
  renderTeam();
  renderTasks();
}
function syncParent() {
  const existing = !!$("parent").value;
  $("titleLabel").hidden = existing;
  $("planTitle").required = !existing;
  const issue = issues.find((i) => i.id === $("parent").value);
  const warning = $("parentWarning");
  warning.hidden = !issue?.titleWarning;
  warning.replaceChildren();
  if (issue?.titleWarning) {
    warning.append(t("work.titleWarning", { id: ref(issue) }));
    if (company?.boardUrl)
      warning.append(" ", boardLink("work.editTitle", "issues/" + encodeURIComponent(ref(issue))));
  }
}
function numberSteps() {
  [...$("steps").children].forEach(
    (r, i) => (r.querySelector(".step-num").textContent = t("step.number", { n: i + 1 })),
  );
}
function addStep(title = "") {
  if ($("steps").children.length >= 20) return message("planFeedback", copy("msg.maxSteps"), true);
  const row = $("stepTemplate").content.firstElementChild.cloneNode(true);
  DeskLocale.apply(row);
  row.querySelector(".step-title").value = title;
  options(
    row.querySelector("select"),
    members.filter(eligible).map((a) => [a.id, a.name]),
    t("step.select"),
  );
  row.querySelector(".remove").onclick = () => {
    row.remove();
    if (!$("steps").children.length) addStep();
    numberSteps();
  };
  $("steps").append(row);
  numberSteps();
  return row;
}
function template() {
  const topic = (
    $("parent").value ? issues.find((i) => i.id === $("parent").value)?.title : $("planTitle").value
  )?.trim();
  if (!topic) return message("planFeedback", copy("msg.needParent"), true);
  const rows = [...$("steps").children];
  if (
    rows.length === 1 &&
    !rows[0].querySelector("input").value &&
    !rows[0].querySelector("select").value &&
    !rows[0].querySelector("textarea").value
  )
    rows[0].remove();
  if ($("steps").children.length > 17) return message("planFeedback", copy("msg.templateFull"), true);
  ["template.define", "template.build", "template.test"].forEach((key) =>
    addStep(t(key) + " — " + topic.slice(0, 160)),
  );
  message("planFeedback", copy("msg.template"));
}
function unlockPlan() {
  pendingPlan = null;
  $("planFields").disabled = false;
  $("discard").hidden = true;
  $("savePlan").textContent = t("plan.save");
}
async function savePlan(event) {
  event.preventDefault();
  if (saving || !local || !company) return;
  if (!pendingPlan)
    pendingPlan = {
      companyId: company.id,
      requestId: crypto.randomUUID(),
      parentId: $("parent").value,
      title: $("parent").value ? "" : $("planTitle").value,
      steps: [...$("steps").children].map((r) => ({
        title: r.querySelector("input").value,
        assigneeAgentId: r.querySelector("select").value,
        description: r.querySelector("textarea").value,
      })),
    };
  saving = true;
  $("savePlan").disabled = true;
  $("discard").hidden = true;
  $("planFields").disabled = true;
  message("planFeedback", copy("msg.saving"));
  try {
    const data = await api("/api/plans", pendingPlan);
    unlockPlan();
    $("planTitle").value = "";
    $("parent").value = "";
    syncParent();
    $("steps").replaceChildren();
    addStep();
    message(
      "planFeedback",
      copy("msg.saved", { id: ref(data.parent), count: data.children.length }),
      false,
      true,
    );
  } catch (e) {
    message("planFeedback", [errorCopy(e), "\n", copy("msg.retryHelp")], true);
    $("discard").hidden = false;
    $("savePlan").textContent = t("msg.retry");
  } finally {
    saving = false;
    $("savePlan").disabled = !local;
    await refresh();
  }
}
function updateEnroll() {
  const unselected =
    $("mode").value === "agent" && (scanning || !$("target").value || targetScope !== $("namespace").value);
  $("enroll").disabled = teamBusy || !local || unselected;
}
function renderMode() {
  const live = $("mode").value === "agent";
  $("targetFields").hidden = !live;
  $("target").required = $("namespace").required = live;
  $("modeHint").textContent = t(live ? "team.linkedHint" : "team.manualHint");
  options(
    $("namespace"),
    sessions.map((s) => [s.name, s.name]),
    t("team.selectSession"),
  );
  options(
    $("target"),
    liveTargets.map((s) => [s.target, `${s.target} · ${s.kind} · ${stateName(s.status)}`]),
    t("team.selectAgent"),
  );
  $("namespace").disabled = scanning || !sessions.length;
  $("target").disabled = scanning || !liveTargets.length;
  $("useManual").hidden = scanning || !["failed", "empty"].includes(targetListState);
  updateEnroll();
}
function modeChanged() {
  renderMode();
  if ($("mode").value === "agent" && local) scan();
}
async function scan(refreshSessions = true) {
  if (scanning || !local) return;
  scanning = true;
  $("scan").disabled = true;
  liveTargets = [];
  targetScope = null;
  renderMode();
  bind("targetHint", copy("team.scanning"));
  try {
    if (refreshSessions) {
      const before = $("namespace").value;
      sessions = [];
      const data = await api("/api/herdr/sessions");
      sessions = data.sessions.filter((s) => s.running);
      renderMode();
      if (!sessions.length) {
        targetListState = "empty";
        bind(
          "targetHint",
          copy(data.sessions.some((s) => s.unreachable) ? "err.herdrAccess" : "team.noServer"),
        );
        return;
      }
      if (!before && sessions.length === 1) $("namespace").value = sessions[0].name;
    }
    const session = $("namespace").value;
    if (!session) {
      targetListState = "choose";
      bind("targetHint", copy("team.chooseServer"));
      return;
    }
    const data = await api("/api/herdr/targets?session=" + encodeURIComponent(session));
    targetScope = session;
    liveTargets = data.targets;
    targetListState = liveTargets.length ? "loaded" : "empty";
    bind("targetHint", copy(liveTargets.length ? "team.match" : "team.noDetected", { session }));
  } catch (e) {
    targetListState = "failed";
    bind("targetHint", errorCopy(e));
  } finally {
    scanning = false;
    $("scan").disabled = false;
    renderMode();
  }
}
async function enroll(event) {
  event.preventDefault();
  if (teamBusy || !local || !company) return;
  const data = {
    companyId: company.id,
    name: $("memberName").value,
    mode: $("mode").value,
    target: $("mode").value === "agent" ? $("target").value : "",
  };
  if (data.mode === "agent") {
    const selected = liveTargets.find((s) => s.target === data.target);
    if (!selected || scanning || !targetScope || targetScope !== $("namespace").value)
      return message("enrollFeedback", copy("team.pickAgain"), true);
    data.session = targetScope;
    data.kind = selected.kind;
    data.terminal = selected.terminal;
  }
  teamBusy = true;
  $("enrollFields").disabled = true;
  message("enrollFeedback", copy("team.saving"));
  try {
    const r = await api("/api/team/enroll", data);
    message("enrollFeedback", [
      copy(r.existing ? "team.exists" : "team.saved", { name: r.agent.name }),
      " ",
      copy(r.needsApproval || r.agent.status === "pending_approval" ? "team.approveHint" : "team.readyHint"),
    ]);
  } catch (e) {
    message("enrollFeedback", errorCopy(e), true);
  } finally {
    teamBusy = false;
    $("enrollFields").disabled = false;
    await refresh();
  }
}
function renderTeam() {
  const grid = $("agentsGrid");
  grid.replaceChildren();
  if (!members.length) {
    grid.append(el("div", "empty", t("team.empty")));
    return;
  }
  for (const a of members) {
    const card = el("article", "member"),
      head = el("div", "section-head");
    const phase = a.verificationFailed
      ? "verificationFailed"
      : a.lifecycleState && a.lifecycleState !== "ready"
        ? a.lifecycleState
        : a.status;
    head.append(person(a), status(phase));
    card.append(head);
    if (a.verificationFailed) card.append(el("p", "message warn", t("team.verifyHint")));
    if (isHermes(a) && !a.connection) card.append(el("small", "", t("team.nativeHermes")));
    if (a.status === "pending_approval") card.append(el("small", "", t("team.awaiting")));
    const actions = el("div", "task-actions");
    actions.append(
      btn(t("team.memberWork"), () => {
        $("filter").value = a.id;
        renderTasks();
        go("tasks");
      }),
    );
    if (company?.boardUrl)
      actions.append(
        a.status === "pending_approval"
          ? boardLink("team.approvals", "approvals/pending")
          : boardLink("team.board", "agents/" + encodeURIComponent(a.id)),
      );
    if (company?.boardUrl && (isHermes(a) || a.verificationFailed))
      actions.append(boardLink("team.configureTest", "agents/" + encodeURIComponent(a.id) + "/runtime"));
    if (a.connection?.mode !== "manual" && local) {
      const wake = btn(t("team.wake"), () => {
        if (confirm(t("team.confirmWake", { name: a.name })))
          action(
            "wake:" + a.id,
            () => api(`/api/agents/${encodeURIComponent(a.id)}/heartbeat/invoke`, {}),
            copy("team.woke"),
          );
      });
      wake.disabled = !eligible(a) || inFlight.has("wake:" + a.id);
      actions.append(wake);
      if (!isHermes(a) || a.hasOutputMapping || a.connection?.mode === "agent")
        actions.append(btn(t("team.output"), () => showOutput(a)));
    }
    card.append(actions);
    grid.append(card);
  }
}
function dialog(title, hint, value) {
  bind("detailTitle", title);
  bind("detailHint", hint);
  bind("detailText", value);
  bind("copyHint", "");
  if (!$("detail").open) $("detail").showModal();
}
async function showOutput(a) {
  dialog(a.name, copy("dialog.output"), copy("dialog.loading"));
  const req = ++outputVersion;
  try {
    const r = await api(`/api/agents/${encodeURIComponent(a.id)}/output`);
    if (req === outputVersion)
      bind(
        "detailText",
        r.success ? r.output || copy("dialog.empty") : r.error || copy("dialog.unavailable"),
      );
  } catch (e) {
    if (req === outputVersion) bind("detailText", errorCopy(e));
  }
}
function sheet(i) {
  ++outputVersion;
  const parent = issues.find((p) => p.id === i.parentId),
    a = memberFor(i.assigneeAgentId);
  dialog(
    copy("dialog.sheet"),
    copy(a?.connection?.mode === "manual" ? "dialog.manual" : "dialog.read"),
    [
      `${ref(i)} · ${i.title}`,
      parent && copy("dialog.parent", { name: parent.title }),
      a && copy("work.ownerLine", { name: a.name }),
      i.description,
    ]
      .filter(Boolean)
      .flatMap((line, idx) => (idx ? ["\n\n", line] : [line])),
  );
}
async function action(key, fn, success) {
  if (inFlight.has(key)) return;
  inFlight.add(key);
  renderTeam();
  renderTasks();
  try {
    await fn();
    message("actionFeedback", success);
  } catch (e) {
    message("actionFeedback", errorCopy(e), true);
  } finally {
    inFlight.delete(key);
    await refresh();
  }
}
function advance(i, op) {
  const manual = memberFor(i.assigneeAgentId)?.connection?.mode === "manual";
  if (
    !confirm(
      t(op === "review" ? "work.confirmReview" : manual ? "work.confirmManual" : "work.confirmRelease"),
    )
  )
    return;
  action(
    i.id,
    () =>
      api("/api/work/advance", {
        companyId: company.id,
        issueId: i.id,
        assigneeAgentId: i.assigneeAgentId,
        action: op,
      }),
    copy(op === "review" ? "work.reviewed" : manual ? "work.started" : "work.released"),
  );
}
function renderTasks() {
  const list = $("ticketsList"),
    rows = issues.filter((i) => !$("filter").value || i.assigneeAgentId === $("filter").value);
  list.replaceChildren();
  if (!rows.length) {
    list.append(el("div", "empty", t("work.empty")));
    return;
  }
  for (const i of rows) {
    const a = memberFor(i.assigneeAgentId),
      parent = issues.find((p) => p.id === i.parentId);
    const card = el("article", "task"),
      head = el("div", "section-head"),
      title = el("h3", "", i.title);
    title.dir = "auto";
    head.append(title, status(i.status));
    card.append(
      head,
      el(
        "small",
        "",
        [
          ref(i),
          t("work.ownerLine", { name: a?.name || t("work.unassigned") }),
          i.parentId ? t("work.parentLine", { name: parent?.title || i.parentId }) : "",
        ]
          .filter(Boolean)
          .join("  ·  "),
      ),
    );
    const actions = el("div", "task-actions");
    if (i.titleWarning) card.append(el("p", "message warn", t("work.titleWarning", { id: ref(i) })));
    actions.append(btn(t("work.sheet"), () => sheet(i)));
    if (company?.boardUrl)
      actions.append(
        boardLink(
          i.titleWarning
            ? "work.editTitle"
            : i.status === "in_review"
              ? "work.boardReview"
              : "work.boardIssue",
          "issues/" + encodeURIComponent(ref(i)),
        ),
      );
    if (!pendingPlan)
      actions.append(
        btn(
          t("work.split"),
          () => {
            $("parent").value = i.id;
            syncParent();
            go("plan");
          },
          "link",
        ),
      );
    if (
      local &&
      a &&
      eligible(a) &&
      (i.status === "backlog" || (i.status === "in_progress" && a.connection?.mode === "manual"))
    ) {
      const review = i.status === "in_progress";
      const b = btn(
        t(review ? "work.toReview" : a.connection?.mode === "manual" ? "work.startManual" : "work.release"),
        () => advance(i, review ? "review" : "release"),
        "primary",
      );
      b.disabled = inFlight.has(i.id);
      actions.append(b);
    }
    card.append(actions);
    list.append(card);
  }
}
async function start() {
  try {
    await DeskLocale.load();
  } catch {
    message(
      "notice",
      "بارگذاری زبان ناموفق بود؛ صفحه را تازه کنید. / Could not load the language file. Reload the page.",
      true,
    );
    return;
  }
  document.querySelectorAll("[data-lang]").forEach(
    (b) =>
      (b.onclick = () => {
        DeskLocale.select(b.dataset.lang);
        renderMode();
        numberSteps();
        render();
        bindings.forEach((binding, id) => paint(id, binding));
      }),
  );
  document
    .querySelectorAll("[data-tab],[data-go]")
    .forEach((b) => b.addEventListener("click", () => go(b.dataset.tab || b.dataset.go)));
  $("refresh").onclick = refresh;
  $("parent").onchange = syncParent;
  $("addStep").onclick = () => addStep()?.querySelector("input").focus();
  $("template").onclick = template;
  $("discard").onclick = () => {
    if (confirm(t("msg.unlockConfirm"))) {
      unlockPlan();
      message("planFeedback", copy("msg.unlocked"));
    }
  };
  $("planForm").onsubmit = savePlan;
  $("preset").onchange = () => {
    const p = $("preset").value;
    $("memberName").value = p === "other" ? "" : p;
    $("mode").value = p === "Antigravity" ? "agent" : "manual";
    modeChanged();
  };
  $("mode").onchange = modeChanged;
  $("scan").onclick = () => scan();
  $("namespace").onchange = () => scan(false);
  $("target").onchange = updateEnroll;
  $("useManual").onclick = () => {
    $("mode").value = "manual";
    modeChanged();
  };
  $("enrollForm").onsubmit = enroll;
  $("filter").onchange = renderTasks;
  $("closeDetail").onclick = () => $("detail").close();
  $("copy").onclick = async () => {
    try {
      await navigator.clipboard.writeText($("detailText").value);
      bind("copyHint", copy("dialog.copied"));
    } catch {
      $("detailText").select();
      bind("copyHint", copy("dialog.selectCopy"));
    }
  };
  addStep();
  renderMode();
  render();
  refresh();
  setInterval(() => {
    if (!document.hidden) refresh();
  }, 5000);
}
start();
