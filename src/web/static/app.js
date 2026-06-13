const state = {
  selectedFeedUrl: null,
  conferences: [],
  categories: [],
  focusTags: [],
  selectedCollectConferences: new Set(),
  selectedSearchConferences: new Set(),
  selectedYears: new Set(),
  yearProgress: [],
  yearFilter: null,
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

function saveCurrentJobRef(ref) {
  state.currentCollectJobRef = ref;
  try {
    if (ref) localStorage.setItem("pc_current_job", ref);
    else localStorage.removeItem("pc_current_job");
  } catch (_) { /* localStorage unavailable */ }
}

const $ = (selector) => document.querySelector(selector);
const urlBase = normalizeUrlBase(window.PAPERCOLLECT_URL_BASE || "");

function normalizeUrlBase(value) {
  const trimmed = String(value || "").replace(/\/+$/, "");
  if (!trimmed || trimmed === "/") {
    return "";
  }
  return trimmed.startsWith("/") ? trimmed : `/${trimmed}`;
}

function appUrl(path) {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  return `${urlBase}${normalized}`;
}

function jobStatusUrl(jobRef) {
  const value = String(jobRef || "");
  if (value.startsWith("/")) {
    return value;
  }
  return appUrl(`/api/jobs/${value}`);
}

async function loadOptions() {
  const response = await fetch(appUrl("/api/options"));
  const data = await response.json();

  state.conferences = data.conferences || [];
  state.categories = data.categories || [];
  state.focusTags = data.focus_tags || [];
  fillCategorySelect($("#collect-category"), state.categories, true);
  fillCategorySelect($("#search-category"), state.categories, true);
  fillFocusSelect($("#collect-focus"), state.focusTags, true);
  fillFocusSelect($("#search-focus"), state.focusTags, true);
  fillCcfSelect($("#collect-ccf"), deriveCcfTiers(state.conferences), true);
  fillCcfSelect($("#search-ccf"), deriveCcfTiers(state.conferences), true);
  if (!state.selectedCollectConferences.size && state.conferences.length) {
    state.selectedCollectConferences.add(state.conferences[0].id);
  }
  renderCollectConferencePicker();
  renderSearchConferencePicker();
  fillYearSuggestions($("#year-options"), data.years);
  $("#limit").value = data.limit_per_conference || 0;
}

function fillYearSuggestions(datalist, values) {
  datalist.innerHTML = "";
  for (const value of values || []) {
    const option = document.createElement("option");
    option.value = value;
    datalist.appendChild(option);
  }
}

function guessDefaultYear(values) {
  if (values && values.length) {
    return Math.max(...values.map(Number));
  }
  return new Date().getFullYear();
}

async function loadYearProgress(customYears) {
  try {
    let url = appUrl("/api/year-progress");
    if (customYears && customYears.length) {
      url += `?years=${customYears.join(",")}`;
    }
    const response = await fetch(url);
    const data = await response.json();
    state.yearProgress = data.progress || [];
    renderYearProgress(state.yearProgress);
  } catch (err) {
    // year-progress is optional; ignore failures silently.
  }
}

async function loadJobHistory() {
  try {
    const response = await fetch(appUrl("/api/jobs"));
    const data = await response.json();
    state.jobHistory = data.jobs || [];
    renderJobHistory();

    // Auto-resume polling for running jobs, or restore view for completed jobs
    if (state.currentCollectJobRef) {
      const jobId = jobStatusUrl(state.currentCollectJobRef).split("/").pop();
      const savedJob = state.jobHistory.find((j) => j.id === jobId);
      if (savedJob) {
        if (savedJob.status === "running" || savedJob.status === "queued") {
          pollJob(state.currentCollectJobRef);
        } else {
          viewJob(jobId);
        }
      }
    }
  } catch (err) {
    // job history is optional; ignore failures silently.
  }
}

function renderJobHistory() {
  const container = $("#job-history");
  if (!container) return;

  const jobs = state.jobHistory;
  if (!jobs.length) {
    container.innerHTML = '<div class="job-history-empty">No jobs yet.</div>';
    return;
  }

  let html = '<div class="job-history-list">';
  for (const job of jobs) {
    const summary = job.task_summary || {};
    const statusLabel = jobStatusShort(job);
    const summaryText = jobSummaryText(job, summary);
    const isActive = job.status === "running" || job.status === "queued";
    const timeStr = job.created_at ? formatTimestamp(job.created_at) : "";
    html += `<div class="job-history-item" data-status="${job.status}" data-job-id="${job.id}">
      <span class="task-icon">${jobTypeIcon(job.type)}</span>
      <div>
        <div class="job-history-status">${escapeHtml(statusLabel)}</div>
        <div class="job-history-summary">${escapeHtml(summaryText)}${timeStr ? ` · ${timeStr}` : ""}</div>
      </div>
      <span class="job-history-status" style="font-size:11px">${isActive ? "● Active" : ""}</span>
      <button class="job-history-delete" data-job-id="${job.id}" title="Delete job">✕</button>
    </div>`;
  }
  html += "</div>";
  container.innerHTML = html;

  // Bind click to view/restore job
  for (const item of container.querySelectorAll(".job-history-item")) {
    item.addEventListener("click", (e) => {
      if (e.target.closest(".job-history-delete")) return;
      const jobId = item.dataset.jobId;
      viewJob(jobId);
    });
  }

  // Bind delete buttons
  for (const btn of container.querySelectorAll(".job-history-delete")) {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      deleteJob(btn.dataset.jobId);
    });
  }
}

function jobStatusShort(job) {
  const s = job.status;
  if (s === "completed") return "Completed";
  if (s === "failed") return "Failed";
  if (s === "stopped") return "Stopped";
  if (s === "running") return "Running";
  if (s === "queued") return "Queued";
  return s;
}

