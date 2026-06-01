const state = {
  tasks: [],
  selectedTask: null,
  session: null,
  llmConfig: null,
  runtimeMode: "rule",
  sending: false,
  evaluating: false,
};

const els = {
  taskList: document.querySelector("#taskList"),
  taskCount: document.querySelector("#taskCount"),
  variableForm: document.querySelector("#variableForm"),
  startBtn: document.querySelector("#startBtn"),
  taskTitle: document.querySelector("#taskTitle"),
  taskSubTitle: document.querySelector("#taskSubTitle"),
  sessionStatus: document.querySelector("#sessionStatus"),
  callMeta: document.querySelector("#callMeta"),
  messages: document.querySelector("#messages"),
  composerArea: document.querySelector("#composerArea"),
  quickReplies: document.querySelector("#quickReplies"),
  messageForm: document.querySelector("#messageForm"),
  messageInput: document.querySelector("#messageInput"),
  sendBtn: document.querySelector("#sendBtn"),
  exportBtn: document.querySelector("#exportBtn"),
  runEvalBtn: document.querySelector("#runEvalBtn"),
  evaluationBoard: document.querySelector("#evaluationBoard"),
  evaluationConclusion: document.querySelector("#evaluationConclusion"),
  evaluationScore: document.querySelector("#evaluationScore"),
  dimensionList: document.querySelector("#dimensionList"),
  scenarioList: document.querySelector("#scenarioList"),
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || "请求失败");
  }
  return data;
}

function mode() {
  return state.runtimeMode;
}

function valuesFromForm() {
  const data = {};
  new FormData(els.variableForm).forEach((value, key) => {
    data[key] = String(value).trim();
  });
  return data;
}

function configureRuntime() {
  state.runtimeMode = state.llmConfig?.configured ? "llm" : "rule";
}

function renderTaskList() {
  els.taskList.innerHTML = "";
  els.taskCount.textContent = `${state.tasks.length} 个`;
  state.tasks.forEach((task) => {
    const button = document.createElement("button");
    button.className = `task-card ${state.selectedTask?.id === task.id ? "active" : ""}`;
    button.type = "button";
    button.innerHTML = `
      <strong>${escapeHtml(task.title)}</strong>
      <span>${escapeHtml(task.response_limit)}</span>
    `;
    button.addEventListener("click", () => selectTask(task.id));
    els.taskList.appendChild(button);
  });
}

async function selectTask(taskId) {
  const task = await api(`/api/tasks/${encodeURIComponent(taskId)}`);
  state.selectedTask = task;
  state.session = null;
  state.sending = false;
  renderTaskList();
  renderTaskDetail();
  renderSession();
}

function renderTaskDetail() {
  const task = state.selectedTask;
  if (!task) return;
  els.taskTitle.textContent = task.title;
  els.taskSubTitle.textContent = task.task;
  els.variableForm.innerHTML = task.variables
    .map(
      (item) => `
        <label>
          <span>${escapeHtml(item.label)}</span>
          <input name="${escapeHtml(item.key)}" value="${escapeHtml(item.default)}" placeholder="${escapeHtml(item.placeholder)}" />
        </label>
      `,
    )
    .join("");
  renderQuickReplies(task.quick_replies || []);
}

function renderQuickReplies(items) {
  els.quickReplies.innerHTML = "";
  items.forEach((item) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = item;
    button.addEventListener("click", () => sendMessage(item));
    els.quickReplies.appendChild(button);
  });
  updateComposerState();
}

function updateComposerState() {
  const locked = !state.session || state.session.ended || state.sending;
  els.composerArea.hidden = !state.session;
  els.startBtn.disabled = state.sending || !state.selectedTask;
  els.runEvalBtn.disabled = state.evaluating || !state.selectedTask;
  els.messageInput.disabled = locked;
  els.sendBtn.disabled = locked;
  els.quickReplies.querySelectorAll("button").forEach((button) => {
    button.disabled = locked;
  });
}

