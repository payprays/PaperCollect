import { $, appUrl, jobStatusUrl, showToast } from "./core.js";

export async function loadSyncStatus() {
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

export async function startSyncUpload() {
  setSyncRunning(true);
  $("#sync-logs").textContent = "Starting upload...";
  try {
    const response = await fetch(appUrl("/api/sync/upload"), { method: "POST" });
    const data = await response.json();
    if (!response.ok) {
      setSyncStatus(data.error || "Failed to start upload.", "failed");
      setSyncRunning(false);
      $("#sync-logs").textContent = data.error || "";
      return;
    }
    pollSyncJob(data.status_url || data.job_id);
  } catch (error) {
    setSyncStatus(`Upload failed: ${error.message}`, "failed");
    setSyncRunning(false);
    showToast(`Upload failed: ${error.message}`, "error");
  }
}

export async function startSyncDownload() {
  if (!confirm("Download will overwrite local files. Continue?")) return;
  setSyncRunning(true);
  $("#sync-logs").textContent = "Starting download...";
  try {
    const response = await fetch(appUrl("/api/sync/download"), { method: "POST" });
    const data = await response.json();
    if (!response.ok) {
      setSyncStatus(data.error || "Failed to start download.", "failed");
      setSyncRunning(false);
      $("#sync-logs").textContent = data.error || "";
      return;
    }
    pollSyncJob(data.status_url || data.job_id);
  } catch (error) {
    setSyncStatus(`Download failed: ${error.message}`, "failed");
    setSyncRunning(false);
    showToast(`Download failed: ${error.message}`, "error");
  }
}

async function pollSyncJob(jobId) {
  try {
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
  } catch (error) {
    showToast(`Sync polling error: ${error.message}`, "error");
    setSyncRunning(false);
  }
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
