let skillsByLabel = new Map();
let agentsByLabel = new Map();
let currentFiles = {};
let activeSessionId = null;

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

function resolveDatalistValue(inputValue, labelMap) {
  if (!inputValue) return null;
  return labelMap.has(inputValue) ? labelMap.get(inputValue) : inputValue;
}

async function loadSkills() {
  const response = await fetch("/skills");
  const skills = await response.json();
  const datalist = document.getElementById("skill-options");
  for (const skill of skills) {
    const label = skill.description ? `${skill.name} — ${skill.description}` : skill.name;
    skillsByLabel.set(label, skill.name);
    const option = document.createElement("option");
    option.value = label;
    datalist.appendChild(option);
  }
}

async function loadAgents() {
  const response = await fetch("/agents");
  const agents = await response.json();
  const datalist = document.getElementById("agent-options");
  for (const agent of agents) {
    const label = `${agent.name} [${agent.role}]`;
    agentsByLabel.set(label, agent.name);
    const option = document.createElement("option");
    option.value = label;
    datalist.appendChild(option);
  }
}

function switchTab(name) {
  document.querySelectorAll(".tab-btn").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  document.querySelectorAll(".tab-panel").forEach((panel) => panel.classList.toggle("active", panel.id === `tab-${name}`));
}

function initTabs() {
  document.querySelectorAll(".tab-btn").forEach((button) => {
    button.addEventListener("click", () => switchTab(button.dataset.tab));
  });
}

function clearActivityLog() {
  document.getElementById("activity-log").innerHTML = "";
  document.getElementById("stream-output-wrap").hidden = true;
  document.getElementById("stream-output").textContent = "";
  document.getElementById("engineered-prompt-wrap").hidden = true;
  document.getElementById("engineered-prompt").textContent = "";
}

function logActivity(text, variant) {
  const log = document.getElementById("activity-log");
  const item = document.createElement("div");
  item.className = `activity-item ${variant || ""}`.trim();
  item.textContent = text;
  log.appendChild(item);
  log.scrollTop = log.scrollHeight;
}

function showStreamHeader(text) {
  document.getElementById("stream-output-wrap").hidden = false;
  document.getElementById("stream-output-label").textContent = text;
  document.getElementById("stream-output").textContent = "";
}

function appendStreamToken(piece) {
  const pre = document.getElementById("stream-output");
  document.getElementById("stream-output-wrap").hidden = false;
  pre.textContent += piece;
  pre.scrollTop = pre.scrollHeight;
}