function updateSessionHeader() {
  const session = state.session;
  if (!session) return;
  els.sessionStatus.textContent = session.status || "进行中";
  els.callMeta.textContent = session.ended ? "已结束" : "进行中";
}

function renderSession() {
  const session = state.session;
  els.messages.innerHTML = "";
  if (!session) {
    els.sessionStatus.textContent = "未开始";
    els.callMeta.textContent = "待开始";
    els.exportBtn.disabled = true;
    updateComposerState();
    return;
  }
  updateSessionHeader();
  session.messages.forEach((message) => appendMessage(message));
  els.exportBtn.disabled = false;
  updateComposerState();
  if (!session.ended && !state.sending) {
    els.messageInput.focus();
  }
}

function appendMessage(message) {
  const item = document.createElement("div");
  item.className = `message ${message.role}`;
  if (message.pending) item.classList.add("pending");
  if (message.error) item.classList.add("error");

  const label = document.createElement("span");
  label.textContent = message.role === "assistant" ? "坐席" : "对方";
  const body = document.createElement("p");
  body.textContent = message.content;

  item.appendChild(label);
  item.appendChild(body);
  els.messages.appendChild(item);
  els.messages.scrollTop = els.messages.scrollHeight;
  return item;
}

function setBubbleText(item, content) {
  const body = item.querySelector("p");
  if (body) body.textContent = content;
  els.messages.scrollTop = els.messages.scrollHeight;
}

async function typeAssistantReply(item, content) {
  item.classList.remove("pending");
  setBubbleText(item, "");
  const chars = Array.from(content);
  for (let i = 0; i < chars.length; i += 1) {
    setBubbleText(item, chars.slice(0, i + 1).join(""));
    await delay(i < 12 ? 24 : 10);
  }
}