function jobSummaryText(job, summary) {
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

function jobTypeIcon(type) {
  if (type === "collection") return "📄";
  if (type === "index") return "🔍";
  if (type === "sync") return "☁️";
  return "📋";
}

function formatTimestamp(ts) {
  const d = new Date(ts * 1000);
  const pad = (n) => String(n).padStart(2, "0");
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

async function viewJob(jobId) {
  try {
    const response = await fetch(appUrl(`/api/jobs/${jobId}`));
    const job = await response.json();
    if (!response.ok) return;

    if (job.type === "collection" && job.queue && job.queue.length) {
      saveCurrentJobRef(appUrl(`/api/jobs/${jobId}`));
      setStatus(renderJobStatus(job), job.status);
      renderQueuePanel(job);
      $("#logs").textContent = (job.logs || []).join("\n") || "";
      if (job.status === "running" || job.status === "queued") {
        setCollectRunning(true);
        pollJob(state.currentCollectJobRef);
      } else {
        setCollectRunning(false);
      }
    }
  } catch (_) { /* ignore */ }
}

async function deleteJob(jobId) {
  try {
    const response = await fetch(appUrl(`/api/jobs/${jobId}`), { method: "DELETE" });
    if (response.ok) {
      state.jobHistory = state.jobHistory.filter((j) => j.id !== jobId);
      renderJobHistory();
      // Clear current ref if we deleted the active job
      if (state.currentCollectJobRef) {
        const currentId = jobStatusUrl(state.currentCollectJobRef).split("/").pop();
        if (currentId === jobId) {
          saveCurrentJobRef(null);
          setCollectRunning(false);
          setStatus("Ready.", "idle");
          $("#task-queue").classList.add("hidden");
          $("#task-queue").innerHTML = "";
          $("#logs").textContent = "";
        }
      }
    }
  } catch (_) { /* ignore */ }
}

function renderYearProgress(progress) {
  const container = $("#year-progress");
  if (!container) return;
  if (!progress.length) {
    container.classList.add("hidden");
    container.innerHTML = "";
    return;
  }

  // Gather all configured years from selected conferences.
  const selectedIds = state.selectedCollectConferences;
  const allYears = new Set();
  for (const entry of progress) {
    if (selectedIds.size && !selectedIds.has(entry.conference_id)) continue;
    for (const y of entry.configured_years) allYears.add(y);
  }
  const sortedYears = [...allYears].sort((a, b) => b - a);

  // Build a map: year -> {saved: Set, missing: Set}
  const yearMap = new Map();
  for (const y of sortedYears) yearMap.set(y, { saved: new Set(), missing: new Set() });
  for (const entry of progress) {
    if (selectedIds.size && !selectedIds.has(entry.conference_id)) continue;
    for (const y of entry.saved_years) {
      if (yearMap.has(y)) yearMap.get(y).saved.add(entry.conference_id);
    }
    for (const y of entry.missing_years) {
      if (yearMap.has(y)) yearMap.get(y).missing.add(entry.conference_id);
    }
  }

  // Pre-select missing years if no selection yet.
  if (!state.selectedYears.size) {
    for (const y of sortedYears) {
      const info = yearMap.get(y);
      if (info && info.missing.size > 0) state.selectedYears.add(y);
    }
  }

  container.classList.remove("hidden");
  let html = '<div class="year-progress-header"><span class="year-progress-title">Year progress</span>';
  html += '<span class="year-custom-input"><input type="number" id="custom-year-input" min="1900" max="2099" placeholder="Year" style="width:64px"><button id="custom-year-add" class="secondary" type="button">+</button></span>';
  html += '</div>';
  if (state.yearFilter !== null) {
    html += `<span class="year-filter-indicator">Filtering: ${state.yearFilter} <button class="year-filter-clear" id="year-filter-clear">✕</button></span>`;
  }
  html += '<div class="year-progress-grid">';
  for (const y of sortedYears) {
    const info = yearMap.get(y) || { saved: new Set(), missing: new Set() };
    const total = info.saved.size + info.missing.size;
    const savedCount = info.saved.size;
    const missingCount = info.missing.size;
    const pct = total > 0 ? Math.round((savedCount / total) * 100) : 0;
    const checked = state.selectedYears.has(y);
    const filtering = state.yearFilter === y;
    html += `<label class="year-progress-chip${checked ? ' selected' : ''}${filtering ? ' filtering' : ''}" title="${savedCount}/${total} saved${missingCount ? `; ${missingCount} missing` : ''}">
      <input type="checkbox" value="${y}" ${checked ? 'checked' : ''} class="year-checkbox">
      <span class="year-chip-label">${y}</span>
      <span class="year-chip-bar"><span class="year-chip-fill" style="width:${pct}%"></span></span>
      <span class="year-chip-count">${savedCount}/${total}</span>
      ${missingCount ? `<button class="year-filter-btn${filtering ? ' active' : ''}" data-year="${y}" title="只显示 ${y} 年有缺失的会议">🔍</button>` : ''}
    </label>`;
  }
  html += '</div>';
  container.innerHTML = html;

  // Bind checkboxes — toggle year for collection.
  for (const cb of container.querySelectorAll(".year-checkbox")) {
    cb.addEventListener("change", () => {
      const val = Number(cb.value);
      if (cb.checked) state.selectedYears.add(val);
      else state.selectedYears.delete(val);
      cb.closest(".year-progress-chip").classList.toggle("selected", cb.checked);
    });
  }

  // Bind year filter buttons — click to filter conferences by missing year.
  for (const btn of container.querySelectorAll(".year-filter-btn")) {
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      const year = Number(btn.dataset.year);
      state.yearFilter = state.yearFilter === year ? null : year;
      renderYearProgress(state.yearProgress);
      renderCollectConferencePicker();
    });
  }

  // Bind clear filter button.
  const clearBtn = container.querySelector("#year-filter-clear");
  if (clearBtn) {
    clearBtn.addEventListener("click", () => {
      state.yearFilter = null;
      renderYearProgress(state.yearProgress);
      renderCollectConferencePicker();
    });
  }

  // Bind custom year input.
  const customInput = container.querySelector("#custom-year-input");
  const customAdd = container.querySelector("#custom-year-add");
  if (customInput && customAdd) {
    const addCustomYear = () => {
      const val = parseInt(customInput.value, 10);
      if (val >= 1900 && val <= 2099) {
        state.customYears.add(val);
        state.selectedYears.add(val);
        customInput.value = "";
        loadYearProgress([...state.customYears]);
      }
    };
    customAdd.addEventListener("click", addCustomYear);
    customInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        addCustomYear();
      }
    });
  }
}

