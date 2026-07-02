import { state, $, appUrl, jobStatusUrl, escapeHtml, formatTimestamp, setStatus, setCollectRunning, setIndexStatus, saveCurrentJobRef, jobStatusShort, jobSummaryText, jobTypeIcon, showToast } from "./core.js";
import { renderQueuePanel, renderJobStatus, renderIndexJobStatus } from "./task-queue.js";
import { collectTaskPairs, loadYearProgress } from "./year-progress.js";
import { loadFeeds } from "./feeds.js";

export async function loadJobHistory() {
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
    // job history is optional; show toast but don't block
    showToast(`Failed to load job history: ${err.message}`, "error");
  }
}

export function renderJobHistory() {
  const container = $("#job-history");
  if (!container) return;

  const jobs = state.jobHistory;
  if (!jobs.length) {
    container.innerHTML = '<div class="job-history-empty">No jobs yet.</div>';
    return;
  }

  let html = "";
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
      <span class="job-history-status job-history-time">${isActive ? "● Active" : ""}</span>
      <button class="job-history-delete" data-job-id="${job.id}" title="Delete job">✕</button>
    </div>`;
  }
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

export async function viewJob(jobId) {
  try {
    const response = await fetch(appUrl(`/api/jobs/${jobId}`));
    const job = await response.json();
    if (!response.ok) {
      showToast(`Failed to load job: ${job.error || response.status}`, "error");
      return;
    }

    if (job.type === "collection" && job.queue && job.queue.length) {
      // Switch to Collect tab so user can see the job
      const collectTab = document.querySelector('.tab-btn[data-tab="collect"]');
      if (collectTab && !collectTab.classList.contains("active")) collectTab.click();

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
  } catch (error) {
    showToast(`Failed to load job: ${error.message}`, "error");
  }
}

export async function deleteJob(jobId) {
  if (!confirm("Delete this job?")) return;
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
    } else {
      const data = await response.json().catch(() => ({}));
      showToast(`Failed to delete job: ${data.error || response.status}`, "error");
    }
  } catch (error) {
    showToast(`Failed to delete job: ${error.message}`, "error");
  }
}

export async function pollJob(jobId) {
  const expectedUrl = jobStatusUrl(jobId);
  if (state.currentCollectJobRef && expectedUrl !== jobStatusUrl(state.currentCollectJobRef)) {
    return;
  }

  try {
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
      await Promise.all([loadFeeds(), loadYearProgress(), loadJobHistory()]);
      setCollectRunning(false);
      renderQueuePanel(job);
      return;
    }

    if (job.status === "failed" || job.status === "stopped") {
      if (job.status === "stopped") {
        await Promise.all([loadFeeds(), loadYearProgress(), loadJobHistory()]);
      } else {
        await loadJobHistory();
      }
      setCollectRunning(false);
      renderQueuePanel(job);
      return;
    }

    const interval = job.status === "running" ? 1500 : 3000;
    state.collectPollTimer = window.setTimeout(() => pollJob(jobId), interval);
  } catch (error) {
    showToast(`Polling error: ${error.message}`, "error");
    setCollectRunning(false);
  }
}

export async function pollIndexJob(jobId) {
  try {
    const response = await fetch(jobStatusUrl(jobId));
    const job = await response.json();

    setIndexStatus(renderIndexJobStatus(job), job.status);
    $("#index-logs").textContent = (job.logs || []).join("\n") || "Waiting for index logs...";

    if (job.status === "completed" || job.status === "failed") {
      return;
    }

    window.setTimeout(() => pollIndexJob(jobId), 1500);
  } catch (error) {
    showToast(`Index polling error: ${error.message}`, "error");
    setIndexStatus("Index polling failed.", "failed");
  }
}

export async function startCollection(event) {
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
  const explicitTasks = collectTaskPairs();
  if (!selectedYears.length && !explicitTasks.length) {
    setStatus("Choose at least one year to collect.", "failed");
    setCollectRunning(false);
    $("#logs").textContent = "";
    return;
  }

  const payload = explicitTasks.length
    ? {
        tasks: explicitTasks,
        limit: Number($("#limit").value),
      }
    : {
        conferences: selectedConferences,
        years: selectedYears,
        limit: Number($("#limit").value),
      };

  try {
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
  } catch (error) {
    setStatus(`Failed to start collection: ${error.message}`, "failed");
    setCollectRunning(false);
    showToast(`Collection failed: ${error.message}`, "error");
  }
}

export async function stopCollection() {
  if (!state.currentCollectJobRef) {
    return;
  }

  const stopButton = $("#collect-stop-button");
  stopButton.disabled = true;
  stopButton.textContent = "Stopping...";
  setStatus("Stopping collection after the current conference...", "running");

  try {
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
  } catch (error) {
    stopButton.disabled = false;
    stopButton.textContent = "Stop";
    setStatus(`Failed to stop: ${error.message}`, "failed");
    showToast(`Stop failed: ${error.message}`, "error");
  }
}

export async function resumeJob(jobId) {
  const normalizedId = jobId || (state.currentCollectJobRef ? jobStatusUrl(state.currentCollectJobRef).split("/").pop() : "");
  if (!normalizedId) return;
  setStatus("Resuming collection...", "running");
  setCollectRunning(true);
  try {
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
  } catch (error) {
    setStatus(`Failed to resume: ${error.message}`, "failed");
    setCollectRunning(false);
    showToast(`Resume failed: ${error.message}`, "error");
  }
}

export async function retryJob(jobId) {
  const normalizedId = jobId || (state.currentCollectJobRef ? jobStatusUrl(state.currentCollectJobRef).split("/").pop() : "");
  if (!normalizedId) return;
  setStatus("Retrying failed tasks...", "running");
  setCollectRunning(true);
  try {
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
  } catch (error) {
    setStatus(`Failed to retry: ${error.message}`, "failed");
    setCollectRunning(false);
    showToast(`Retry failed: ${error.message}`, "error");
  }
}

export async function retryTask(jobId, taskId) {
  if (!jobId || !taskId) return;
  setStatus("Retrying task...", "running");
  setCollectRunning(true);
  try {
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
  } catch (error) {
    setStatus(`Failed to retry task: ${error.message}`, "failed");
    setCollectRunning(false);
    showToast(`Task retry failed: ${error.message}`, "error");
  }
}
