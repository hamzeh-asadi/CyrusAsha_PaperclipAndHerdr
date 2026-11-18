"use strict";
const $ = (id) => document.getElementById(id);
const fa = (n) => Number(n).toLocaleString("fa-IR");
const names = {
  backlog: "در صف برنامه‌ریزی",
  todo: "آمادهٔ اجرا",
  in_progress: "در حال انجام",
  in_review: "در بازبینی",
  blocked: "متوقف",
  done: "پایان‌یافته",
  cancelled: "لغو",
  idle: "آزاد",
  active: "فعال",
  running: "در حال اجرا",
  pending_approval: "منتظر تأیید",
  paused: "مکث",
  terminated: "خاتمه‌یافته",
  error: "خطای اجرا",
};
let members = [],
  liveTargets = [],
  issues = [],
  company = null,
  local = false,
  online = false,
  loading = false;
let pendingPlan = null,
  teamBusy = false,
  saving = false,
  scanning = false;
const inFlight = new Set();
const eligible = (a) => ["active", "idle", "running"].includes(a.status) && a.assignable !== false;
const memberFor = (id) => members.find((a) => a.id === id);
const ref = (i) => i.identifier || i.id;
const shortMode = (a) =>
  a.connection?.mode === "manual"
    ? "تحویل دستی"
    : a.connection?.mode === "agent"
      ? `Herdr · ${a.connection.target}`
      : a.adapterType || "Paperclip";