function fillCategorySelect(select, categories, includeAll = false) {
  select.innerHTML = "";
  if (includeAll) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "All categories";
    select.appendChild(option);
  }
  for (const category of categories) {
    const option = document.createElement("option");
    option.value = category.id;
    option.textContent = formatCategoryLabel(category);
    option.title = category.name_en || category.name || category.id;
    select.appendChild(option);
  }
}

function fillFocusSelect(select, focusTags, includeAll = false) {
  select.innerHTML = "";
  if (includeAll) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "All focus areas";
    select.appendChild(option);
  }
  for (const tag of focusTags) {
    const option = document.createElement("option");
    option.value = tag.id;
    option.textContent = tag.label;
    select.appendChild(option);
  }
}

function fillCcfSelect(select, tiers, includeAll = false) {
  select.innerHTML = "";
  if (includeAll) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "All CCF tiers";
    select.appendChild(option);
  }
  for (const tier of tiers) {
    const option = document.createElement("option");
    option.value = tier;
    option.textContent = `CCF ${tier}`;
    select.appendChild(option);
  }
}

function deriveCcfTiers(conferences) {
  const order = ["A", "B", "C", "N"];
  const tiers = new Set(
    conferences
      .map((conference) => conferenceCcf(conference))
      .filter(Boolean),
  );
  return [...tiers].sort((left, right) => {
    const leftIndex = order.indexOf(left);
    const rightIndex = order.indexOf(right);
    if (leftIndex === -1 && rightIndex === -1) {
      return left.localeCompare(right);
    }
    if (leftIndex === -1) {
      return 1;
    }
    if (rightIndex === -1) {
      return -1;
    }
    return leftIndex - rightIndex;
  });
}

function visibleCollectConferences() {
  return visibleConferences({
    category: $("#collect-category").value || null,
    focus: $("#collect-focus").value || null,
    ccf: $("#collect-ccf").value || null,
    yearFilter: state.yearFilter,
  });
}

function visibleSearchConferences() {
  return visibleConferences({
    category: $("#search-category").value || null,
    focus: $("#search-focus").value || null,
    ccf: $("#search-ccf").value || null,
  });
}

function visibleConferences(filters) {
  return state.conferences.filter((conference) => conferenceMatchesFilters(conference, filters));
}

function conferenceMatchesFilters(conference, filters) {
  if (filters.category && conference.category !== filters.category) {
    return false;
  }
  if (filters.focus && !(conference.focus_tags || []).includes(filters.focus)) {
    return false;
  }
  if (filters.ccf && conferenceCcf(conference) !== filters.ccf) {
    return false;
  }
  if (filters.yearFilter != null) {
    const progress = state.yearProgress.find((p) => p.conference_id === conference.id);
    if (progress && progress.missing_years && progress.missing_years.includes(filters.yearFilter)) {
      return true;
    }
    return false;
  }
  return true;
}

function renderCollectConferencePicker() {
  const picker = $("#conference-picker");
  const visible = visibleCollectConferences();
  picker.innerHTML = "";

  if (!visible.length) {
    picker.innerHTML = '<p class="muted">No conferences match the current filters.</p>';
    updateCollectConferenceCount(0);
    renderYearProgress(state.yearProgress);
    return;
  }

  for (const group of groupConferences(visible)) {
    const groupNode = document.createElement("section");
    groupNode.className = "conference-group";

    const title = document.createElement("h3");
    title.textContent = group.label;
    groupNode.appendChild(title);

    const list = document.createElement("div");
    list.className = "conference-list";
    for (const conference of group.conferences) {
      list.appendChild(
        conferenceCheckbox(conference, state.selectedCollectConferences, () => {
          updateCollectConferenceCount(visible.length);
          renderYearProgress(state.yearProgress);
        }),
      );
    }
    groupNode.appendChild(list);
    picker.appendChild(groupNode);
  }

  updateCollectConferenceCount(visible.length);
  renderYearProgress(state.yearProgress);
}

function selectVisibleCollectConferences() {
  for (const conference of visibleCollectConferences()) {
    state.selectedCollectConferences.add(conference.id);
  }
  renderCollectConferencePicker();
}

function clearVisibleCollectConferences() {
  for (const conference of visibleCollectConferences()) {
    state.selectedCollectConferences.delete(conference.id);
  }
  renderCollectConferencePicker();
}

function clearAllCollectConferences() {
  state.selectedCollectConferences.clear();
  renderCollectConferencePicker();
}

function updateCollectConferenceCount(visibleCount) {
  const filter = state.yearFilter != null ? ` · missing ${state.yearFilter}` : "";
  $("#conference-count").textContent =
    `${state.selectedCollectConferences.size} selected · ${visibleCount} visible${filter}`;
}

function renderSearchConferencePicker() {
  const picker = $("#search-conference-picker");
  const visible = visibleSearchConferences();
  picker.innerHTML = "";

  if (!visible.length) {
    picker.innerHTML = '<p class="muted">No conferences match the current filters.</p>';
    updateSearchConferenceCount(0);
    return;
  }

  for (const group of groupConferences(visible)) {
    const groupNode = document.createElement("section");
    groupNode.className = "conference-group";

    const title = document.createElement("h3");
    title.textContent = group.label;
    groupNode.appendChild(title);

    const list = document.createElement("div");
    list.className = "conference-list";
    for (const conference of group.conferences) {
      list.appendChild(
        conferenceCheckbox(conference, state.selectedSearchConferences, () => {
          updateSearchConferenceCount(visible.length);
        }),
      );
    }
    groupNode.appendChild(list);
    picker.appendChild(groupNode);
  }

  updateSearchConferenceCount(visible.length);
}

