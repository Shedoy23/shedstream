const state = {
  selectedTask: null,
  tasks: [],
  loading: false,
  lastMessageId: null,
  lastActivityId: null,
};

const elements = {
  taskList: document.querySelector("#task-list"),
  taskCount: document.querySelector("#task-count"),
  title: document.querySelector("#task-title"),
  status: document.querySelector("#agent-status"),
  welcome: document.querySelector("#welcome"),
  messages: document.querySelector("#messages"),
  taskName: document.querySelector("#task-name"),
  taskRequest: document.querySelector("#task-request"),
  maxRounds: document.querySelector("#max-rounds"),
  taskMode: document.querySelector("#task-mode"),
  modeHint: document.querySelector("#mode-hint"),
  send: document.querySelector("#send-task"),
  newTask: document.querySelector("#new-task-button"),
  error: document.querySelector("#error-message"),
  close: document.querySelector("#close-task"),
  conversation: document.querySelector("#conversation"),
  claudeModel: document.querySelector("#claude-model"),
  codexModel: document.querySelector("#codex-model"),
  codexLimits: document.querySelector("#codex-limits"),
  claudeLimits: document.querySelector("#claude-limits"),
  refreshLimits: document.querySelector("#refresh-limits"),
};

const labels = {
  owner: "Ты",
  claude: "Claude",
  codex: "Codex",
  system: "Оркестратор",
  request: "задача",
  implementation: "реализация",
  analysis: "анализ",
  review: "ревью",
  ready: "готово",
  blocked: "нужно решение",
};

function setError(message = "") {
  elements.error.textContent = message;
  elements.error.classList.toggle("hidden", !message);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  const payload = await response.json();
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.error || "Не удалось выполнить действие.");
  }
  return payload;
}

