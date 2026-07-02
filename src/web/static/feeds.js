import { $, appUrl, showToast } from "./core.js";

export async function loadFeeds() {
  const list = $("#feeds");
  list.innerHTML = '<li><span class="spinner"></span> Loading...</li>';
  try {
    const response = await fetch(appUrl("/api/feeds"));
    const data = await response.json();
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
  } catch (error) {
    list.innerHTML = "<li>Failed to load feeds.</li>";
    throw error;
  }
}