function selectVisibleSearchConferences() {
  for (const conference of visibleSearchConferences()) {
    state.selectedSearchConferences.add(conference.id);
  }
  renderSearchConferencePicker();
}

function clearVisibleSearchConferences() {
  for (const conference of visibleSearchConferences()) {
    state.selectedSearchConferences.delete(conference.id);
  }
  renderSearchConferencePicker();
}

function clearAllSearchConferences() {
  state.selectedSearchConferences.clear();
  renderSearchConferencePicker();
}

function updateSearchConferenceCount(visibleCount) {
  const selected = state.selectedSearchConferences.size;
  $("#search-conference-count").textContent = selected
    ? `${selected} selected · ${visibleCount} visible`
    : `All conferences · ${visibleCount} visible`;
}

function groupConferences(conferences) {
  const grouped = new Map();
  for (const conference of conferences) {
    const category = conference.category || "Other";
    const ccf = conferenceCcf(conference) || "N";
    const key = `${category}|${ccf}`;
    if (!grouped.has(key)) {
      grouped.set(key, {
        label: `${categoryLabel(category)} · CCF ${ccf}`,
        conferences: [],
      });
    }
    grouped.get(key).conferences.push(conference);
  }
  return [...grouped.values()];
}

function conferenceCheckbox(conference, selection, onChange) {
  const option = document.createElement("label");
  option.className = "conference-option";
  option.title = conference.full_name || conference.display_name;

  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.value = conference.id;
  checkbox.checked = selection.has(conference.id);
  checkbox.addEventListener("change", () => {
    if (checkbox.checked) {
      selection.add(conference.id);
    } else {
      selection.delete(conference.id);
    }
    onChange();
  });

  const text = document.createElement("span");
  text.className = "conference-option-text";
  text.textContent = conference.display_name;

  const meta = document.createElement("span");
  meta.className = "conference-option-meta";
  meta.textContent = conferenceSummary(conference);

  option.append(checkbox, text, meta);
  return option;
}

function conferenceSummary(conference) {
  const parts = [`CCF ${conferenceCcf(conference) || "N"}`];
  if ((conference.focus_tags || []).length) {
    parts.push(conference.focus_tags.join(", "));
  }
  return parts.join(" · ");
}

function conferenceCcf(conference) {
  return String((conference.tier || {}).ccf || "").trim().toUpperCase();
}

function categoryLabel(categoryId) {
  const category = state.categories.find((item) => item.id === categoryId);
  return category ? formatCategoryLabel(category) : categoryId;
}

function formatCategoryLabel(category) {
  const localName = category.name && category.name !== category.id ? category.name : "";
  const englishName = category.name_en && category.name_en !== category.id ? category.name_en : "";
  const label =
    localName && englishName && localName !== englishName
      ? `${localName} / ${englishName}`
      : localName || englishName || category.id;
  return `${category.id} · ${label}`;
}

async function loadFeeds() {
  const response = await fetch(appUrl("/api/feeds"));
  const data = await response.json();
  const list = $("#feeds");
  list.innerHTML = "";

  if (!data.feeds.length) {
    list.innerHTML = "<li>No saved feeds yet.</li>";
    return;
  }

  for (const feed of data.feeds) {
    const item = document.createElement("li");
    const link = document.createElement("a");
    link.href = feed.feed_url;
    link.textContent = `${feed.display_name || feed.conference} ${feed.year}`;
    link.target = "_blank";
    link.rel = "noreferrer";
    item.append(link, ` (${feed.paper_count} papers)`);
    list.appendChild(item);
  }
}

async function startCollection(event) {
  event.preventDefault();
  setStatus("Starting collection...", "running");
  setCollectRunning(true);
  $("#logs").textContent = "Waiting for collection logs...";
  $("#rss-link").classList.add("hidden");
  const selectedConferences = state.conferences
    .filter((conference) => state.selectedCollectConferences.has(conference.id))
    .map((conference) => conference.id);
  if (!selectedConferences.length) {
    setStatus("Choose at least one conference to collect.", "failed");
    setCollectRunning(false);
    $("#logs").textContent = "";
    return;
  }

  const selectedYears = [...state.selectedYears].sort();
  if (!selectedYears.length) {
    setStatus("Choose at least one year to collect.", "failed");
    setCollectRunning(false);
    $("#logs").textContent = "";
    return;
  }

  const payload = {
    conferences: selectedConferences,
    years: selectedYears,
    limit: Number($("#limit").value),
  };

  const response = await fetch(appUrl("/api/collect"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();

  if (!response.ok) {
    setStatus(data.error || "Failed to start collection.", "failed");
    setCollectRunning(false);
    $("#logs").textContent = data.error || "";
    return;
  }

  saveCurrentJobRef(data.status_url || data.job_id);
  pollJob(state.currentCollectJobRef);
}

async function stopCollection() {
  if (!state.currentCollectJobRef) {
    return;
  }

  const stopButton = $("#collect-stop-button");
  stopButton.disabled = true;
  stopButton.textContent = "Stopping...";
  setStatus("Stopping collection after the current conference...", "running");

  const response = await fetch(`${jobStatusUrl(state.currentCollectJobRef)}/stop`, {
    method: "POST",
  });
  const data = await response.json();
  if (!response.ok) {
    stopButton.disabled = false;
    stopButton.textContent = "Stop";
    setStatus(data.error || "Failed to stop collection.", "failed");
    return;
  }

  setStatus(renderJobStatus(data), data.status);
  renderQueuePanel(data);
  $("#logs").textContent = (data.logs || []).join("\n") || "Waiting for collection logs...";
}

async function searchPapers(event) {
  event.preventDefault();
  const params = new URLSearchParams();
  const query = $("#search-query").value.trim();
  const category = $("#search-category").value;
  const focus = $("#search-focus").value;
  const ccf = $("#search-ccf").value;
  const year = $("#search-year").value;
  const mode = $("#search-mode").value;

  if (query) params.set("q", query);
  if (mode) params.set("mode", mode);
  if (category) params.set("category", category);
  if (focus) params.set("focus", focus);
  if (ccf) params.set("ccf", ccf);
  for (const conference of state.selectedSearchConferences) {
    params.append("conference", conference);
  }
  if (year) params.set("year", year);
  params.set("limit", "30");

  setSearchStatus("Searching...", "running");
  const response = await fetch(appUrl(`/api/search?${params.toString()}`));
  const data = await response.json();
  if (!response.ok) {
    setSearchStatus(data.error || "Search failed.", "failed");
    return;
  }

  renderSearchResults(data.results || []);
  setSearchStatus(`Found ${data.results.length} papers with ${searchModeLabel(data.mode || mode)}.`, "completed");
}

async function startIndexBuild() {
  setIndexStatus("Starting vector index rebuild...", "running");
  $("#index-logs").textContent = "Waiting for index logs...";

  const response = await fetch(appUrl("/api/index"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ force: true }),
  });
  const data = await response.json();

  if (!response.ok) {
    setIndexStatus(data.error || "Failed to start vector index rebuild.", "failed");
    $("#index-logs").textContent = data.error || "";
    return;
  }

  pollIndexJob(data.status_url || data.job_id);
}

