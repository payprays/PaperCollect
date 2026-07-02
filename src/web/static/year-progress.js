import { state, $, appUrl, showToast } from "./core.js";
import { renderCollectConferencePicker } from "./conference.js";

export function fillYearSuggestions(datalist, values) {
  datalist.innerHTML = "";
  for (const value of values || []) {
    const option = document.createElement("option");
    option.value = value;
    datalist.appendChild(option);
  }
}

export function renderCollectPreview() {
  const container = $("#collect-preview");
  if (!container) return;

  const selectedIds = state.selectedCollectConferences;
  const selectedYears = state.selectedYears;
  const explicitTasks = collectTaskPairs();

  if (!selectedIds.size || (!selectedYears.size && !explicitTasks.length)) {
    container.classList.add("hidden");
    container.innerHTML = "";
    return;
  }

  container.classList.remove("hidden");

  // Build preview data from the exact conference x year queue submitted to /api/collect.
  const previewItems = [];
  let totalTasks = 0;

  if (state.selectedCollectTasks) {
    for (const conference of state.conferences || []) {
      if (!selectedIds.has(conference.id)) continue;
      const years = state.selectedCollectTasks.get(conference.id);
      if (!years || !years.size) continue;
      const sortedYears = [...years].sort((a, b) => a - b);

      totalTasks += sortedYears.length;
      previewItems.push({
        name: conference.display_name,
        years: sortedYears,
      });
    }
  } else {
    const sortedSelectedYears = [...selectedYears].sort((a, b) => a - b);
    for (const conference of state.conferences || []) {
      if (!selectedIds.has(conference.id)) continue;
      if (!sortedSelectedYears.length) continue;

      totalTasks += sortedSelectedYears.length;
      previewItems.push({
        name: conference.display_name,
        years: sortedSelectedYears,
      });
    }
  }

  if (!previewItems.length) {
    container.innerHTML = '<div class="collect-preview-empty">No tasks to collect. Select conferences and years.</div>';
    return;
  }

  const COLLAPSE_THRESHOLD = 5;
  const visibleItems = previewItems.slice(0, COLLAPSE_THRESHOLD);
  const remaining = previewItems.length - COLLAPSE_THRESHOLD;

  const conferenceLabel = previewItems.length === 1 ? "conference" : "conferences";
  const taskLabel = state.selectedCollectTasks
    ? (totalTasks === 1 ? "missing task" : "missing tasks")
    : (totalTasks === 1 ? "task" : "tasks");
  let html = `<div class="collect-preview-summary">${previewItems.length} ${conferenceLabel} × ${totalTasks} ${taskLabel}</div>`;
  html += '<div class="collect-preview-details">';
  for (const item of visibleItems) {
    const yearStr = formatYearRanges(item.years);
    html += `<div class="collect-preview-item"><span class="collect-preview-conference">${item.name}</span><span class="collect-preview-years">${yearStr}</span></div>`;
  }
  if (remaining > 0) {
    html += `<div class="collect-preview-more">and ${remaining} more...</div>`;
  }
  html += '</div>';
  container.innerHTML = html;
}

export function collectTaskPairs() {
  if (!state.selectedCollectTasks) {
    return [];
  }

  const tasks = [];
  for (const conference of state.conferences || []) {
    if (!state.selectedCollectConferences.has(conference.id)) continue;
    const years = state.selectedCollectTasks.get(conference.id);
    if (!years) continue;
    for (const year of [...years].sort((a, b) => a - b)) {
      tasks.push({ conference: conference.id, year });
    }
  }
  return tasks;
}

function formatYearRanges(years) {
  if (years.length <= 3) return years.join(", ");
  // Format as ranges: 2023-2026
  const ranges = [];
  let start = years[0];
  let end = years[0];
  for (let i = 1; i < years.length; i++) {
    if (years[i] === end + 1) {
      end = years[i];
    } else {
      ranges.push(start === end ? `${start}` : `${start}-${end}`);
      start = years[i];
      end = years[i];
    }
  }
  ranges.push(start === end ? `${start}` : `${start}-${end}`);
  return ranges.join(", ");
}