function handleProgressEvent(event) {
  switch (event.type) {
    case "call_start":
      logActivity(`→ [${event.role}] ${event.provider}/${event.model} — ${event.purpose}`);
      showStreamHeader(`${event.provider}/${event.model} — ${event.purpose}`);
      break;
    case "call_fallback":
      logActivity(`⚠ ${event.provider}/${event.model} unavailable (${event.reason}) — trying next candidate`, "fallback");
      break;
    case "token":
      appendStreamToken(event.content);
      break;
    case "call_end":
      logActivity(`✓ [${event.role}] ${event.provider}/${event.model} done in ${event.duration_ms}ms`);
      break;
    case "language_detected":
      logActivity(`Detected language: ${event.language}`, "milestone");
      break;
    case "complexity_classified":
      logActivity(`Complexity: ${event.complexity}`, "milestone");
      break;
    case "prompt_engineered":
      logActivity("Prompt engineered from your request", "milestone");
      document.getElementById("engineered-prompt-wrap").hidden = false;
      document.getElementById("engineered-prompt").textContent = event.prompt;
      break;
    case "architecture_proposed":
      logActivity("Solution architect proposed a blueprint", "milestone");
      break;
    case "consensus_verdict":
      logActivity(
        `Consensus review (round ${event.round}): ${event.approved ? "APPROVED" : "REJECTED"} -- ${event.reason}`,
        event.approved ? "milestone" : "fallback"
      );
      break;
    case "architecture_revised":
      logActivity("Solution architect revised the blueprint after review", "milestone");
      break;
    case "tests_run":
      logActivity(`Initial test run: ${event.passed ? "PASSED" : "FAILED"}`, "milestone");
      break;
    case "heal_attempt_start":
      logActivity(`Self-heal attempt ${event.attempt} starting...`, "milestone");
      break;
    case "heal_attempt_result":
      logActivity(`Self-heal attempt ${event.attempt}: ${event.passed ? "PASSED" : "FAILED"}`, "milestone");
      break;
    case "heal_timeout":
      logActivity(`Self-heal timed out at attempt ${event.attempt}`, "fallback");
      break;
    case "heal_attempt_parse_failed":
      logActivity(`Self-heal attempt ${event.attempt}: fix response could not be parsed -- ${event.reason}`, "fallback");
      break;
    case "srs_context_engineered":
      logActivity("SRS: context engineered from raw requirements", "milestone");
      break;
    case "srs_prompt_engineered":
      logActivity("SRS: prompt engineered from context", "milestone");
      document.getElementById("engineered-prompt-wrap").hidden = false;
      document.getElementById("engineered-prompt").textContent = event.prompt;
      break;
    case "srs_review":
      logActivity(
        `SRS requirements review: ${event.approved ? "APPROVED" : "REJECTED"} -- ${event.reason}`,
        event.approved ? "milestone" : "fallback"
      );
      break;
    case "hld_context_engineered":
      logActivity("HLD: context engineered from SRS + task", "milestone");
      break;
    case "hld_prompt_engineered":
      logActivity("HLD: prompt engineered from context", "milestone");
      document.getElementById("engineered-prompt-wrap").hidden = false;
      document.getElementById("engineered-prompt").textContent = event.prompt;
      break;
    case "hld_review":
      logActivity(
        `HLD architect self-review: ${event.approved ? "APPROVED" : "REJECTED"} -- ${event.reason}`,
        event.approved ? "milestone" : "fallback"
      );
      break;
    case "agent_spawned":
      logActivity(`⚒ Spawned agent [${event.persona}] (${event.agent_id.slice(0, 8)})`, "milestone");
      break;
    case "agent_completed":
      logActivity(`⚒ Agent (${event.agent_id.slice(0, 8)}) finished in ${event.duration_ms}ms`, "milestone");
      break;
    case "kg_route_resolved":
      logActivity(
        `KG routed to [${event.lead_agent}] via ${event.pattern_id} (${event.domain})`,
        "milestone"
      );
      break;
    case "kg_route_unavailable":
      logActivity(`KG routing unavailable: ${event.reason}`, "fallback");
      break;
    case "docs_generation_started":
      logActivity(`Generating ${event.diagram_types.length} diagrams in parallel...`, "milestone");
      break;
    case "diagram_source":
      logActivity(`${event.diagram_type} diagram source: ${event.source}`, "milestone");
      break;
    case "diagram_generated":
      logActivity(`${event.diagram_type} diagram generated`, "milestone");
      break;
    case "diagram_generation_failed":
      logActivity(`${event.diagram_type} diagram failed: ${event.reason} -- skipped, others continue`, "fallback");
      break;
    case "traceability_generated":
      logActivity("Traceability matrix generated", "milestone");
      break;
    case "api_contract_skipped":
      logActivity(`API contract skipped: ${event.reason}`, "fallback");
      break;
    case "api_contract_generated":
      logActivity("OpenAPI contract generated", "milestone");
      break;
    case "joint_validation_verdict":
      logActivity(
        `Joint validation: ${event.approved ? "APPROVED" : "REJECTED"} -- ${event.reason}`,
        event.approved ? "milestone" : "fallback"
      );
      break;
    case "git_repo_initialized":
      logActivity("Git: initialized a new repo", "milestone");
      break;
    case "git_repo_already_exists":
      logActivity("Git: repo already exists", "milestone");
      break;
    case "git_commit_created":
      logActivity(`Git: commit ${event.commit_hash ?? "?"} created`, "milestone");
      break;
    case "git_commit_skipped":
      logActivity("Git: nothing to commit", "milestone");
      break;
    case "git_branch_pushed":
      logActivity(`Git: branch '${event.branch}' pushed`, "milestone");
      break;
    case "pr_created":
      logActivity(`Git: PR created (${event.pr_url ?? "?"})`, "milestone");
      break;
    case "full_stack_reconciliation_verdict":
      logActivity(
        `Reconciliation: ${event.approved ? "APPROVED" : "REJECTED"} -- ${event.reason}`,
        event.approved ? "milestone" : "fallback"
      );
      break;
    case "jira_epic_created":
      logActivity(`Jira: epic ${event.epic_key} created`, "milestone");
      break;
    case "jira_story_created":
      logActivity(`Jira: story ${event.issue_key} created for ${event.fr_id}`, "milestone");
      break;
    case "jira_epic_link_failed":
      logActivity(`Jira: ${event.issue_key} not linked to epic -- ${event.reason}`, "fallback");
      break;
    case "jira_sprint_created":
      logActivity(`Jira: sprint ${event.sprint_id} ('${event.name}') created`, "milestone");
      break;
    case "jira_issues_moved_to_sprint":
      logActivity(`Jira: ${event.issue_keys.length} issue(s) moved to sprint ${event.sprint_id}`, "milestone");
      break;
    case "file_manifest_planned":
      logActivity(`Parallel generation: file manifest planned (${event.file_count} files)`, "milestone");
      break;
    case "parallel_generation_group_completed":
      logActivity(`Parallel generation: group '${event.label}' completed (${event.file_count} file(s))`, "milestone");
      break;
    case "dependency_graph_computed":
      logActivity(`Parallel generation: dependency graph computed (${event.edge_count} edge(s))`, "milestone");
      break;
    case "generation_wave_completed":
      logActivity(`Parallel generation: wave ${event.wave} completed (${event.group_count} group(s))`, "milestone");
      break;
    case "dependency_cluster_exceeds_group_size":
      logActivity(`Parallel generation: dependency cluster of ${event.cluster_size} file(s) exceeds the target group size`, "fallback");
      break;
    case "dependency_cycle_fallback":
      logActivity("Parallel generation: cross-group dependency cycle detected -- falling back to wave 0", "fallback");
      break;
    case "parallel_group_count_exceeded_target":
      logActivity(`Parallel generation: ${event.group_count} groups exceeds the target of ${event.max_parallel_groups}`, "fallback");
      break;
  }
}