function renderSearchResults(results) {
  const root = $("#search-results");
  root.innerHTML = "";
  if (!results.length) {
    root.innerHTML = '<p class="muted">No saved papers match the query.</p>';
    return;
  }

  for (const paper of results) {
    const item = document.createElement("article");
    item.className = "search-result";

    const title = document.createElement(paper.url ? "a" : "h3");
    if (paper.url) {
      title.href = paper.url;
      title.target = "_blank";
      title.rel = "noreferrer";
    }
    title.textContent = paper.title;

    const meta = document.createElement("p");
    meta.className = "meta";
    meta.textContent = [
      paper.display_name || paper.venue,
      paper.year,
      paper.category ? categoryLabel(paper.category) : null,
      paper.tier && paper.tier.ccf ? `CCF ${paper.tier.ccf}` : null,
      paper.focus_tags && paper.focus_tags.length ? paper.focus_tags.join(", ") : null,
      paper.retrieval_backend ? paper.retrieval_backend : null,
      paper.matched_concepts && paper.matched_concepts.length ? `concepts: ${paper.matched_concepts.join(", ")}` : null,
    ].filter(Boolean).join(" · ");

    const abstract = document.createElement("p");
    abstract.textContent = truncate(paper.snippet || paper.abstract || "No abstract available.", 360);

    item.append(title, meta, abstract);
    root.appendChild(item);
  }
}

function searchModeLabel(mode) {
  if (mode === "agentic") {
    return "agentic hybrid search";
  }
  return mode === "concept" ? "concept semantic search" : "keyword search";
}

function truncate(value, length) {
  if (value.length <= length) {
    return value;
  }
  return `${value.slice(0, length - 1)}…`;
}

async function pollJob(jobId) {
  const expectedUrl = jobStatusUrl(jobId);
  if (state.currentCollectJobRef && expectedUrl !== jobStatusUrl(state.currentCollectJobRef)) {
    return;
  }

  const response = await fetch(jobStatusUrl(jobId));
  const job = await response.json();

  setStatus(renderJobStatus(job), job.status);
  renderQueuePanel(job);
  $("#logs").textContent = (job.logs || []).join("\n") || "Waiting for collection logs...";

  if (job.status === "completed") {
    state.selectedFeedUrl = job.feed_url || (job.feed_urls || [])[0] || null;
    const link = $("#rss-link");
    if (state.selectedFeedUrl) {
      link.href = state.selectedFeedUrl;
      const feedUrls = job.feed_urls || [];
      link.textContent = feedUrls.length > 1
        ? `Open first RSS feed (${feedUrls.length} total); all feeds are listed on the right`
        : `Open RSS feed`;
      link.classList.remove("hidden");
    }
    await Promise.all([loadFeeds(), loadYearProgress()]);
    setCollectRunning(false);
    renderQueuePanel(job);
    return;
  }

  if (job.status === "failed" || job.status === "stopped") {
    if (job.status === "stopped") {
      await Promise.all([loadFeeds(), loadYearProgress()]);
    }
    setCollectRunning(false);
    renderQueuePanel(job);
    return;
  }

  const interval = job.status === "running" ? 1500 : 3000;
  state.collectPollTimer = window.setTimeout(() => pollJob(jobId), interval);
}

async function pollIndexJob(jobId) {
  const response = await fetch(jobStatusUrl(jobId));
  const job = await response.json();

  setIndexStatus(renderIndexJobStatus(job), job.status);
  $("#index-logs").textContent = (job.logs || []).join("\n") || "Waiting for index logs...";

  if (job.status === "completed" || job.status === "failed") {
    return;
  }

  window.setTimeout(() => pollIndexJob(jobId), 1500);
}

function renderJobStatus(job) {
  const queue = job.queue || [];
  const totalTasks = queue.length;
  const yearCount = (job.years || []).length || 1;
  const confCount = job.conference_count || 1;
  if (job.status === "completed") {
    if (totalTasks > 1) {
      return `Completed: saved ${job.paper_count || 0} papers across ${job.completed_count || 0} tasks (${confCount} conferences x ${yearCount} years); ${job.failed_count || 0} failed.`;
    }
    const first = queue[0] || {};
    return `Completed: saved ${job.paper_count} papers for ${first.display_name || job.display_name || job.conference} ${first.year || job.year}.`;
  }
  if (job.status === "failed") {
    return `Failed: ${job.error || "unknown error"}`;
  }
  if (job.status === "stopped") {
    return `Stopped: saved ${job.paper_count || 0} papers across ${job.completed_count || 0} tasks; ${job.stopped_count || 0} not started.`;
  }
  if (totalTasks > 1) {
    return `Running batch collection for ${totalTasks} tasks (${confCount} conferences x ${yearCount} years)...`;
  }
  const first = queue[0] || {};
  return `Running collection for ${first.display_name || job.display_name || job.conference} ${first.year || job.year}...`;
}

