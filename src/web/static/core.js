export const state = {
  selectedFeedUrl: null,
  conferences: [],
  categories: [],
  focusTags: [],
  selectedCollectConferences: new Set(),
  selectedCollectTasks: null,
  selectedSearchConferences: new Set(),
  selectedYears: new Set(),
  yearSelectionTouched: false,
  yearProgress: [],
  currentCollectJobRef: null,
  collectPollTimer: null,
  jobHistory: [],
  customYears: new Set(),
};

// Restore current job from localStorage on load
try {
  const savedJob = localStorage.getItem("pc_current_job");
  if (savedJob) state.currentCollectJobRef = savedJob;
} catch (_) { /* localStorage unavailable */ }

export function saveCurrentJobRef(ref) {
  state.currentCollectJobRef = ref;
  try {
    if (ref) localStorage.setItem("pc_current_job", ref);
    else localStorage.removeItem("pc_current_job");
  } catch (_) { /* localStorage unavailable */ }
}

export const $ = (selector) => document.querySelector(selector);

export const urlBase = normalizeUrlBase(window.PAPERCOLLECT_URL_BASE || "");

export function normalizeUrlBase(value) {
  const trimmed = String(value || "").replace(/\/+$/, "");
  if (!trimmed || trimmed === "/") {
    return "";
  }
  return trimmed.startsWith("/") ? trimmed : `/${trimmed}`;
}

export function appUrl(path) {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  return `${urlBase}${normalized}`;
}

export function jobStatusUrl(jobRef) {
  const value = String(jobRef || "");
  if (value.startsWith("/")) {
    return value;
  }
  return appUrl(`/api/jobs/${value}`);
}

export function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

export function truncate(value, length) {
  if (value.length <= length) {
    return value;
  }
  return `${value.slice(0, length - 1)}…`;
}

export function guessDefaultYear(values) {
  if (values && values.length) {
    return Math.max(...values.map(Number));
  }
  return new Date().getFullYear();
}

export function formatTimestamp(ts) {
  const d = new Date(ts * 1000);
  const pad = (n) => String(n).padStart(2, "0");
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function setStatus(message, status) {
  const statusNode = $("#status");
  statusNode.textContent = message;
  statusNode.dataset.status = status;
}

export function setCollectRunning(isRunning) {
  $("#collect-button").disabled = isRunning;
  const stopButton = $("#collect-stop-button");
  stopButton.disabled = false;
  stopButton.textContent = "Stop";
  stopButton.classList.toggle("hidden", !isRunning);
  if (!isRunning && state.collectPollTimer) {
    window.clearTimeout(state.collectPollTimer);
    state.collectPollTimer = null;
  }
}

export function setSearchStatus(message, status) {
  const statusNode = $("#search-status");
  statusNode.textContent = message;
  statusNode.dataset.status = status;
}

export function setIndexStatus(message, status) {
  const statusNode = $("#index-status");
  statusNode.textContent = message;
  statusNode.dataset.status = status;
}

export function jobStatusShort(job) {
  const s = job.status;
  if (s === "completed") return "Completed";
  if (s === "failed") return "Failed";
  if (s === "stopped") return "Stopped";
  if (s === "running") return "Running";
  if (s === "queued") return "Queued";
  return s;
}

export function jobSummaryText(job, summary) {
  const total = job.task_count || 0;
  if (!total) return job.type || "job";
  const parts = [];
  if (summary.completed) parts.push(`${summary.completed} done`);
  if (summary.running) parts.push(`${summary.running} running`);
  if (summary.pending) parts.push(`${summary.pending} pending`);
  if (summary.failed) parts.push(`${summary.failed} failed`);
  if (summary.skipped) parts.push(`${summary.skipped} skipped`);
  return parts.join(", ") || `${total} tasks`;
}

export function jobTypeIcon(type) {
  if (type === "collection") return "📄";
  if (type === "index") return "🔍";
  if (type === "sync") return "☁️";
  return "📋";
}

export function showToast(message, type = "info") {
  const container = document.getElementById("toast-container");
  if (!container) return;
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => {
    toast.classList.add("fade-out");
    toast.addEventListener("animationend", () => toast.remove());
  }, 3000);
}

export function initTheme() {
  const toggle = document.getElementById("theme-toggle");
  if (!toggle) return;
  let theme = localStorage.getItem("pc_theme");
  if (!theme) {
    theme = window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  document.documentElement.setAttribute("data-theme", theme);
  toggle.textContent = theme === "dark" ? "☀️" : "🌙";
  toggle.addEventListener("click", () => {
    const current = document.documentElement.getAttribute("data-theme");
    const next = current === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    localStorage.setItem("pc_theme", next);
    toggle.textContent = next === "dark" ? "☀️" : "🌙";
  });
}

export function initJobHistoryCollapse() {
  const panel = document.querySelector(".job-history-panel");
  if (!panel) return;
  const collapsed = localStorage.getItem("pc_job_history_collapsed") !== "false";
  if (collapsed) panel.classList.add("collapsed");
  const btn = panel.querySelector(".job-history-toggle");
  if (btn) {
    btn.addEventListener("click", () => {
      panel.classList.toggle("collapsed");
      localStorage.setItem("pc_job_history_collapsed", panel.classList.contains("collapsed"));
    });
  }
}