// --- File tree (package structure) ---------------------------------------

const FILE_ICONS = {
  py: "🐍",
  java: "☕",
  js: "📜",
  jsx: "📜",
  ts: "📘",
  tsx: "📘",
  html: "🌐",
  css: "🎨",
  json: "🗂️",
  yml: "⚙️",
  yaml: "⚙️",
  xml: "📰",
  md: "📝",
  txt: "📝",
  sql: "🗄️",
  sh: "💻",
  toml: "⚙️",
};

const HLJS_LANGUAGES = {
  py: "python",
  java: "java",
  js: "javascript",
  jsx: "javascript",
  ts: "typescript",
  tsx: "typescript",
  html: "html",
  css: "css",
  json: "json",
  yml: "yaml",
  yaml: "yaml",
  xml: "xml",
  md: "markdown",
  sql: "sql",
  sh: "bash",
  toml: "ini",
};

function fileExtension(path) {
  const base = path.split("/").pop() || "";
  const dot = base.lastIndexOf(".");
  return dot === -1 ? "" : base.slice(dot + 1).toLowerCase();
}

function fileIcon(path) {
  return FILE_ICONS[fileExtension(path)] || "📄";
}

function buildTree(paths) {
  const root = { children: new Map() };
  for (const path of paths) {
    const parts = path.split("/");
    let node = root;
    let prefix = "";
    for (let i = 0; i < parts.length; i++) {
      const part = parts[i];
      prefix = prefix ? `${prefix}/${part}` : part;
      const isFile = i === parts.length - 1;
      if (!node.children.has(part)) {
        node.children.set(part, { name: part, fullPath: prefix, isFile, children: new Map() });
      }
      node = node.children.get(part);
    }
  }
  return root;
}