function renderIndexJobStatus(job) {
  if (job.status === "completed") {
    return `Index ready: ${job.paper_count || 0} papers in ${job.collection}.`;
  }
  if (job.status === "failed") {
    return `Index failed: ${job.error || "unknown error"}`;
  }
  return `Building vector index for ${job.collection || "papers"}...`;
}

function renderQueuePanel(job) {
  const panel = $("#task-queue");
  const queue = job.queue || [];
  if (!queue.length) {
    panel.classList.add("hidden");
    panel.innerHTML = "";
    return;
  }
  panel.classList.remove("hidden");

  const hasRetryable = queue.some((t) => t.status === "failed" || t.status === "skipped");
  const hasSkipped = queue.some((t) => t.status === "skipped");
  const isTerminal = ["stopped", "failed", "completed"].includes(job.status);
  const canModify = job.status !== "running";

  let actionsHtml = "";
  if (isTerminal && hasSkipped) {
    actionsHtml += `<button class="task-queue-resume secondary" type="button">Resume</button>`;
  }
  if (isTerminal && hasRetryable) {
    actionsHtml += `<button class="task-queue-retry secondary" type="button">Retry failed</button>`;
  }

  const jobId = job.id || "";
  let html = `<div class="task-queue-header">`;
  html += `<h3>Task queue (${queue.length})</h3>`;
  if (actionsHtml) {
    html += `<div class="task-queue-actions">${actionsHtml}</div>`;
  }
  html += `</div>`;
  html += `<div class="task-list" data-job-id="${jobId}">`;
  for (const task of queue) {
    html += renderTaskItem(task, isTerminal, jobId, canModify);
  }
  html += `</div>`;
  if (canModify) {
    html += `<button class="task-queue-add" type="button" data-job-id="${jobId}">+ Add task</button>`;
  }
  panel.innerHTML = html;

  const resumeBtn = panel.querySelector(".task-queue-resume");
  if (resumeBtn) {
    resumeBtn.addEventListener("click", () => resumeJob(jobId));
  }
  const retryBtn = panel.querySelector(".task-queue-retry");
  if (retryBtn) {
    retryBtn.addEventListener("click", () => retryJob(jobId));
  }
  for (const btn of panel.querySelectorAll(".task-retry-btn")) {
    btn.addEventListener("click", () => retryTask(btn.dataset.jobId, btn.dataset.taskId));
  }
  for (const btn of panel.querySelectorAll(".task-remove-btn")) {
    btn.addEventListener("click", () => removeTask(btn.dataset.jobId, btn.dataset.taskId));
  }
  const addBtn = panel.querySelector(".task-queue-add");
  if (addBtn) {
    addBtn.addEventListener("click", () => showAddTaskForm(jobId));
  }

  // Setup drag-and-drop for reorder
  if (canModify) {
    setupQueueDragDrop(panel, jobId);
  }
}

function renderTaskItem(task, isTerminal, jobId, canModify) {
  const icon = taskStatusIcon(task.status);
  const canRetry = isTerminal && (task.status === "failed" || task.status === "skipped");
  const canRemove = canModify && (task.status === "pending" || task.status === "skipped");
  const detail = taskDetail(task);
  let retryBtn = "";
  if (canRetry) {
    retryBtn = `<button class="task-retry-btn" data-job-id="${jobId}" data-task-id="${task.task_id}">Retry</button>`;
  }
  let removeBtn = "";
  if (canRemove) {
    removeBtn = `<button class="task-remove-btn" data-job-id="${jobId}" data-task-id="${task.task_id}" title="Remove task">&times;</button>`;
  }
  let dragHandle = "";
  if (canModify && task.status === "pending") {
    dragHandle = `<span class="task-drag-handle" draggable="true" data-task-id="${task.task_id}">⠿</span>`;
  }
  const yearLabel = task.year != null ? ` ${task.year}` : "";
  return `<div class="task-item" data-status="${task.status}" data-task-id="${task.task_id}">
    ${dragHandle}<span class="task-icon">${icon}</span>
    <span class="task-name">${escapeHtml(task.display_name)}${yearLabel}</span>
    <span class="task-detail">${detail}${retryBtn}${removeBtn}</span>
  </div>`;
}

function taskStatusIcon(status) {
  switch (status) {
    case "pending": return '<span class="task-icon-pending">&#9711;</span>';
    case "running": return '<span class="task-icon-running">&#9697;</span>';
    case "completed": return '<span class="task-icon-completed">&#10003;</span>';
    case "failed": return '<span class="task-icon-failed">&#10007;</span>';
    case "skipped": return '<span class="task-icon-skipped">&#8211;</span>';
    default: return '<span class="task-icon-unknown">?</span>';
  }
}

