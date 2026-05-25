const state = {
  selectedFeedUrl: null,
  conferences: [],
  categories: [],
  focusTags: [],
  selectedCollectConferences: new Set(),
  selectedSearchConferences: new Set(),
};

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
  $("#year").value = guessDefaultYear(data.years);
  $("#limit").value = data.limit_per_conference || 0;

  await loadFeeds();
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
  return true;
}

function renderCollectConferencePicker() {
  const picker = $("#conference-picker");
  const visible = visibleCollectConferences();
  picker.innerHTML = "";

  if (!visible.length) {
    picker.innerHTML = '<p class="muted">No conferences match the current filters.</p>';
    updateCollectConferenceCount(0);
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
        }),
      );
    }
    groupNode.appendChild(list);
    picker.appendChild(groupNode);
  }

  updateCollectConferenceCount(visible.length);
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
  $("#conference-count").textContent =
    `${state.selectedCollectConferences.size} selected · ${visibleCount} visible`;
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
  $("#logs").textContent = "Waiting for collection logs...";
  $("#rss-link").classList.add("hidden");
  const selectedConferences = state.conferences
    .filter((conference) => state.selectedCollectConferences.has(conference.id))
    .map((conference) => conference.id);
  if (!selectedConferences.length) {
    setStatus("Choose at least one conference to collect.", "failed");
    $("#logs").textContent = "";
    return;
  }

  const payload = {
    conferences: selectedConferences,
    year: Number($("#year").value),
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
    $("#logs").textContent = data.error || "";
    return;
  }

  pollJob(data.status_url || data.job_id);
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
  const response = await fetch(jobStatusUrl(jobId));
  const job = await response.json();

  setStatus(renderJobStatus(job), job.status);
  $("#logs").textContent = (job.logs || []).join("\n") || "Waiting for collection logs...";

  if (job.status === "completed") {
    state.selectedFeedUrl = job.feed_url || (job.feed_urls || [])[0] || null;
    const link = $("#rss-link");
    if (state.selectedFeedUrl) {
      link.href = state.selectedFeedUrl;
      link.textContent = job.conference_count > 1
        ? "Open first RSS feed; all feeds are listed on the right"
        : `Open RSS feed for ${job.display_name || job.conference} ${job.year}`;
      link.classList.remove("hidden");
    }
    await loadFeeds();
    return;
  }

  if (job.status === "failed") {
    return;
  }

  window.setTimeout(() => pollJob(jobId), 1500);
}

function renderJobStatus(job) {
  if (job.status === "completed") {
    if (job.conference_count > 1) {
      return `Completed: saved ${job.paper_count || 0} papers across ${job.completed_count || 0} conferences; ${job.failed_count || 0} failed.`;
    }
    return `Completed: saved ${job.paper_count} papers for ${job.display_name || job.conference} ${job.year}.`;
  }
  if (job.status === "failed") {
    return `Failed: ${job.error || "unknown error"}`;
  }
  if (job.conference_count > 1) {
    return `Running batch collection for ${job.conference_count} conferences in ${job.year}...`;
  }
  return `Running collection for ${job.display_name || job.conference} ${job.year}...`;
}

function setStatus(message, status) {
  const statusNode = $("#status");
  statusNode.textContent = message;
  statusNode.dataset.status = status;
}

function setSearchStatus(message, status) {
  const statusNode = $("#search-status");
  statusNode.textContent = message;
  statusNode.dataset.status = status;
}

$("#collect-form").addEventListener("submit", startCollection);
$("#search-form").addEventListener("submit", searchPapers);
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
loadOptions().catch((error) => {
  setStatus(`Failed to load app options: ${error}`, "failed");
});
