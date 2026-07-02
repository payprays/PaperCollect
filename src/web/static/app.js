import { state, $, appUrl, setStatus, showToast, initTheme, initJobHistoryCollapse } from "./core.js";
import { fillCategorySelect, fillFocusSelect, fillCcfSelect, deriveCcfTiers, renderCollectConferencePicker, selectVisibleCollectConferences, clearVisibleCollectConferences, selectMissingCollectYears, renderSearchConferencePicker, selectVisibleSearchConferences, clearVisibleSearchConferences, clearAllSearchConferences } from "./conference.js";
import { fillYearSuggestions, loadYearProgress, renderYearProgress, renderCollectPreview } from "./year-progress.js";
import { loadJobHistory, startCollection, stopCollection } from "./jobs.js";
import { loadFeeds } from "./feeds.js";
import { searchPapers, startIndexBuild } from "./search.js";
import { loadSyncStatus, startSyncUpload, startSyncDownload } from "./sync.js";

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

// Event bindings
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
$("#collect-select-missing-years").addEventListener("click", selectMissingCollectYears);
$("#collect-select-visible").addEventListener("click", selectVisibleCollectConferences);
$("#collect-clear-visible").addEventListener("click", clearVisibleCollectConferences);
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

// Init theme and collapse state
initTheme();
initJobHistoryCollapse();

// Tab switching
for (const btn of document.querySelectorAll(".tab-btn")) {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
    document.querySelectorAll("[data-tab-content]").forEach(p => p.classList.remove("active"));
    btn.classList.add("active");
    const target = document.querySelector(`[data-tab-content="${btn.dataset.tab}"]`);
    if (target) target.classList.add("active");
    localStorage.setItem("pc_active_tab", btn.dataset.tab);
  });
}

// Restore last active tab
const savedTab = localStorage.getItem("pc_active_tab") || "collect";
const tabBtn = document.querySelector(`.tab-btn[data-tab="${savedTab}"]`);
if (tabBtn) tabBtn.click();

// Init data
Promise.all([
  loadOptions()
    .then(() => loadYearProgress())
    .catch((error) => {
      setStatus(`Failed to load app options: ${error}`, "failed");
      showToast(`Failed to load options: ${error.message || error}`, "error");
    }),
  loadFeeds().catch((error) => {
    showToast(`Failed to load feeds: ${error.message || error}`, "error");
  }),
  loadSyncStatus().catch((error) => {
    showToast(`Failed to load sync status: ${error.message || error}`, "error");
  }),
  loadJobHistory().catch((error) => {
    showToast(`Failed to load job history: ${error.message || error}`, "error");
  }),
]);