function formatTime(value) {
  if (!value) return "";
  const date = new Date(value);
  return new Intl.DateTimeFormat("ru-RU", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function taskTone(task) {
  if (task.run?.running) return "running";
  if (task.status === "blocked" || task.run?.error) return "blocked";
  if (task.current_owner === "owner" && task.status === "open") return "ready";
  return "";
}

function taskSubtitle(task) {
  if (task.run?.running) {
    const phase = task.run.phase;
    if (phase === "claude") return "Claude работает";
    if (phase === "codex") return "Codex проверяет";
    return "Запускается";
  }
  if (task.run?.error) return "Ошибка — открой задачу";
  if (task.status === "closed") return "Закрыта";
  if (task.current_owner === "owner") return "Ждёт тебя";
  return `Ход: ${labels[task.current_owner] || task.current_owner}`;
}

function renderTaskList() {
  elements.taskList.replaceChildren();
  elements.taskCount.textContent = String(state.tasks.length);
  for (const task of state.tasks) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `task-item${task.id === state.selectedTask ? " active" : ""}`;

    const dot = document.createElement("span");
    dot.className = `task-dot ${taskTone(task)}`;

    const copy = document.createElement("span");
    copy.className = "task-copy";
    const title = document.createElement("strong");
    title.textContent = task.title;
    const subtitle = document.createElement("span");
    subtitle.textContent = taskSubtitle(task);
    copy.append(title, subtitle);
    button.append(dot, copy);
    button.addEventListener("click", () => selectTask(task.id));
    elements.taskList.append(button);
  }
}

function setAgentStatus(task) {
  elements.status.className = "agent-status";
  const copy = elements.status.querySelector("span:last-child");
  if (!task) {
    copy.textContent = "Готовы к работе";
    return;
  }
  if (task.run?.error) {
    elements.status.classList.add("error");
    copy.textContent = "Нужна помощь";
    return;
  }
  if (task.run?.running) {
    elements.status.classList.add("working");
    copy.textContent =
      task.run.phase === "codex" ? "Codex проверяет" : "Claude работает";
    return;
  }
  if (task.status === "closed") {
    copy.textContent = "Задача закрыта";
  } else if (task.current_owner === "owner") {
    copy.textContent = "Отчёт готов";
  } else {
    copy.textContent = "Готово к продолжению";
  }
}

function makeMessage(message, task) {
  const article = document.createElement("article");
  article.className = `message ${message.sender}`;

  const avatar = document.createElement("div");
  avatar.className = "message-avatar";
  avatar.textContent =
    message.sender === "owner" ? "Я" : message.sender === "claude" ? "C" : "X";

  const main = document.createElement("div");
  main.className = "message-main";

  const meta = document.createElement("div");
  meta.className = "message-meta";
  const author = document.createElement("strong");
  author.textContent = labels[message.sender] || message.sender;
  const kind = document.createElement("span");
  kind.className = "kind";
  kind.textContent = labels[message.kind] || message.kind;
  const model = document.createElement("span");
  model.className = "model-badge";
  model.textContent =
    message.sender === "claude"
      ? task.claude_model || "default"
      : message.sender === "codex"
        ? task.codex_model || "default"
        : "";
  const time = document.createElement("span");
  time.textContent = formatTime(message.created_at);
  meta.append(author, kind);
  if (model.textContent) meta.append(model);
  meta.append(time);

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = message.body;

  main.append(meta, bubble);
  if (message.evidence?.length) {
    const evidence = document.createElement("div");
    evidence.className = "evidence";
    for (const path of message.evidence) {
      const item = document.createElement("span");
      item.textContent = path;
      evidence.append(item);
    }
    main.append(evidence);
  }

  article.append(avatar, main);
  return article;
}

function makeActivityFeed(task) {
  const activity = task.run?.activity || [];
  if (!activity.length) return null;

  const section = document.createElement("section");
  section.className = `activity-feed${task.run?.running ? " live" : ""}`;

  const heading = document.createElement("div");
  heading.className = "activity-heading";
  const pulse = document.createElement("span");
  pulse.className = "activity-pulse";
  const title = document.createElement("strong");
  title.textContent = task.run?.running ? "Сейчас происходит" : "Ход последнего запуска";
  heading.append(pulse, title);
  section.append(heading);

  const list = document.createElement("div");
  list.className = "activity-list";
  for (const event of activity.slice(-12)) {
    const row = document.createElement("div");
    row.className = `activity-row ${event.kind || "status"}`;

    const marker = document.createElement("span");
    marker.className = "activity-marker";

    const copy = document.createElement("div");
    const meta = document.createElement("span");
    meta.className = "activity-meta";
    meta.textContent = `${labels[event.agent] || event.agent} · ${formatTime(event.created_at)}`;
    const message = document.createElement("strong");
    message.textContent = event.message;
    copy.append(meta, message);
    if (event.detail) {
      const detail = document.createElement("code");
      detail.textContent = event.detail;
      copy.append(detail);
    }
    row.append(marker, copy);
    list.append(row);
  }
  section.append(list);
  return section;
}

function renderConversation(task) {
  elements.welcome.classList.toggle("hidden", Boolean(task));
  elements.messages.classList.toggle("hidden", !task);
  elements.close.classList.toggle(
    "hidden",
    !task || task.status === "closed" || task.current_owner !== "owner",
  );
  if (!task) {
    elements.title.textContent = "Новая задача";
    setAgentStatus(null);
    return;
  }

  elements.title.textContent = task.title;
  setAgentStatus(task);
  elements.messages.replaceChildren();
  for (const message of task.messages) {
    elements.messages.append(makeMessage(message, task));
  }

  if (task.run?.running) {
    const typing = document.createElement("div");
    typing.className = "typing";
    typing.setAttribute("aria-label", "Агент работает");
    typing.innerHTML = "<i></i><i></i><i></i>";
    elements.messages.append(typing);
  }

  const activityFeed = makeActivityFeed(task);
  if (activityFeed) {
    elements.messages.append(activityFeed);
  }

  const finalMessage = task.messages.at(-1);
  if (
    task.current_owner === "owner" &&
    finalMessage &&
    ["ready", "blocked"].includes(finalMessage.kind)
  ) {
    const card = document.createElement("div");
    card.className = `final-card ${finalMessage.kind === "blocked" ? "blocked" : ""}`;
    const title = document.createElement("strong");
    title.textContent =
      finalMessage.kind === "ready"
        ? "Готово к твоему решению"
        : "Нужно твоё решение";
    const copy = document.createElement("span");
    copy.textContent =
      finalMessage.kind === "ready"
        ? task.mode === "analysis"
          ? "Два независимых анализа завершены. Можно изучить отчёты и закрыть задачу."
          : `Проверок Codex: ${task.reviews}. Можно изучить отчёт и закрыть задачу.`
        : "Автоматический цикл остановлен безопасно.";
    card.append(title, copy);
    elements.messages.append(card);
  }

  if (task.run?.error) {
    const card = document.createElement("div");
    card.className = "final-card blocked";
    const title = document.createElement("strong");
    title.textContent = "Цикл остановлен";
    const copy = document.createElement("span");
    copy.textContent = task.run.error;
    card.append(title, copy);
    elements.messages.append(card);
  }

  const newest = task.messages.at(-1)?.id || 0;
  const newestActivity = task.run?.activity?.at(-1)?.id || 0;
  if (
    newest !== state.lastMessageId ||
    newestActivity !== state.lastActivityId
  ) {
    state.lastMessageId = newest;
    state.lastActivityId = newestActivity;
    requestAnimationFrame(() => {
      elements.conversation.scrollTop = elements.conversation.scrollHeight;
    });
  }
}

async function refresh() {
  try {
    const query = state.selectedTask
      ? `?task=${encodeURIComponent(state.selectedTask)}`
      : "";
    const payload = await api(`/api/state${query}`);
    state.tasks = payload.tasks;
    if (
      state.selectedTask &&
      !state.tasks.some((task) => task.id === state.selectedTask)
    ) {
      state.selectedTask = null;
    }
    renderTaskList();
    renderConversation(payload.task || null);
  } catch (error) {
    setError(error.message);
  }
}

async function selectTask(taskId) {
  state.selectedTask = taskId;
  state.lastMessageId = null;
  state.lastActivityId = null;
  setError();
  await refresh();
}

function newTask() {
  state.selectedTask = null;
  state.lastMessageId = null;
  state.lastActivityId = null;
  elements.taskName.value = "";
  elements.taskRequest.value = "";
  elements.title.textContent = "Новая задача";
  renderTaskList();
  renderConversation(null);
  elements.taskRequest.focus();
}

function populateModels(control, models) {
  const previous = control.value;
  if (control instanceof HTMLInputElement) {
    const listId = control.getAttribute("list");
    const list = listId ? document.querySelector(`#${listId}`) : null;
    if (!list) return;
    list.replaceChildren();
    for (const model of models || []) {
      if (!model.id) continue;
      const option = document.createElement("option");
      option.value = model.id;
      option.label = model.display_name;
      list.append(option);
    }
    control.value = previous;
    return;
  }

  control.replaceChildren();
  const defaultOption = document.createElement("option");
  defaultOption.value = "";
  defaultOption.textContent = "По умолчанию";
  control.append(defaultOption);
  for (const model of models || []) {
    if (!model.id) continue;
    const option = document.createElement("option");
    option.value = model.id;
    option.textContent = `${model.display_name}${model.is_default ? " · default" : ""}`;
    control.append(option);
  }
  if ([...control.options].some((option) => option.value === previous)) {
    control.value = previous;
  }
}

function limitLabel(minutes) {
  if (!minutes) return "окно";
  if (minutes >= 7 * 24 * 60) return "Неделя";
  if (minutes >= 4 * 60) return `${Math.round(minutes / 60)} часов`;
  return `${minutes} минут`;
}

function resetLabel(timestamp) {
  if (!timestamp) return "";
  const date = new Date(timestamp * 1000);
  return `до ${new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date)}`;
}

function renderLimits(payload) {
  elements.codexLimits.replaceChildren();
  const codex = payload.limits.codex;
  if (!codex.available) {
    elements.codexLimits.textContent = "CLI пока не отдал данные";
  } else {
    for (const window of codex.windows) {
      const row = document.createElement("div");
      row.className = "usage-window";
      const meta = document.createElement("div");
      meta.className = "usage-window-meta";
      const name = document.createElement("span");
      name.textContent = limitLabel(window.window_minutes);
      const value = document.createElement("span");
      value.textContent = `${window.remaining_percent ?? "—"}% · ${resetLabel(window.resets_at)}`;
      meta.append(name, value);
      const track = document.createElement("div");
      track.className = "usage-track";
      const fill = document.createElement("i");
      fill.style.width = `${Math.max(0, Math.min(100, window.remaining_percent ?? 0))}%`;
      track.append(fill);
      row.append(meta, track);
      elements.codexLimits.append(row);
    }
  }

  elements.claudeLimits.replaceChildren();
  const claude = payload.limits.claude;
  const copy = document.createElement("span");
  copy.textContent = "Точный остаток: ";
  const link = document.createElement("a");
  link.href = claude.url;
  link.target = "_blank";
  link.rel = "noreferrer";
  link.textContent = "Settings → Usage";
  elements.claudeLimits.append(copy, link);
}

async function refreshCapabilities(force = false) {
  try {
    const payload = await api(
      `/api/capabilities${force ? "?refresh=1" : ""}`,
    );
    populateModels(elements.claudeModel, payload.models.claude);
    populateModels(elements.codexModel, payload.models.codex);
    renderLimits(payload);
  } catch (error) {
    elements.codexLimits.textContent = "Не удалось обновить";
    elements.claudeLimits.textContent = "Не удалось обновить";
  }
}

async function sendTask() {
  if (state.loading) return;
  const request = elements.taskRequest.value.trim();
  const title = elements.taskName.value.trim();
  if (!request) {
    setError("Опиши задачу перед запуском.");
    elements.taskRequest.focus();
    return;
  }
  state.loading = true;
  elements.send.disabled = true;
  setError();
  try {
    const payload = await api("/api/tasks", {
      method: "POST",
      body: JSON.stringify({
        title,
        request,
        mode: elements.taskMode.value,
        max_rounds: Number(elements.maxRounds.value),
        claude_model: elements.claudeModel.value,
        codex_model: elements.codexModel.value,
      }),
    });
    elements.taskName.value = "";
    elements.taskRequest.value = "";
    await selectTask(payload.task_id);
  } catch (error) {
    setError(error.message);
  } finally {
    state.loading = false;
    elements.send.disabled = false;
  }
}

async function closeTask() {
  if (!state.selectedTask) return;
  try {
    await api(`/api/tasks/${encodeURIComponent(state.selectedTask)}/close`, {
      method: "POST",
      body: "{}",
    });
    await refresh();
  } catch (error) {
    setError(error.message);
  }
}

elements.send.addEventListener("click", sendTask);
elements.newTask.addEventListener("click", newTask);
elements.close.addEventListener("click", closeTask);
elements.refreshLimits.addEventListener("click", () => refreshCapabilities(true));
elements.taskMode.addEventListener("change", () => {
  const mode = elements.taskMode.value;
  elements.maxRounds.disabled = mode === "analysis";
  elements.modeHint.textContent = {
    auto: "Приложение определит права до запуска; сомнение означает read-only.",
    analysis:
      "Claude и Codex анализируют независимо. Запись файлов запрещена обоим.",
    delivery: "Claude реализует, затем Codex независимо проверяет.",
  }[mode];
});
elements.taskRequest.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
    event.preventDefault();
    sendTask();
  }
});

refresh();
refreshCapabilities();
setInterval(refresh, 1500);
setInterval(refreshCapabilities, 60000);
