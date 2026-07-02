import { state, $ } from "./core.js";

export function fillCategorySelect(select, categories, includeAll = false) {
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

export function fillFocusSelect(select, focusTags, includeAll = false) {
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

export function fillCcfSelect(select, tiers, includeAll = false) {
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

export function deriveCcfTiers(conferences) {
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

export function visibleCollectConferences() {
  return visibleConferences({
    category: $("#collect-category").value || null,
    focus: $("#collect-focus").value || null,
    ccf: $("#collect-ccf").value || null,
  });
}

export function visibleSearchConferences() {
  return visibleConferences({
    category: $("#search-category").value || null,
    focus: $("#search-focus").value || null,
    ccf: $("#search-ccf").value || null,
  });
}

export function visibleConferences(filters) {
  return state.conferences.filter((conference) => conferenceMatchesFilters(conference, filters));
}

export function conferenceMatchesFilters(conference, filters) {
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

export function renderCollectConferencePicker() {
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
          state.selectedCollectTasks = null;
          // Dynamic import to avoid circular dependency
          import("./year-progress.js").then((m) => m.loadYearProgress());
        }),
      );
    }
    groupNode.appendChild(list);
    picker.appendChild(groupNode);
  }

  updateCollectConferenceCount(visible.length);
}

export function selectVisibleCollectConferences() {
  const visible = visibleCollectConferences();
  state.yearSelectionTouched = true;
  state.selectedCollectTasks = null;
  state.selectedCollectConferences.clear();
  for (const conference of visible) {
    state.selectedCollectConferences.add(conference.id);
  }
  renderCollectConferencePicker();
  $("#collect-preview").classList.add("hidden");
  $("#collect-preview").innerHTML = "";
  import("./year-progress.js").then(async (m) => {
    if (!state.yearProgress.length) {
      await m.loadYearProgress([...state.customYears], false);
    }
    m.selectYearsForConferences(
      visible.map((conference) => conference.id),
      "all",
    );
  });
}

export function clearVisibleCollectConferences() {
  state.selectedCollectTasks = null;
  for (const conference of visibleCollectConferences()) {
    state.selectedCollectConferences.delete(conference.id);
  }
  renderCollectConferencePicker();
  import("./year-progress.js").then((m) => m.loadYearProgress());
}

export function selectMissingCollectYears() {
  state.yearSelectionTouched = true;
  const selectedIds = [...state.selectedCollectConferences];
  const scopeIds = selectedIds.length
    ? selectedIds
    : visibleCollectConferences().map((conference) => conference.id);
  $("#collect-preview").classList.add("hidden");
  $("#collect-preview").innerHTML = "";
  import("./year-progress.js").then(async (m) => {
    if (!state.yearProgress.length) {
      await m.loadYearProgress([...state.customYears], false);
    }
    m.selectYearsForConferences(scopeIds, "missing");
  });
}

export function updateCollectConferenceCount(visibleCount) {
  $("#conference-count").textContent =
    `${state.selectedCollectConferences.size} selected · ${visibleCount} visible`;
}

export function renderSearchConferencePicker() {
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

export function selectVisibleSearchConferences() {
  for (const conference of visibleSearchConferences()) {
    state.selectedSearchConferences.add(conference.id);
  }
  renderSearchConferencePicker();
}

export function clearVisibleSearchConferences() {
  for (const conference of visibleSearchConferences()) {
    state.selectedSearchConferences.delete(conference.id);
  }
  renderSearchConferencePicker();
}

export function clearAllSearchConferences() {
  state.selectedSearchConferences.clear();
  renderSearchConferencePicker();
}

export function updateSearchConferenceCount(visibleCount) {
  const selected = state.selectedSearchConferences.size;
  $("#search-conference-count").textContent = selected
    ? `${selected} selected · ${visibleCount} visible`
    : `All conferences · ${visibleCount} visible`;
}

export function groupConferences(conferences) {
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

export function conferenceCheckbox(conference, selection, onChange) {
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

  // Show missing years indicator from year progress data.
  const progress = (state.yearProgress || []).find((p) => p.conference_id === conference.id);
  if (progress && progress.missing_years && progress.missing_years.length) {
    const badge = document.createElement("span");
    badge.className = "conference-missing-badge";
    badge.textContent = progress.missing_years.sort((a, b) => a - b).join(", ");
    badge.title = `Missing: ${progress.missing_years.join(", ")}`;
    option.appendChild(badge);
  }

  return option;
}

export function conferenceSummary(conference) {
  const parts = [`CCF ${conferenceCcf(conference) || "N"}`];
  if ((conference.focus_tags || []).length) {
    parts.push(conference.focus_tags.join(", "));
  }
  return parts.join(" · ");
}

export function conferenceCcf(conference) {
  return String((conference.tier || {}).ccf || "").trim().toUpperCase();
}

export function categoryLabel(categoryId) {
  const category = state.categories.find((item) => item.id === categoryId);
  return category ? formatCategoryLabel(category) : categoryId;
}

export function formatCategoryLabel(category) {
  const localName = category.name && category.name !== category.id ? category.name : "";
  const englishName = category.name_en && category.name_en !== category.id ? category.name_en : "";
  const label =
    localName && englishName && localName !== englishName
      ? `${localName} / ${englishName}`
      : localName || englishName || category.id;
  return `${category.id} · ${label}`;
}
