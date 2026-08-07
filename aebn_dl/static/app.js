const form = document.querySelector("#download-form");
const formMessage = document.querySelector("#form-message");
const infoButton = document.querySelector("#info-button");
const movieInfo = document.querySelector("#movie-info");
const jobsList = document.querySelector("#jobs-list");
const historyList = document.querySelector("#history-list");
const playerEmpty = document.querySelector("#player-empty");
const playerWrap = document.querySelector("#player-wrap");
const videoPlayer = document.querySelector("#video-player");
const playerTitle = document.querySelector("#player-title");
const playerPath = document.querySelector("#player-path");
const refreshJobs = document.querySelector("#refresh-jobs");
const clearCompleted = document.querySelector("#clear-completed");
const sockets = new Map();
let activeMediaUrl = "";

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function setMessage(message, isError = false) {
  formMessage.textContent = message;
  formMessage.classList.toggle("message-error", isError);
}

function statusLabel(status) {
  return `<span class="status status-${escapeHtml(status)}">${escapeHtml(status)}</span>`;
}

function subtitleControls(job, output) {
  if (!output.exists || job.status !== "completed") {
    return "";
  }
  const status = output.subtitle_status || "idle";
  const link = output.subtitle_url ? `<a class="text-button" href="${escapeHtml(output.subtitle_url)}" download>Subtitle</a>` : "";
  const disabled = status === "running" ? "disabled" : "";
  const label = status === "running" ? "Subtitles..." : "Generate subtitles";
  const button = `<button class="text-button" type="button" data-subtitle-job="${escapeHtml(job.id)}" data-subtitle-output="${escapeHtml(output.index)}" ${disabled}>${label}</button>`;
  const error = output.subtitle_error ? `<small class="error-text">${escapeHtml(output.subtitle_error)}</small>` : "";
  return `<span class="subtitle-actions"><span class="subtitle-state">${escapeHtml(status)}</span>${link}${button}${error}</span>`;
}

function renderJobs(jobs) {
  renderHistory(jobs);

  if (!jobs.length) {
    jobsList.innerHTML = `<div class="empty-state">No jobs yet. Start a download to see progress here.</div>`;
    return;
  }

  jobsList.innerHTML = jobs.map((job) => {
    const logs = (job.logs || []).slice(-12).map((line) => escapeHtml(line)).join("\n");
    const outputs = (job.outputs || []).map((output) => {
      const playButton = output.media_url ? `<button class="text-button" type="button" data-media-url="${escapeHtml(output.media_url)}" data-media-title="${escapeHtml(output.name)}" data-media-path="${escapeHtml(output.path)}" data-subtitle-url="${escapeHtml(output.subtitle_url || "")}">Play</button>` : "";
      return `<li><span>${escapeHtml(output.path)}</span><span class="output-actions">${playButton}${subtitleControls(job, output)}</span></li>`;
    }).join("");
    const error = job.error ? `<p class="error-text">${escapeHtml(job.error)}</p>` : "";
    const outputsBlock = outputs ? `<ul class="outputs">${outputs}</ul>` : "";
    const controls = job.cancellable
      ? `<button class="text-button danger-action" type="button" data-cancel-job="${escapeHtml(job.id)}">Cancel</button>`
      : `<button class="text-button" type="button" data-delete-job="${escapeHtml(job.id)}">Delete</button>`;
    return `
      <article class="job-card" data-job-id="${escapeHtml(job.id)}">
        <div class="job-card__header">
          <div>
            <h3>${escapeHtml(job.url)}</h3>
            <p>Job ${escapeHtml(job.id)} · ${escapeHtml(job.target_stream)} · ${job.resolution ?? "highest"}p</p>
          </div>
          <div class="job-actions">${statusLabel(job.status)}${controls}</div>
        </div>
        ${error}
        ${outputsBlock}
        <pre class="terminal job-log">${logs || "Waiting for logs..."}</pre>
      </article>`;
  }).join("");

  jobs.forEach((job) => {
    if (!["completed", "failed", "cancelled"].includes(job.status)) {
      connectJob(job.id);
    }
  });
}

function playableOutputs(jobs) {
  return jobs.flatMap((job) => (job.outputs || [])
    .filter((output) => output.media_url)
    .map((output) => ({ ...output, job })));
}