function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text != null) node.textContent = text;
  return node;
}
function btn(text, fn, cls = "ghost") {
  const b = el("button", cls, text);
  b.type = "button";
  b.addEventListener("click", fn);
  return b;
}
function boardLink(title, path) {
  const a = el("a", "link", title + " ↗");
  a.href = company.boardUrl + "/" + path;
  a.target = "_blank";
  a.rel = "noopener noreferrer";
  return a;
}
function message(id, text, error = false) {
  const n = $(id);
  n.className = `message${error ? " warn" : ""}`;
  n.textContent = text;
  n.hidden = !text;
}
function empty(text) {
  return el("div", "empty", text);
}
function status(value) {
  return el(
    "span",
    "status " + (Object.hasOwn(names, value) ? value : ""),
    names[value] || value || "نامشخص",
  );
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
  info.append(el("b", "", a.name), el("small", "", shortMode(a)));
  row.append(av, info);
  return row;
}
// Only text nodes/Option values carry server data. No agent configuration, credentials or drafts in browser storage.
function options(select, choices, placeholder) {
  const signature = JSON.stringify([placeholder, choices]);
  if (select.dataset.options === signature) return;
  const before = select.value;
  select.replaceChildren(new Option(placeholder, ""));
  choices.forEach(([id, label]) => select.add(new Option(label, id)));
  select.value = choices.some(([id]) => id === before) ? before : "";
  select.dataset.options = signature;
}
async function api(path, data) {
  const res = await fetch(
    path,
    data === undefined
      ? { cache: "no-store" }
      : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) },
  );
  const value = await res.json();
  if (!res.ok) throw new Error(value.error || `HTTP ${res.status}`);
  return value;
}
function go(tab) {
  document.querySelectorAll("[data-page]").forEach((n) => (n.hidden = n.dataset.page !== tab));
  document.querySelectorAll("[data-tab]").forEach((n) => {
    n.classList.toggle("selected", n.dataset.tab === tab);
    if (n.dataset.tab === tab) n.setAttribute("aria-current", "page");
    else n.removeAttribute("aria-current");
  });
  if (tab === "team" && $("mode").value === "agent" && !$("target").dataset.options) scan();
}
async function refresh() {
  if (loading) return;
  loading = true;
  $("refresh").disabled = true;
  const errors = [];
  try {
    online = (await api("/health")).paperclip === true;
    if (!online) throw new Error("Paperclip آماده نیست؛ پنجرهٔ npm start را بررسی کنید.");
    const [a, t] = await Promise.allSettled([api("/api/agents"), api("/api/tickets")]);
    if (a.status === "fulfilled") {
      members = a.value.agents;
      company = a.value.company;
      local = a.value.localControl;
    } else {
      members = [];
      company = null;
      local = false;
      errors.push(a.reason.message);
    }
    if (t.status === "fulfilled") issues = t.value.tickets;
    else {
      issues = [];
      errors.push(t.reason.message);
    }
    if (company && !local)
      errors.push("حالت فقط‌خواندنی. برای مدیریت، داشبورد را روی رایانهٔ میزبان با آدرس محلی باز کنید.");
  } catch (e) {
    online = false;
    company = null;
    local = false;
    members = [];
    issues = [];
    errors.push(e.message);
  } finally {
    loading = false;
    $("refresh").disabled = false;
  }
  message("notice", [...new Set(errors)].join("\n"), true);
  render();
}
function render() {
  $("health").textContent = online ? "Paperclip آنلاین" : "Paperclip در دسترس نیست";
  $("health").classList.toggle("online", online);
  $("company").textContent = company?.name || "شرکت Paperclip";
  $("agentCount").textContent = fa(members.length);
  $("taskCount").textContent = fa(issues.length);
  $("teamPreview").replaceChildren(
    ...(members.length
      ? members.slice(0, 4).map(person)
      : [empty("اولین عضو را در «تیم ایجنت‌ها» ثبت کنید.")]),
  );
  const parentWas = $("parent").value;
  options(
    $("parent"),
    issues.map((i) => [i.id, `${ref(i)} · ${i.title}`]),
    "+ ساخت کار اصلی جدید",
  );
  if (parentWas && !$("parent").value && !pendingPlan)
    message("planFeedback", "کار انتخابی دیگر در فهرست باز نیست. کار اصلی را دوباره بررسی کنید.", true);
  syncParent();
  const choices = members.filter(eligible).map((a) => [a.id, a.name]);
  document.querySelectorAll(".assignee").forEach((s) => options(s, choices, "انتخاب مسئول…"));
  options(
    $("filter"),
    members.map((a) => [a.id, a.name]),
    "همهٔ اعضا",
  );
  $("savePlan").disabled = saving || !local || (!pendingPlan && !choices.length);
  $("enroll").disabled = teamBusy || !local;
  renderTeam();
  renderTasks();
}
function syncParent() {
  const existing = !!$("parent").value;
  $("titleLabel").hidden = existing;
  $("planTitle").required = !existing;
}
function addStep(title = "") {
  if ($("steps").children.length >= 20) return message("planFeedback", "حداکثر ۲۰ زیرکار در هر طرح.", true);
  const row = el("div", "step");
  row.innerHTML =
    '<div class="step-head"><span class="step-num"></span><button type="button" class="remove">حذف</button></div><div class="row-fields"><label>عنوان زیرکار<input class="step-title" maxlength="240" required placeholder="خروجی مشخص این مرحله" dir="auto"></label><label>ایجنت مسئول<select class="assignee" required></select></label></div><details><summary>شرح و معیار پذیرش (اختیاری)</summary><label><textarea class="step-desc" aria-label="شرح زیرکار" maxlength="3000" rows="2" dir="auto"></textarea></label></details>';
  row.querySelector(".step-title").value = title;
  options(
    row.querySelector("select"),
    members.filter(eligible).map((a) => [a.id, a.name]),
    "انتخاب مسئول…",
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
function numberSteps() {
  [...$("steps").children].forEach(
    (r, i) => (r.querySelector(".step-num").textContent = "مرحلهٔ " + fa(i + 1)),
  );
}
function template() {
  const topic = (
    $("parent").value ? issues.find((i) => i.id === $("parent").value)?.title : $("planTitle").value
  )?.trim();
  if (!topic)
    return message("planFeedback", "ابتدا عنوان کار اصلی را بنویسید یا یک کار موجود را انتخاب کنید.", true);
  const rows = [...$("steps").children];
  if (
    rows.length === 1 &&
    !rows[0].querySelector("input").value &&
    !rows[0].querySelector("select").value &&
    !rows[0].querySelector("textarea").value
  )
    rows[0].remove();
  if ($("steps").children.length > 17)
    return message("planFeedback", "برای الگوی سه‌مرحله‌ای جا نیست.", true);
  ["تعریف نیاز و معیار پذیرش", "پیاده‌سازی تغییر", "آزمون و گزارش نتیجه"].forEach((name) =>
    addStep(name + " — " + topic.slice(0, 160)),
  );
  message(
    "planFeedback",
    "این یک الگوی قابل ویرایش است. عنوان‌ها را متناسب با کار تغییر دهید و مسئول هر ردیف را انتخاب کنید.",
  );
}
function unlockPlan() {
  pendingPlan = null;
  $("planFields").disabled = false;
  $("discard").hidden = true;
  $("savePlan").textContent = "ثبت طرح در Paperclip";
}
async function savePlan(event) {
  event.preventDefault();
  if (saving || !local || !company) return;
  if (!pendingPlan) {
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
  }
  saving = true;
  $("savePlan").disabled = true;
  $("discard").hidden = true;
  $("planFields").disabled = true;
  message("planFeedback", "در حال ثبت در Paperclip…");
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
      `کار اصلی ${ref(data.parent)} و ${fa(data.children.length)} زیرکار در Paperclip ثبت شدند. هنوز هیچ کاری اجرا نشده است. `,
    );
    $("planFeedback").append(btn("دیدن کارها ←", () => go("tasks"), "link"));
  } catch (e) {
    message(
      "planFeedback",
      e.message + "\nتلاش مجدد همین درخواست را ادامه می‌دهد. پیش از تغییر طرح، کارهای ثبت‌شده را بررسی کنید.",
      true,
    );
    $("discard").hidden = false;
    $("savePlan").textContent = "تلاش مجدد همین طرح";
  } finally {
    saving = false;
    $("savePlan").disabled = !local;
    await refresh();
  }
}
function modeChanged() {
  const live = $("mode").value === "agent";
  $("targetFields").hidden = !live;
  $("target").required = live;
  $("modeHint").textContent = live
    ? "ایجنت را داخل Herdr اجرا کنید (برای Antigravity، دستور agy). فقط نشست شناخته‌شده را انتخاب کنید؛ میز کار برنامه‌ای نصب یا اجرا نمی‌کند."
    : "برای Freebuff یا هر ابزار دیگر: آن را در پنجرهٔ خودش در Herdr باز کنید و برگهٔ کار را آنجا بچسبانید. میز کار هیچ کلیدی به پنجره نمی‌فرستد.";
  if (live && local) scan();
}
async function scan() {
  if (scanning || !local) return;
  scanning = true;
  $("scan").disabled = true;
  $("targetHint").textContent = "در حال خواندن نشست‌ها…";
  try {
    const { targets } = await api("/api/herdr/targets");
    liveTargets = targets;
    options(
      $("target"),
      targets.map((t) => [t.target, `${t.target} · ${t.kind || "Herdr"} · ${names[t.status] || t.status}`]),
      "انتخاب نشست…",
    );
    $("targetHint").textContent = targets.length
      ? "نشست متعلق به همین عضو را انتخاب کنید."
      : "نشست شناخته‌شده‌ای پیدا نشد. بعد از اجرای CLI دوباره جست‌وجو کنید یا تحویل دستی را برگزینید.";
  } catch (e) {
    liveTargets = [];
    options($("target"), [], "بدون نشست");
    $("targetHint").textContent = e.message;
  } finally {
    scanning = false;
    $("scan").disabled = false;
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
    const selected = liveTargets.find((t) => t.target === data.target);
    if (!selected) return message("enrollFeedback", "نشست زنده را دوباره انتخاب کنید.", true);
    data.kind = selected.kind;
    data.terminal = selected.terminal;
  }
  teamBusy = true;
  $("enrollFields").disabled = true;
  message("enrollFeedback", "در حال ثبت عضو…");
  try {
    const r = await api("/api/team/enroll", data);
    message(
      "enrollFeedback",
      `${r.agent.name}: ${r.existing ? "از قبل عضو همین شرکت است." : "در Paperclip ثبت شد."} ` +
        (r.needsApproval || r.agent.status === "pending_approval"
          ? "در Paperclip، بخش Approvals، استخدام را تأیید کنید؛ سپس می‌توانید کار واگذار کنید."
          : "وقتی وضعیت عضو فعال یا آزاد شد، در میز تقسیم کار قابل انتخاب است."),
    );
  } catch (e) {
    message("enrollFeedback", e.message, true);
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
    grid.append(empty("هنوز عضوی در دسترس نیست. بعد از ثبت، نام و وضعیت تأیید اینجا نمایش داده می‌شود."));
    return;
  }
  for (const a of members) {
    const card = el("article", "member"),
      head = el("div", "section-head");
    head.append(person(a), status(a.status));
    card.append(head);
    if (a.status === "pending_approval")
      card.append(el("small", "", "در انتظار تأیید استخدام در Paperclip ← Approvals"));
    const actions = el("div", "task-actions");
    actions.append(
      btn("کارهای این عضو", () => {
        $("filter").value = a.id;
        renderTasks();
        go("tasks");
      }),
    );
    if (company?.boardUrl)
      actions.append(
        a.status === "pending_approval"
          ? boardLink("تأیید استخدام", "approvals/pending")
          : boardLink("عضو در Paperclip", "agents/" + encodeURIComponent(a.id)),
      );
    if (a.connection?.mode !== "manual" && local) {
      const wake = btn("بیدارباش", async () => {
        if (!confirm(`برای ${a.name} در Paperclip درخواست اجرا ارسال شود؟`)) return;
        await action(
          "wake:" + a.id,
          () => api(`/api/agents/${encodeURIComponent(a.id)}/heartbeat/invoke`, {}),
          "درخواست بیدارباش به Paperclip ارسال شد.",
        );
      });
      wake.disabled = !eligible(a) || inFlight.has("wake:" + a.id);
      actions.append(
        wake,
        btn("خروجی Herdr", () => showOutput(a)),
      );
    }
    card.append(actions);
    grid.append(card);
  }
}
function dialog(title, hint, value) {
  $("detailTitle").textContent = title;
  $("detailHint").textContent = hint;
  $("detailText").value = value;
  $("copyHint").textContent = "";
  if (!$("detail").open) $("detail").showModal();
}
async function showOutput(a) {
  dialog(a.name, "خروجی اخیر Herdr", "در حال خواندن…");
  const req = ++outputVersion;
  try {
    const r = await api(`/api/agents/${encodeURIComponent(a.id)}/output`);
    if (req === outputVersion)
      $("detailText").value = r.success ? r.output || "خروجی خالی" : r.error || "خروجی در دسترس نیست.";
  } catch (e) {
    if (req === outputVersion) $("detailText").value = e.message;
  }
}
let outputVersion = 0;
function sheet(i) {
  ++outputVersion;
  const parent = issues.find((p) => p.id === i.parentId),
    a = memberFor(i.assigneeAgentId);
  dialog(
    "برگهٔ تحویل کار",
    a?.connection?.mode === "manual"
      ? "متن را کپی کنید و در خودِ برنامهٔ ایجنت (نه خط فرمان شل) بچسبانید."
      : "متن این تیکت برای بررسی یا تحویل دستی:",
    [
      `${ref(i)} · ${i.title}`,
      parent ? "کار اصلی: " + parent.title : "",
      a ? "مسئول: " + a.name : "",
      i.description || "",
    ]
      .filter(Boolean)
      .join("\n\n"),
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
    message("actionFeedback", e.message, true);
  } finally {
    inFlight.delete(key);
    await refresh();
  }
}
function advance(i, op) {
  const manual = memberFor(i.assigneeAgentId)?.connection?.mode === "manual";
  const prompt =
    op === "review"
      ? "این کار دستی آمادهٔ بازبینی است؟"
      : manual
        ? "این کار را دستی شروع می‌کنید؟ متنی به ترمینال ارسال نمی‌شود."
        : "این کار از Backlog وارد Todo شود؟ Paperclip ممکن است ایجنت مسئول را اجرا کند.";
  if (!confirm(prompt)) return;
  action(
    i.id,
    () =>
      api("/api/work/advance", {
        companyId: company.id,
        issueId: i.id,
        assigneeAgentId: i.assigneeAgentId,
        action: op,
      }),
    op === "review"
      ? "درخواست بازبینی انسانی روی تیکت ثبت شد. از «بازبینی در Paperclip» نتیجه را بررسی کنید."
      : manual
        ? "کار دستی شروع شد؛ برگهٔ کار را کپی کنید."
        : "کار به صف اجرای مسئول رفت. وضعیت واقعی را در Paperclip پیگیری کنید.",
  );
}
function renderTasks() {
  const list = $("ticketsList"),
    rows = issues.filter((i) => !$("filter").value || i.assigneeAgentId === $("filter").value);
  list.replaceChildren();
  if (!rows.length) {
    list.append(empty("در این نما کار بازی وجود ندارد."));
    return;
  }
  for (const i of rows) {
    const a = memberFor(i.assigneeAgentId),
      parent = issues.find((p) => p.id === i.parentId);
    const card = el("article", "task"),
      head = el("div", "section-head");
    head.append(el("h3", "", i.title), status(i.status));
    card.append(
      head,
      el(
        "small",
        "",
        `${ref(i)}  ·  مسئول: ${a?.name || "واگذار نشده"}${i.parentId ? "  ·  کار مادر: " + (parent?.title || i.parentId) : ""}`,
      ),
    );
    const actions = el("div", "task-actions");
    actions.append(btn("برگهٔ کار", () => sheet(i)));
    if (company?.boardUrl)
      actions.append(
        boardLink(
          i.status === "in_review" ? "بازبینی در Paperclip" : "تیکت در Paperclip",
          "issues/" + encodeURIComponent(ref(i)),
        ),
      );
    if (!pendingPlan)
      actions.append(
        btn(
          "تقسیم این کار",
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
        review ? "آمادهٔ بازبینی" : a.connection?.mode === "manual" ? "شروع دستی" : "ارسال به صف اجرا",
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

document
  .querySelectorAll("[data-tab],[data-go]")
  .forEach((b) => b.addEventListener("click", () => go(b.dataset.tab || b.dataset.go)));
$("refresh").onclick = refresh;
$("parent").onchange = syncParent;
$("addStep").onclick = () => addStep()?.querySelector("input").focus();
$("template").onclick = template;
$("discard").onclick = () => {
  if (confirm("ممکن است بعضی ردیف‌ها ثبت شده باشند. قبل از ارسال یک طرح جدید، آن‌ها را بررسی کرده‌اید؟")) {
    unlockPlan();
    message("planFeedback", "فرم آزاد شد. برای ادامهٔ یک کار ثبت‌شده، آن را به عنوان کار اصلی انتخاب کنید.");
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
$("scan").onclick = scan;
$("enrollForm").onsubmit = enroll;
$("filter").onchange = renderTasks;
$("closeDetail").onclick = () => $("detail").close();
$("copy").onclick = async () => {
  try {
    await navigator.clipboard.writeText($("detailText").value);
    $("copyHint").textContent = "کپی شد.";
  } catch {
    $("detailText").select();
    $("copyHint").textContent = "متن انتخاب شد؛ Ctrl+C را بزنید.";
  }
};
addStep();
modeChanged();
refresh();
setInterval(() => {
  if (!document.hidden) refresh();
}, 5000);