function renderTreeNode(node, container, depth) {
  const sortedEntries = [...node.children.values()].sort((a, b) => {
    if (a.isFile !== b.isFile) return a.isFile ? 1 : -1;
    return a.name.localeCompare(b.name);
  });

  for (const child of sortedEntries) {
    const row = document.createElement("div");
    row.className = `tree-row ${child.isFile ? "file" : "folder"}`;
    row.style.paddingLeft = `${8 + depth * 16}px`;
    const icon = child.isFile ? fileIcon(child.fullPath) : "📁";
    row.innerHTML = `<span class="tree-icon">${icon}</span><span>${escapeHtml(child.name)}</span>`;
    container.appendChild(row);

    if (child.isFile) {
      row.dataset.path = child.fullPath;
      row.addEventListener("click", () => selectFile(child.fullPath));
    } else {
      renderTreeNode(child, container, depth + 1);
    }
  }
}

function selectFile(path) {
  document.querySelectorAll(".tree-row.file").forEach((row) => {
    row.classList.toggle("active", row.dataset.path === path);
  });

  const tabBar = document.getElementById("editor-tab");
  tabBar.innerHTML = `<span class="editor-tab-icon">${fileIcon(path)}</span><span>${escapeHtml(path)}</span>`;

  const codeEl = document.getElementById("file-content");
  codeEl.textContent = currentFiles[path] || "";
  codeEl.className = "";

  const lang = HLJS_LANGUAGES[fileExtension(path)];
  if (lang) codeEl.classList.add(`language-${lang}`);

  if (window.hljs) {
    delete codeEl.dataset.highlighted;
    hljs.highlightElement(codeEl);
    if (window.hljs.lineNumbersBlock) hljs.lineNumbersBlock(codeEl);
  }
}

function renderFiles(files) {
  currentFiles = files;
  const tree = document.getElementById("file-tree");
  tree.innerHTML = "";
  const paths = Object.keys(files);
  const root = buildTree(paths);
  renderTreeNode(root, tree, 0);
  if (paths.length > 0) selectFile(paths[0]);
}

// --- Preview / tests -------------------------------------------------------

function renderPreview(language, files) {
  const frame = document.getElementById("preview-frame");
  const unavailable = document.getElementById("preview-unavailable");
  const htmlEntry = Object.entries(files).find(([path]) => path.endsWith(".html"));

  if (language === "web" && htmlEntry) {
    frame.hidden = false;
    unavailable.hidden = true;
    frame.srcdoc = htmlEntry[1];
  } else {
    frame.hidden = true;
    unavailable.hidden = false;
  }
}

function renderAttempts(attempts) {
  const container = document.getElementById("attempts");
  container.innerHTML = "";
  for (const attempt of attempts) {
    const row = document.createElement("div");
    row.className = `attempt-row ${attempt.passed ? "attempt-pass" : "attempt-fail"}`;
    row.textContent = `Attempt ${attempt.attempt}: ${attempt.passed ? "PASSED" : "FAILED"}`;
    container.appendChild(row);
    if (!attempt.passed && attempt.stderr) {
      const stderrBlock = document.createElement("pre");
      stderrBlock.className = "code-pre text-xs";
      stderrBlock.textContent = attempt.stderr;
      container.appendChild(stderrBlock);
    }
  }
}