function renderHistory(jobs) {
  const items = playableOutputs(jobs);
  if (!items.length) {
    historyList.innerHTML = `<div class="empty-state">No playable downloads yet.</div>`;
    return;
  }

  historyList.innerHTML = items.map((item) => `
    <button class="history-item${item.media_url === activeMediaUrl ? " is-active" : ""}" type="button" data-media-url="${escapeHtml(item.media_url)}" data-media-title="${escapeHtml(item.name)}" data-media-path="${escapeHtml(item.path)}" data-subtitle-url="${escapeHtml(item.subtitle_url || "")}">
      <strong>${escapeHtml(item.name)}</strong>
      <span>${escapeHtml(item.job.updated_at)} · job ${escapeHtml(item.job.id)} · subtitles ${escapeHtml(item.subtitle_status)}</span>
    </button>
  `).join("");
}

function playMedia(url, title, path, subtitleUrl = "") {
  activeMediaUrl = url;
  playerEmpty.hidden = true;
  playerWrap.hidden = false;
  videoPlayer.src = url;
  videoPlayer.querySelectorAll("track").forEach((track) => track.remove());
  if (subtitleUrl) {
    const track = document.createElement("track");
    track.kind = "subtitles";
    track.label = "Auto subtitles";
    track.srclang = "en";
    track.src = subtitleUrl;
    track.default = true;
    videoPlayer.append(track);
  }
  playerTitle.textContent = title;
  playerPath.textContent = path;
  videoPlayer.load();
  videoPlayer.play().catch(() => {
    // Browsers may block autoplay; controls remain available.
  });
  document.querySelectorAll(".history-item").forEach((item) => {
    item.classList.toggle("is-active", item.dataset.mediaUrl === url);
  });
}

async function loadJobs() {
  const response = await fetch("/jobs");
  const payload = await response.json();
  renderJobs(payload.jobs || []);
}

function connectJob(jobId) {
  if (sockets.has(jobId)) {
    return;
  }
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${protocol}://${window.location.host}/ws/jobs/${jobId}`);
  sockets.set(jobId, socket);
  socket.onmessage = () => loadJobs();
  socket.onclose = () => sockets.delete(jobId);
  socket.onerror = () => sockets.delete(jobId);
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  setMessage("Starting download...");
  try {
    const response = await fetch(form.action, { method: "POST", body: new FormData(form) });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "Failed to start download.");
    }
    (payload.jobs || []).forEach((job) => connectJob(job.job_id));
    if ((payload.jobs || []).length > 1) {
      setMessage(`Started ${payload.jobs.length} queued jobs`);
    } else {
      setMessage(`Started job ${payload.job_id}`);
    }
    await loadJobs();
  } catch (error) {
    setMessage(error.message, true);
  }
});

infoButton.addEventListener("click", async () => {
  movieInfo.textContent = "Fetching movie info...";
  try {
    const response = await fetch("/info", { method: "POST", body: new FormData(form) });
    const text = await response.text();
    if (!response.ok) {
      throw new Error(text || "Failed to fetch movie info.");
    }
    movieInfo.textContent = text;
  } catch (error) {
    movieInfo.textContent = error.message;
  }
});

refreshJobs.addEventListener("click", loadJobs);

clearCompleted.addEventListener("click", async () => {
  await fetch("/jobs", { method: "DELETE" });
  await loadJobs();
});

document.addEventListener("click", (event) => {
  const cancelTarget = event.target.closest("[data-cancel-job]");
  if (cancelTarget) {
    fetch(`/jobs/${cancelTarget.dataset.cancelJob}/cancel`, { method: "POST" })
      .then(() => loadJobs())
      .catch(() => loadJobs());
    return;
  }

  const deleteTarget = event.target.closest("[data-delete-job]");
  if (deleteTarget) {
    fetch(`/jobs/${deleteTarget.dataset.deleteJob}`, { method: "DELETE" })
      .then(() => loadJobs())
      .catch(() => loadJobs());
    return;
  }

  const subtitleTarget = event.target.closest("[data-subtitle-job]");
  if (subtitleTarget) {
    fetch(`/subtitles/${subtitleTarget.dataset.subtitleJob}/${subtitleTarget.dataset.subtitleOutput}`, { method: "POST" })
      .then(() => loadJobs())
      .catch(() => loadJobs());
    return;
  }

  const target = event.target.closest("[data-media-url]");
  if (!target) {
    return;
  }
  playMedia(target.dataset.mediaUrl, target.dataset.mediaTitle, target.dataset.mediaPath, target.dataset.subtitleUrl);
});

const initialJobs = JSON.parse(jobsList.dataset.initialJobs || "[]");
renderJobs(initialJobs);
setInterval(loadJobs, 3000);