export async function loadYearProgress(customYears, autoSelectMissing = true) {
  try {
    let url = appUrl("/api/year-progress");
    if (customYears && customYears.length) {
      url += `?years=${customYears.join(",")}`;
    }
    const response = await fetch(url);
    const data = await response.json();
    state.yearProgress = data.progress || [];
    renderYearProgress(state.yearProgress, autoSelectMissing);
    renderCollectConferencePicker();
  } catch (err) {
    showToast(`Failed to load year progress: ${err.message}`, "error");
  }
}

export function selectYearsForConferences(conferenceIds, mode = "missing") {
  state.yearSelectionTouched = true;
  const ids = new Set(conferenceIds || []);
  state.selectedYears.clear();
  state.selectedCollectTasks = mode === "missing" ? new Map() : null;
  for (const entry of state.yearProgress || []) {
    if (ids.size && !ids.has(entry.conference_id)) continue;
    const years = mode === "all" ? entry.configured_years : entry.missing_years;
    const taskYears = [];
    for (const y of years || []) {
      const year = Number(y);
      state.selectedYears.add(year);
      taskYears.push(year);
    }
    if (mode === "missing" && taskYears.length) {
      state.selectedCollectTasks.set(entry.conference_id, new Set(taskYears));
    }
  }
  renderYearProgress(state.yearProgress, false);
  renderCollectPreview();
}

export function renderYearProgress(progress, autoSelectMissing = false) {
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

  // Auto-select missing years when conferences change.
  if (autoSelectMissing && !state.yearSelectionTouched) {
    state.selectedYears.clear();
    if (state.selectedCollectConferences.size) {
      for (const y of sortedYears) {
        const info = yearMap.get(y);
        if (info && info.missing.size > 0) state.selectedYears.add(y);
      }
    }
  }

  container.classList.remove("hidden");
  let html = '<div class="year-progress-header"><span class="year-progress-title">Year progress</span>';
  html += '<span class="year-custom-input"><input type="number" id="custom-year-input" min="1900" max="2099" placeholder="Year"><button id="custom-year-add" class="secondary" type="button">+</button></span>';
  html += '</div>';
  html += '<div class="year-progress-grid">';
  for (const y of sortedYears) {
    const info = yearMap.get(y) || { saved: new Set(), missing: new Set() };
    const total = info.saved.size + info.missing.size;
    const savedCount = info.saved.size;
    const missingCount = info.missing.size;
    const pct = total > 0 ? Math.round((savedCount / total) * 100) : 0;
    const checked = state.selectedYears.has(y);
    html += `<label class="year-progress-chip${checked ? ' selected' : ''}" title="${savedCount}/${total} saved${missingCount ? `; ${missingCount} missing` : ''}">
      <input type="checkbox" value="${y}" ${checked ? 'checked' : ''} class="year-checkbox">
      <span class="year-chip-label">${y}</span>
      <span class="year-chip-bar"><span class="year-chip-fill" style="width:${pct}%"></span></span>
      <span class="year-chip-count">${savedCount}/${total}</span>
    </label>`;
  }
  html += '</div>';
  container.innerHTML = html;

  // Bind checkboxes — toggle year for collection.
  for (const cb of container.querySelectorAll(".year-checkbox")) {
    cb.addEventListener("change", () => {
      state.yearSelectionTouched = true;
      state.selectedCollectTasks = null;
      const val = Number(cb.value);
      if (cb.checked) state.selectedYears.add(val);
      else state.selectedYears.delete(val);
      cb.closest(".year-progress-chip").classList.toggle("selected", cb.checked);
      renderCollectPreview();
    });
  }

  // Bind custom year input.
  const customInput = container.querySelector("#custom-year-input");
  const customAdd = container.querySelector("#custom-year-add");
  if (customInput && customAdd) {
    const addCustomYear = () => {
      const val = parseInt(customInput.value, 10);
      if (val >= 1900 && val <= 2099) {
        state.yearSelectionTouched = true;
        state.selectedCollectTasks = null;
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

  // Update collect preview.
  renderCollectPreview();
}