function taskDetail(task) {
  if (task.status === "completed" && task.paper_count != null) {
    return `${task.paper_count} papers `;
  }
  if (task.status === "failed" && task.error) {
    return `Error `;
  }
  if (task.status === "skipped") {
    return "Skipped ";
  }
  if (task.status === "running") {
    return "Running... ";
  }
  return "";
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

async function resumeJob(jobId) {
  const normalizedId = jobId || (state.currentCollectJobRef ? jobStatusUrl(state.currentCollectJobRef).split("/").pop() : "");
  if (!normalizedId) return;
  setStatus("Resuming collection...", "running");
  setCollectRunning(true);
  const response = await fetch(jobStatusUrl(normalizedId).replace(/\/?$/, "/resume"), {
    method: "POST",
  });
  const data = await response.json();
  if (!response.ok) {
    setStatus(data.error || "Failed to resume.", "failed");
    setCollectRunning(false);
    return;
  }
  saveCurrentJobRef(data.status_url || data.job_id);
  pollJob(state.currentCollectJobRef);
}

async function retryJob(jobId) {
  const normalizedId = jobId || (state.currentCollectJobRef ? jobStatusUrl(state.currentCollectJobRef).split("/").pop() : "");
  if (!normalizedId) return;
  setStatus("Retrying failed tasks...", "running");
  setCollectRunning(true);
  const response = await fetch(jobStatusUrl(normalizedId).replace(/\/?$/, "/retry"), {
    method: "POST",
  });
  const data = await response.json();
  if (!response.ok) {
    setStatus(data.error || "Failed to retry.", "failed");
    setCollectRunning(false);
    return;
  }
  saveCurrentJobRef(data.status_url || data.job_id);
  pollJob(state.currentCollectJobRef);
}

async function retryTask(jobId, taskId) {
  if (!jobId || !taskId) return;
  setStatus("Retrying task...", "running");
  setCollectRunning(true);
  const response = await fetch(jobStatusUrl(jobId).replace(/\/?$/, `/queue/${taskId}/retry`), {
    method: "POST",
  });
  const data = await response.json();
  if (!response.ok) {
    setStatus(data.error || "Failed to retry task.", "failed");
    setCollectRunning(false);
    return;
  }
  saveCurrentJobRef(jobStatusUrl(jobId));
  pollJob(state.currentCollectJobRef);
}

async function removeTask(jobId, taskId) {
  if (!jobId || !taskId) return;
  const response = await fetch(appUrl(`/api/jobs/${jobId}/queue/${taskId}`), { method: "DELETE" });
  if (response.ok) {
    const jobResp = await fetch(appUrl(`/api/jobs/${jobId}`));
    if (jobResp.ok) {
      const job = await jobResp.json();
      renderQueuePanel(job);
    }
  }
}

function showAddTaskForm(jobId) {
  const panel = $("#task-queue");
  const existing = panel.querySelector(".add-task-form");
  if (existing) {
    existing.remove();
    return;
  }

  const form = document.createElement("div");
  form.className = "add-task-form";
  form.style.cssText = "margin-top:8px;padding:10px;border:1px solid var(--line);border-radius:6px;background:#fbfcfe;display:grid;gap:8px;";

  let confOptions = "";
  for (const conf of state.conferences) {
    confOptions += `<option value="${conf.id}">${escapeHtml(conf.display_name)}</option>`;
  }

  const currentYear = new Date().getFullYear();
  form.innerHTML = `
    <div style="display:flex;gap:8px;align-items:end;flex-wrap:wrap;">
      <label style="flex:1;min-width:160px;">Conference
        <select class="add-task-conf">${confOptions}</select>
      </label>
      <label style="width:80px;">Year
        <input type="number" class="add-task-year" min="1900" max="2099" value="${currentYear}">
      </label>
      <button class="secondary add-task-confirm" type="button" style="align-self:end;">Add</button>
      <button class="secondary add-task-cancel" type="button" style="align-self:end;">Cancel</button>
    </div>`;

  panel.appendChild(form);

  form.querySelector(".add-task-confirm").addEventListener("click", async () => {
    const confId = form.querySelector(".add-task-conf").value;
    const year = parseInt(form.querySelector(".add-task-year").value, 10);
    if (!confId || !year) return;
    const resp = await fetch(appUrl(`/api/jobs/${jobId}/queue`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ conference_id: confId, year }),
    });
    if (resp.ok) {
      form.remove();
      const jobResp = await fetch(appUrl(`/api/jobs/${jobId}`));
      if (jobResp.ok) {
        const job = await jobResp.json();
        renderQueuePanel(job);
      }
    }
  });

  form.querySelector(".add-task-cancel").addEventListener("click", () => form.remove());
}

function setupQueueDragDrop(panel, jobId) {
  const taskList = panel.querySelector(".task-list");
  if (!taskList) return;

  let draggedEl = null;

  taskList.addEventListener("dragstart", (e) => {
    const handle = e.target.closest(".task-drag-handle");
    if (!handle) return;
    const item = handle.closest(".task-item");
    if (!item || item.dataset.status !== "pending") return;
    draggedEl = item;
    item.classList.add("dragging");
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", item.dataset.taskId);
  });

  taskList.addEventListener("dragend", () => {
    if (draggedEl) {
      draggedEl.classList.remove("dragging");
      draggedEl = null;
    }
    for (const el of taskList.querySelectorAll(".drag-over")) {
      el.classList.remove("drag-over");
    }
  });

  taskList.addEventListener("dragover", (e) => {
    if (!draggedEl) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    const target = e.target.closest(".task-item");
    if (target && target !== draggedEl && target.dataset.status === "pending") {
      for (const el of taskList.querySelectorAll(".drag-over")) el.classList.remove("drag-over");
      target.classList.add("drag-over");
    }
  });

  taskList.addEventListener("dragleave", (e) => {
    const target = e.target.closest(".task-item");
    if (target) target.classList.remove("drag-over");
  });

  taskList.addEventListener("drop", async (e) => {
    e.preventDefault();
    if (!draggedEl) return;
    const target = e.target.closest(".task-item");
    if (!target || target === draggedEl || target.dataset.status !== "pending") return;
    target.classList.remove("drag-over");

    // Collect new order
    const items = [...taskList.querySelectorAll(".task-item")];
    const ids = items.map((el) => el.dataset.taskId);
    const fromIdx = ids.indexOf(draggedEl.dataset.taskId);
    const toIdx = ids.indexOf(target.dataset.taskId);
    if (fromIdx === -1 || toIdx === -1) return;
    ids.splice(fromIdx, 1);
    ids.splice(toIdx, 0, draggedEl.dataset.taskId);

    await fetch(appUrl(`/api/jobs/${jobId}/queue/reorder`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ task_ids: ids }),
    });

    const jobResp = await fetch(appUrl(`/api/jobs/${jobId}`));
    if (jobResp.ok) {
      const job = await jobResp.json();
      renderQueuePanel(job);
    }
  });
}