function renderFinal(result) {
  document.getElementById("empty-state").hidden = true;
  document.getElementById("error-panel").hidden = true;
  document.getElementById("workspace").hidden = false;

  const header = document.getElementById("workspace-header");
  if (result.workdir) {
    header.hidden = false;
    document.getElementById("workspace-path").textContent = result.workdir;
  } else {
    header.hidden = true;
  }

  const meta = document.getElementById("meta");
  meta.innerHTML = "";
  const chips = [
    { text: `Language: ${result.language}`, cls: "" },
    { text: `Complexity: ${result.complexity}`, cls: "" },
    { text: result.passed ? "Tests passed" : "Tests failing", cls: result.passed ? "pass" : "fail" },
  ];
  if (result.skill_used) chips.push({ text: `Skill: ${result.skill_used}`, cls: "" });
  if (result.agent_used) chips.push({ text: `Agent: ${result.agent_used}`, cls: "" });
  for (const chip of chips) {
    const span = document.createElement("span");
    span.className = `meta-chip ${chip.cls}`.trim();
    span.textContent = chip.text;
    meta.appendChild(span);
  }

  const planWrap = document.getElementById("plan-wrap");
  if (result.plan) {
    planWrap.hidden = false;
    document.getElementById("plan").textContent = result.plan;
  } else {
    planWrap.hidden = true;
  }

  if (result.engineered_prompt) {
    document.getElementById("engineered-prompt-wrap").hidden = false;
    document.getElementById("engineered-prompt").textContent = result.engineered_prompt;
  }

  renderFiles(result.files);
  renderPreview(result.language, result.files);
  renderAttempts(result.attempts);
  switchTab("code");
}

function renderError(message) {
  document.getElementById("workspace").hidden = true;
  document.getElementById("empty-state").hidden = true;
  document.getElementById("error-panel").hidden = false;
  document.getElementById("error-message").textContent = message;
}

// --- Chat/session history --------------------------------------------------

function timeAgo(isoString) {
  const seconds = Math.floor((Date.now() - new Date(isoString).getTime()) / 1000);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

async function loadSessions() {
  const response = await fetch("/sessions");
  const items = await response.json();
  const list = document.getElementById("session-list");
  list.innerHTML = "";
  for (const item of items) {
    const el = document.createElement("div");
    el.className = `session-item ${item.id === activeSessionId ? "active" : ""}`.trim();
    el.dataset.id = item.id;
    el.innerHTML = `
      <div class="session-task">${escapeHtml(item.task)}</div>
      <div class="session-meta">
        <span class="session-dot ${item.passed ? "pass" : "fail"}"></span>
        <span>${item.language}</span>
        <span>·</span>
        <span>${timeAgo(item.created_at)}</span>
      </div>`;
    el.addEventListener("click", () => selectSession(item.id));
    list.appendChild(el);
  }
}

async function selectSession(id) {
  const response = await fetch(`/sessions/${id}`);
  if (!response.ok) return;
  const session = await response.json();
  activeSessionId = id;
  document.querySelectorAll(".session-item").forEach((el) => {
    el.classList.toggle("active", el.dataset.id === id);
  });
  document.getElementById("task").value = session.task;
  clearActivityLog();
  renderFinal(session);
}

let sdlcStep = "srs"; // "srs" | "hld" | "implement" | "docs" | "api" | "git" | "reconcile" | "jira" -- only meaningful when sdlc_mode is checked

function resetSdlcState() {
  sdlcStep = "srs";
  document.getElementById("sdlc-srs-wrap").hidden = true;
  document.getElementById("sdlc-hld-wrap").hidden = true;
  document.getElementById("sdlc-docs-wrap").hidden = true;
  document.getElementById("sdlc-api-wrap").hidden = true;
  document.getElementById("sdlc-git-wrap").hidden = true;
  document.getElementById("sdlc-reconcile-wrap").hidden = true;
  document.getElementById("sdlc-jira-input-wrap").hidden = true;
  document.getElementById("sdlc-jira-wrap").hidden = true;
  document.getElementById("sdlc-srs-content").textContent = "";
  document.getElementById("sdlc-hld-content").textContent = "";
  document.getElementById("sdlc-docs-content").innerHTML = "";
  document.getElementById("sdlc-api-content").textContent = "";
  document.getElementById("sdlc-api-summary").textContent = "";
  document.getElementById("sdlc-git-summary").textContent = "";
  document.getElementById("sdlc-reconcile-summary").textContent = "";
  document.getElementById("sdlc-jira-summary").textContent = "";
  ["srs", "hld", "implement", "docs", "api", "git", "reconcile", "jira"].forEach((step) => {
    document.getElementById(`sdlc-step-${step}`).classList.remove("active", "done");
  });
  document.getElementById("sdlc-step-srs").classList.add("active");
  updateSubmitLabel();
}

function updateSubmitLabel() {
  const label = document.getElementById("submit").querySelector(".btn-label");
  if (!document.getElementById("sdlc_mode").checked) {
    label.textContent = "Generate";
    return;
  }
  label.textContent = {
    srs: "Generate SRS",
    hld: "Generate HLD",
    implement: "Implement",
    docs: "Generate Docs",
    api: "Generate API Contract",
    git: "Commit to Git",
    reconcile: "Reconcile Full-Stack",
    jira: "Create Jira Tickets",
  }[sdlcStep];
}

function startNewChat() {
  activeSessionId = null;
  document.querySelectorAll(".session-item").forEach((el) => el.classList.remove("active"));
  document.getElementById("task").value = "";
  document.getElementById("workspace").hidden = true;
  document.getElementById("error-panel").hidden = true;
  document.getElementById("empty-state").hidden = false;
  document.getElementById("workspace-header").hidden = true;
  clearActivityLog();
  resetSdlcState();
}

// --- Submit ------------------------------------------------------------

/**
 * POST `url` with `body`, parse the SSE response, and dispatch each frame
 * to onEvent/onFinal/onError. Shared by the normal /generate flow and every
 * /sdlc/* step so the fetch+SSE-parsing loop lives in one place.
 */
async function streamRequest(url, body, { onEvent, onFinal, onError }) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!response.ok || !response.body) {
    const detail = await response.json().catch(() => ({}));
    onError(detail.detail || `Request failed: ${response.status} ${response.statusText}`);
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let boundary;
    while ((boundary = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      if (!frame.startsWith("data: ")) continue;

      const event = JSON.parse(frame.slice(6));
      if (event.type === "final") {
        onFinal(event);
      } else if (event.type === "error") {
        onError(event.message);
      } else {
        onEvent(event);
      }
    }
  }
}