function delay(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

async function startSession() {
  if (!state.selectedTask || state.sending) return;
  state.sending = true;
  updateComposerState();
  try {
    const session = await api("/api/sessions", {
      method: "POST",
      body: JSON.stringify({
        task_id: state.selectedTask.id,
        mode: mode(),
        variables: valuesFromForm(),
      }),
    });
    state.session = session;
    renderSession();
  } finally {
    state.sending = false;
    updateComposerState();
  }
}

async function sendMessage(content) {
  if (!state.session || state.session.ended || state.sending) return;
  const text = String(content || els.messageInput.value).trim();
  if (!text) return;

  const activeSessionKey = state.session.id;
  els.messageInput.value = "";
  state.sending = true;
  updateComposerState();

  appendMessage({ role: "user", content: text });
  const pendingBubble = appendMessage({ role: "assistant", content: "回复中", pending: true });
  els.sessionStatus.textContent = "坐席回复中";
  els.callMeta.textContent = "处理中";

  try {
    const data = await api(`/api/sessions/${activeSessionKey}/messages`, {
      method: "POST",
      body: JSON.stringify({ content: text }),
    });
    state.session = data.session;
    updateSessionHeader();
    await typeAssistantReply(pendingBubble, data.reply.content);
  } catch (error) {
    pendingBubble.classList.remove("pending");
    pendingBubble.classList.add("error");
    setBubbleText(pendingBubble, `回复失败：${error.message}`);
    els.sessionStatus.textContent = "回复失败";
    els.callMeta.textContent = "异常";
  } finally {
    state.sending = false;
    updateComposerState();
    if (state.session && !state.session.ended) {
      els.messageInput.focus();
    }
  }
}

function exportTranscript() {
  if (!state.session || !state.selectedTask) return;
  const rows = [
    `任务：${state.selectedTask.title}`,
    "",
    ...state.session.messages.map((item) => {
      const role = item.role === "assistant" ? "坐席" : "对方";
      return `${role}：${item.content}`;
    }),
  ];
  const blob = new Blob([rows.join("\n")], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  const stamp = new Date().toISOString().slice(0, 19).replaceAll(":", "-");
  link.href = url;
  link.download = `${state.selectedTask.id}-${stamp}.txt`;
  link.click();
  URL.revokeObjectURL(url);
}

async function runEvaluation() {
  if (!state.selectedTask || state.evaluating) return;
  state.evaluating = true;
  els.runEvalBtn.textContent = "评测中...";
  updateComposerState();
  try {
    const report = await api("/api/evaluations/run", {
      method: "POST",
      body: JSON.stringify({
        task_id: state.selectedTask.id,
        mode: mode(),
        variables: valuesFromForm(),
      }),
    });
    renderEvaluation(report);
  } catch (error) {
    els.evaluationBoard.hidden = false;
    els.evaluationScore.textContent = "-";
    els.evaluationConclusion.textContent = `评测失败：${error.message}`;
    els.dimensionList.innerHTML = "";
    els.scenarioList.innerHTML = "";
  } finally {
    state.evaluating = false;
    els.runEvalBtn.textContent = "运行评测";
    updateComposerState();
  }
}

function renderEvaluation(report) {
  const summary = report.summary || {};
  const taskReports = report.task_reports || [];
  const taskReport = taskReports[0] || {};
  els.evaluationBoard.hidden = false;
  els.evaluationScore.textContent =
    typeof summary.score === "number" ? `${summary.score}` : "-";
  els.evaluationConclusion.textContent = summary.conclusion || "评测完成";

  els.dimensionList.innerHTML = (taskReport.dimensions || [])
    .map(
      (item) => `
        <article class="dimension-item">
          <span>${escapeHtml(item.name)}</span>
          <strong>${escapeHtml(item.score)}</strong>
          <small>${escapeHtml(item.passed_count)} / ${escapeHtml(item.check_count)}</small>
        </article>
      `,
    )
    .join("");

  els.scenarioList.innerHTML = (taskReport.scenarios || [])
    .map((scenario) => renderScenario(scenario))
    .join("");
}

function renderScenario(scenario) {
  const failedChecks = (scenario.checks || []).filter((item) => !item.passed);
  const evidence = (scenario.evidence || [])
    .map(
      (item) => `
        <li>
          <span>用户：${escapeHtml(item.user)}</span>
          <strong>坐席：${escapeHtml(item.assistant)}</strong>
          <em>意图：${escapeHtml(item.intent || "-")}</em>
        </li>
      `,
    )
    .join("");
  const failures = failedChecks.length
    ? `
      <div class="failed-checks">
        ${failedChecks
          .map(
            (item) => `
              <p>${escapeHtml(item.dimension)} / ${escapeHtml(item.name)}：${escapeHtml(item.evidence)}</p>
            `,
          )
          .join("")}
      </div>
    `
    : `<p class="scenario-ok">所有检查通过</p>`;
  return `
    <article class="scenario-card">
      <div class="scenario-head">
        <div>
          <h4>${escapeHtml(scenario.title)}</h4>
          <p>${escapeHtml(scenario.description)}</p>
        </div>
        <strong>${escapeHtml(scenario.score)}</strong>
      </div>
      ${failures}
      <details>
        <summary>查看模拟过程</summary>
        <ol>${evidence}</ol>
      </details>
    </article>
  `;
}

async function boot() {
  const [tasks, llmConfig] = await Promise.all([
    api("/api/tasks"),
    api("/api/llm/config"),
  ]);
  state.tasks = tasks;
  state.llmConfig = llmConfig;
  configureRuntime();
  renderTaskList();
  if (state.tasks[0]) {
    await selectTask(state.tasks[0].id);
  }
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

els.startBtn.addEventListener("click", startSession);
els.messageForm.addEventListener("submit", (event) => {
  event.preventDefault();
  sendMessage();
});
els.exportBtn.addEventListener("click", exportTranscript);
els.runEvalBtn.addEventListener("click", runEvaluation);

boot().catch((error) => {
  els.sessionStatus.textContent = error.message;
});