function setStatus(message, status) {
  const statusNode = $("#status");
  statusNode.textContent = message;
  statusNode.dataset.status = status;
}

function setCollectRunning(isRunning) {
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

function setSearchStatus(message, status) {
  const statusNode = $("#search-status");
  statusNode.textContent = message;
  statusNode.dataset.status = status;
}

function setIndexStatus(message, status) {
  const statusNode = $("#index-status");
  statusNode.textContent = message;
  statusNode.dataset.status = status;
}

async function loadSyncStatus() {
  try {
    const response = await fetch(appUrl("/api/sync/status"));
    const data = await response.json();
    renderSyncStatus(data);
  } catch (err) {
    renderSyncStatus({ error: "Failed to load sync status." });
  }
}

function renderSyncStatus(data) {
  const container = $("#sync-status");
  if (!container) return;
  if (data.error) {
    container.textContent = data.error;
    container.dataset.status = "failed";
    return;
  }
  const remoteCount = (data.remote_files || []).length;
  const localOnly = (data.local_only || []).length;
  const remoteOnly = (data.remote_only || []).length;
  const both = (data.both || []).length;
  container.textContent = `Remote: ${remoteCount} files (${both} shared, ${localOnly} local-only, ${remoteOnly} remote-only).`;
  container.dataset.status = "idle";
}

async function startSyncUpload() {
  setSyncRunning(true);
  $("#sync-logs").textContent = "Starting upload...";
  const response = await fetch(appUrl("/api/sync/upload"), { method: "POST" });
  const data = await response.json();
  if (!response.ok) {
    setSyncStatus(data.error || "Failed to start upload.", "failed");
    setSyncRunning(false);
    $("#sync-logs").textContent = data.error || "";
    return;
  }
  pollSyncJob(data.status_url || data.job_id);
}

async function startSyncDownload() {
  if (!confirm("Download will overwrite local files. Continue?")) return;
  setSyncRunning(true);
  $("#sync-logs").textContent = "Starting download...";
  const response = await fetch(appUrl("/api/sync/download"), { method: "POST" });
  const data = await response.json();
  if (!response.ok) {
    setSyncStatus(data.error || "Failed to start download.", "failed");
    setSyncRunning(false);
    $("#sync-logs").textContent = data.error || "";
    return;
  }
  pollSyncJob(data.status_url || data.job_id);
}

async function pollSyncJob(jobId) {
  const response = await fetch(jobStatusUrl(jobId));
  const job = await response.json();
  $("#sync-logs").textContent = (job.logs || []).join("\n") || "Waiting...";

  if (job.status === "completed") {
    setSyncStatus("Sync completed.", "completed");
    setSyncRunning(false);
    await loadSyncStatus();
    return;
  }
  if (job.status === "failed") {
    setSyncStatus(`Sync failed: ${job.error || "unknown error"}`, "failed");
    setSyncRunning(false);
    return;
  }
  window.setTimeout(() => pollSyncJob(jobId), 1500);
}

function setSyncStatus(message, status) {
  const node = $("#sync-status");
  if (!node) return;
  node.textContent = message;
  node.dataset.status = status;
}

function setSyncRunning(isRunning) {
  const uploadBtn = $("#sync-upload-button");
  const downloadBtn = $("#sync-download-button");
  if (uploadBtn) uploadBtn.disabled = isRunning;
  if (downloadBtn) downloadBtn.disabled = isRunning;
}

$("#collect-form").addEventListener("submit", startCollection);
$("#collect-stop-button").addEventListener("click", stopCollection);
$("#search-form").addEventListener("submit", searchPapers);
$("#index-button").addEventListener("click", startIndexBuild);
$("#collect-category").addEventListener("change", () => {
  renderCollectConferencePicker();
});
$("#collect-focus").addEventListener("change", () => {
  renderCollectConferencePicker();
});
$("#collect-ccf").addEventListener("change", () => {
  renderCollectConferencePicker();
});
$("#collect-select-visible").addEventListener("click", selectVisibleCollectConferences);
$("#collect-clear-visible").addEventListener("click", clearVisibleCollectConferences);
$("#collect-clear-all").addEventListener("click", clearAllCollectConferences);
$("#year-select-all").addEventListener("click", () => {
  for (const cb of document.querySelectorAll("#year-progress .year-checkbox")) {
    cb.checked = true;
    state.selectedYears.add(Number(cb.value));
    cb.closest(".year-progress-chip").classList.add("selected");
  }
});
$("#year-clear-all").addEventListener("click", () => {
  for (const cb of document.querySelectorAll("#year-progress .year-checkbox")) {
    cb.checked = false;
    cb.closest(".year-progress-chip").classList.remove("selected");
  }
  state.selectedYears.clear();
});
$("#search-category").addEventListener("change", () => {
  renderSearchConferencePicker();
});
$("#search-focus").addEventListener("change", () => {
  renderSearchConferencePicker();
});
$("#search-ccf").addEventListener("change", () => {
  renderSearchConferencePicker();
});
$("#search-select-visible").addEventListener("click", selectVisibleSearchConferences);
$("#search-clear-visible").addEventListener("click", clearVisibleSearchConferences);
$("#search-clear-all").addEventListener("click", clearAllSearchConferences);
$("#sync-upload-button").addEventListener("click", startSyncUpload);
$("#sync-download-button").addEventListener("click", startSyncDownload);
Promise.all([
  loadOptions().catch((error) => {
    setStatus(`Failed to load app options: ${error}`, "failed");
  }),
  loadFeeds().catch(() => {}),
  loadYearProgress().catch(() => {}),
  loadSyncStatus().catch(() => {}),
  loadJobHistory().catch(() => {}),
]);
