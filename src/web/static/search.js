import { state, $, appUrl, setSearchStatus, setIndexStatus, truncate, showToast } from "./core.js";
import { categoryLabel, visibleSearchConferences } from "./conference.js";

let searchOffset = 0;
const SEARCH_LIMIT = 20;

export async function searchPapers(event) {
  event.preventDefault();
  searchOffset = 0;
  await doSearch();
}

async function doSearch(append = false) {
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
  params.set("limit", String(SEARCH_LIMIT));
  if (searchOffset) params.set("offset", String(searchOffset));

  setSearchStatus("Searching...", "running");
  try {
    const response = await fetch(appUrl(`/api/search?${params.toString()}`));
    const data = await response.json();
    if (!response.ok) {
      setSearchStatus(data.error || "Search failed.", "failed");
      return;
    }

    renderSearchResults(data.results || [], append);
    const total = (data.results || []).length;
    setSearchStatus(`Found ${total + searchOffset} papers with ${searchModeLabel(data.mode || mode)}.`, "completed");

    if (total >= SEARCH_LIMIT) {
      showLoadMore();
    }
  } catch (error) {
    setSearchStatus(`Search failed: ${error.message}`, "failed");
    showToast(`Search failed: ${error.message}`, "error");
  }
}

export async function startIndexBuild() {
  setIndexStatus("Starting vector index rebuild...", "running");
  $("#index-logs").textContent = "Waiting for index logs...";

  try {
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

    // Dynamic import to avoid circular dependency
    import("./jobs.js").then((m) => m.pollIndexJob(data.status_url || data.job_id));
  } catch (error) {
    setIndexStatus(`Failed to start index rebuild: ${error.message}`, "failed");
    showToast(`Index rebuild failed: ${error.message}`, "error");
  }
}

function renderSearchResults(results, append = false) {
  const root = $("#search-results");
  if (!append) root.innerHTML = "";
  if (!results.length && !append) {
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

function showLoadMore() {
  let btn = $("#search-load-more");
  if (!btn) {
    btn = document.createElement("button");
    btn.id = "search-load-more";
    btn.className = "secondary search-load-more";
    btn.textContent = "Load more";
    btn.addEventListener("click", async () => {
      searchOffset += SEARCH_LIMIT;
      btn.textContent = "Loading...";
      btn.disabled = true;
      await doSearch(true);
      btn.remove();
    });
    $("#search-results").after(btn);
  }
}

function searchModeLabel(mode) {
  if (mode === "agentic") {
    return "agentic hybrid search";
  }
  return mode === "concept" ? "concept semantic search" : "keyword search";
}