async function normalSubmit(task) {
  clearActivityLog();
  document.getElementById("empty-state").hidden = true;
  document.getElementById("workspace").hidden = false;
  switchTab("activity");

  await streamRequest(
    "/generate",
    {
      task,
      workdir: document.getElementById("workdir").value || null,
      skill_name: resolveDatalistValue(document.getElementById("skill").value, skillsByLabel),
      agent_name: resolveDatalistValue(document.getElementById("agent").value, agentsByLabel),
      use_rag: document.getElementById("use_rag").checked,
      project_dir: document.getElementById("project_dir").value || null,
    },
    {
      onEvent: handleProgressEvent,
      onFinal: async (event) => {
        renderFinal(event);
        activeSessionId = event.session_id;
        await loadSessions();
      },
      onError: renderError,
    }
  );
}

async function sdlcSubmit(task) {
  const workdir = document.getElementById("workdir").value || null;

  if (sdlcStep === "srs") {
    clearActivityLog();
    await streamRequest(
      "/sdlc/srs",
      { raw_requirements: task, workdir },
      {
        onEvent: handleProgressEvent,
        onFinal: (event) => {
          document.getElementById("sdlc-srs-wrap").hidden = false;
          document.getElementById("sdlc-srs-content").textContent = event.srs_markdown;
          document.getElementById("sdlc-srs-path").textContent =
            `Written to ${event.path} -- edit it directly if you want to change it before continuing.`;
          document.getElementById("sdlc-step-srs").classList.replace("active", "done");
          document.getElementById("sdlc-step-hld").classList.add("active");
          sdlcStep = "hld";
        },
        onError: renderError,
      }
    );
  } else if (sdlcStep === "hld") {
    await streamRequest(
      "/sdlc/hld",
      { workdir, task },
      {
        onEvent: handleProgressEvent,
        onFinal: (event) => {
          document.getElementById("sdlc-hld-wrap").hidden = false;
          document.getElementById("sdlc-hld-content").textContent = event.hld_markdown;
          document.getElementById("sdlc-hld-path").textContent =
            `Written to ${event.path} -- edit it directly if you want to change it before continuing.`;
          document.getElementById("sdlc-step-hld").classList.replace("active", "done");
          document.getElementById("sdlc-step-implement").classList.add("active");
          sdlcStep = "implement";
        },
        onError: renderError,
      }
    );
  } else if (sdlcStep === "implement") {
    document.getElementById("empty-state").hidden = true;
    document.getElementById("workspace").hidden = false;
    switchTab("activity");
    await streamRequest(
      "/sdlc/implement",
      {
        task,
        workdir,
        skill_name: resolveDatalistValue(document.getElementById("skill").value, skillsByLabel),
        agent_name: resolveDatalistValue(document.getElementById("agent").value, agentsByLabel),
        use_rag: document.getElementById("use_rag").checked,
        project_dir: document.getElementById("project_dir").value || null,
      },
      {
        onEvent: handleProgressEvent,
        onFinal: async (event) => {
          renderFinal(event);
          activeSessionId = event.session_id;
          await loadSessions();
          document.getElementById("sdlc-step-implement").classList.replace("active", "done");
          document.getElementById("sdlc-step-docs").classList.add("active");
          sdlcStep = "docs";
        },
        onError: renderError,
      }
    );
  } else if (sdlcStep === "docs") {
    switchTab("activity");
    await streamRequest(
      "/sdlc/docs",
      { workdir },
      {
        onEvent: handleProgressEvent,
        onFinal: (event) => {
          const wrap = document.getElementById("sdlc-docs-wrap");
          const content = document.getElementById("sdlc-docs-content");
          wrap.hidden = false;
          content.innerHTML = "";
          for (const [diagramType, diagram] of Object.entries(event.diagrams)) {
            const heading = document.createElement("h4");
            heading.className = "section-label mb-1";
            heading.textContent = diagramType;
            const pre = document.createElement("pre");
            pre.className = "code-pre text-xs";
            pre.textContent = diagram;
            content.appendChild(heading);
            content.appendChild(pre);
          }
          document.getElementById("sdlc-docs-summary").textContent =
            `${event.succeeded}/${event.total} diagrams generated. Traceability matrix appended to ${event.srs_path}.`;
          document.getElementById("sdlc-step-docs").classList.replace("active", "done");
          document.getElementById("sdlc-step-api").classList.add("active");
          sdlcStep = "api";
        },
        onError: renderError,
      }
    );
  } else if (sdlcStep === "api") {
    switchTab("activity");
    await streamRequest(
      "/sdlc/api",
      { workdir },
      {
        onEvent: handleProgressEvent,
        onFinal: (event) => {
          const wrap = document.getElementById("sdlc-api-wrap");
          const content = document.getElementById("sdlc-api-content");
          const summary = document.getElementById("sdlc-api-summary");
          wrap.hidden = false;
          if (event.skipped) {
            content.textContent = "";
            summary.textContent = `Skipped -- ${event.reason}.`;
          } else {
            content.textContent = event.openapi_yaml;
            summary.textContent = `Written to ${event.openapi_path}. Joint validation appended to ${event.hld_path}.`;
          }
          document.getElementById("sdlc-step-api").classList.replace("active", "done");
          document.getElementById("sdlc-step-git").classList.add("active");
          sdlcStep = "git";
        },
        onError: renderError,
      }
    );
  } else if (sdlcStep === "git") {
    switchTab("activity");
    await streamRequest(
      "/sdlc/git",
      { workdir },
      {
        onEvent: handleProgressEvent,
        onFinal: (event) => {
          const wrap = document.getElementById("sdlc-git-wrap");
          const summary = document.getElementById("sdlc-git-summary");
          wrap.hidden = false;
          const commitPart = event.commit
            ? `Committed ${event.commit.commit_hash ?? "?"}.`
            : "Nothing to commit.";
          summary.textContent = event.pr_skipped_reason
            ? `${commitPart} PR skipped -- ${event.pr_skipped_reason}.`
            : commitPart;
          document.getElementById("sdlc-step-git").classList.replace("active", "done");
          document.getElementById("sdlc-step-reconcile").classList.add("active");
          sdlcStep = "reconcile";
        },
        onError: renderError,
      }
    );
  } else if (sdlcStep === "reconcile") {
    switchTab("activity");
    document.getElementById("sdlc-jira-input-wrap").hidden = false;
    await streamRequest(
      "/sdlc/reconcile",
      { workdir },
      {
        onEvent: handleProgressEvent,
        onFinal: (event) => {
          const wrap = document.getElementById("sdlc-reconcile-wrap");
          const summary = document.getElementById("sdlc-reconcile-summary");
          wrap.hidden = false;
          if (event.skipped) {
            summary.textContent = `Skipped -- ${event.reason}.`;
          } else {
            summary.textContent = `Appended to ${event.hld_path}.${event.advisory ? " " + event.advisory : ""}`;
          }
          document.getElementById("sdlc-step-reconcile").classList.replace("active", "done");
          document.getElementById("sdlc-step-jira").classList.add("active");
          sdlcStep = "jira";
        },
        onError: renderError,
      }
    );
  } else {
    switchTab("activity");
    const projectKey = document.getElementById("jira-project-key").value;
    if (!projectKey) {
      renderError("Enter a Jira project key before continuing.");
      return;
    }
    await streamRequest(
      "/sdlc/jira",
      {
        workdir,
        project_key: projectKey,
        sprint: document.getElementById("jira-sprint").checked,
        sprint_name: document.getElementById("jira-sprint-name").value || null,
      },
      {
        onEvent: handleProgressEvent,
        onFinal: (event) => {
          const wrap = document.getElementById("sdlc-jira-wrap");
          const summary = document.getElementById("sdlc-jira-summary");
          wrap.hidden = false;
          const linked = event.stories.filter((s) => s.linked).length;
          let text = `Epic ${event.epic.key}: ${event.stories.length} stories created, ${linked} linked.`;
          if (event.sprint) {
            text += ` Sprint '${event.sprint.name}' populated.`;
          }
          summary.textContent = `${text} Written to ${event.jira_tickets_path}.`;
          document.getElementById("sdlc-step-jira").classList.replace("active", "done");
        },
        onError: renderError,
      }
    );
  }
}

