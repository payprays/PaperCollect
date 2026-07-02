import { state, $, appUrl, jobStatusUrl, escapeHtml, setStatus, setCollectRunning, saveCurrentJobRef, showToast } from "./core.js";

export function renderJobStatus(job) {
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

export function renderIndexJobStatus(job) {
  if (job.status === "completed") {
    return `Index ready: ${job.paper_count || 0} papers in ${job.collection}.`;
  }
  if (job.status === "failed") {
    return `Index failed: ${job.error || "unknown error"}`;
  }
  return `Building vector index for ${job.collection || "papers"}...`;
}

export function renderQueuePanel(job) {
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

  // Dynamic imports to avoid circular dependencies
  import("./jobs.js").then((jobsMod) => {
    const resumeBtn = panel.querySelector(".task-queue-resume");
    if (resumeBtn) {
      resumeBtn.addEventListener("click", () => jobsMod.resumeJob(jobId));
    }
    const retryBtn = panel.querySelector(".task-queue-retry");
    if (retryBtn) {
      retryBtn.addEventListener("click", () => jobsMod.retryJob(jobId));
    }
    for (const btn of panel.querySelectorAll(".task-retry-btn")) {
      btn.addEventListener("click", () => jobsMod.retryTask(btn.dataset.jobId, btn.dataset.taskId));
    }
  });

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

async function removeTask(jobId, taskId) {
  if (!jobId || !taskId) return;
  try {
    const response = await fetch(appUrl(`/api/jobs/${jobId}/queue/${taskId}`), { method: "DELETE" });
    if (response.ok) {
      const jobResp = await fetch(appUrl(`/api/jobs/${jobId}`));
      if (jobResp.ok) {
        const job = await jobResp.json();
        renderQueuePanel(job);
      }
    } else {
      const data = await response.json().catch(() => ({}));
      showToast(`Failed to remove task: ${data.error || response.status}`, "error");
    }
  } catch (error) {
    showToast(`Failed to remove task: ${error.message}`, "error");
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

  let confOptions = "";
  for (const conf of state.conferences) {
    confOptions += `<option value="${conf.id}">${escapeHtml(conf.display_name)}</option>`;
  }

  const currentYear = new Date().getFullYear();
  form.innerHTML = `
    <div class="add-task-row">
      <label class="add-task-field">Conference
        <select class="add-task-conf">${confOptions}</select>
      </label>
      <label class="add-task-limit">Year
        <input type="number" class="add-task-year" min="1900" max="2099" value="${currentYear}">
      </label>
      <div class="add-task-actions">
        <button class="secondary add-task-confirm" type="button">Add</button>
        <button class="secondary add-task-cancel" type="button">Cancel</button>
      </div>
    </div>`;

  panel.appendChild(form);

  form.querySelector(".add-task-confirm").addEventListener("click", async () => {
    const confId = form.querySelector(".add-task-conf").value;
    const year = parseInt(form.querySelector(".add-task-year").value, 10);
    if (!confId || !year) return;
    try {
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
      } else {
        const data = await resp.json().catch(() => ({}));
        showToast(`Failed to add task: ${data.error || resp.status}`, "error");
      }
    } catch (error) {
      showToast(`Failed to add task: ${error.message}`, "error");
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

    try {
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
    } catch (error) {
      showToast(`Failed to reorder tasks: ${error.message}`, "error");
    }
  });
}