async function submitTask() {
  const button = document.getElementById("submit");
  const label = button.querySelector(".btn-label");
  const spinner = button.querySelector(".spinner");
  const task = document.getElementById("task").value.trim();

  if (!task) {
    renderError("Describe what you want built before generating.");
    return;
  }

  const sdlcMode = document.getElementById("sdlc_mode").checked;

  button.disabled = true;
  label.textContent = "Generating…";
  spinner.hidden = false;
  document.getElementById("error-panel").hidden = true;

  try {
    if (sdlcMode) {
      await sdlcSubmit(task);
    } else {
      await normalSubmit(task);
    }
  } catch (err) {
    renderError(`Network error: ${err.message}`);
  } finally {
    button.disabled = false;
    spinner.hidden = true;
    updateSubmitLabel();
  }
}

document.addEventListener("DOMContentLoaded", () => {
  loadSkills();
  loadAgents();
  loadSessions();
  initTabs();

  document.getElementById("submit").addEventListener("click", submitTask);
  document.getElementById("new-chat").addEventListener("click", startNewChat);

  const ragCheckbox = document.getElementById("use_rag");
  const projectDirInput = document.getElementById("project_dir");
  ragCheckbox.addEventListener("change", () => {
    projectDirInput.disabled = !ragCheckbox.checked;
  });

  const sdlcCheckbox = document.getElementById("sdlc_mode");
  sdlcCheckbox.addEventListener("change", () => {
    document.getElementById("sdlc-panel").hidden = !sdlcCheckbox.checked;
    resetSdlcState();
  });
  resetSdlcState();
});
