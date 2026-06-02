const fileInput = document.getElementById("file-input");
const browseBtn = document.getElementById("browse-btn");
const dropZone = document.getElementById("drop-zone");
const uploadCard = document.getElementById("upload-card");
const progressCard = document.getElementById("progress-card");
const resultsCard = document.getElementById("results-card");
const progressBar = document.getElementById("progress-bar");
const progressPercent = document.getElementById("progress-percent");
const progressStage = document.getElementById("progress-stage");
const logLine = document.getElementById("log-line");
const gallery = document.getElementById("gallery");
const sceneTotal = document.getElementById("scene-total");
const downloadAllUnmutedBtn = document.getElementById("download-all-unmuted-btn");
const downloadAllMutedBtn = document.getElementById("download-all-muted-btn");

const modal = document.getElementById("preview-modal");
const modalVideo = document.getElementById("modal-video");
const modalTitle = document.getElementById("modal-title");
const modalDownloadUnmutedBtn = document.getElementById("modal-download-unmuted-btn");
const modalDownloadMutedBtn = document.getElementById("modal-download-muted-btn");
const closeModalBtn = document.getElementById("close-modal-btn");

let currentJobId = null;
let pollTimer = null;
let lastRenderedSceneCount = 0;
let lastLogCount = 0;

function setProgress(progress, stage) {
  progressBar.style.width = `${progress}%`;
  progressPercent.textContent = `${progress}%`;
  progressStage.textContent = stage || "Processing...";
}

async function uploadVideo(file) {
  const formData = new FormData();
  formData.append("file", file);

  const res = await fetch("/api/upload", { method: "POST", body: formData });
  if (!res.ok) {
    const payload = await res.json().catch(() => ({}));
    throw new Error(payload.detail || "Upload failed.");
  }
  const payload = await res.json();
  return payload.job_id;
}

function renderScenes(job) {
  const expected = job.expected_scenes || job.total_scenes || 0;
  sceneTotal.textContent = `${job.total_scenes} / ${expected} scenes exported`;
  downloadAllUnmutedBtn.disabled = !job.download_all_unmuted_url;
  downloadAllMutedBtn.disabled = !job.download_all_muted_url;
  downloadAllUnmutedBtn.onclick = () => {
    if (job.download_all_unmuted_url) window.location.href = job.download_all_unmuted_url;
  };
  downloadAllMutedBtn.onclick = () => {
    if (job.download_all_muted_url) window.location.href = job.download_all_muted_url;
  };

  if (job.total_scenes < lastRenderedSceneCount) {
    gallery.innerHTML = "";
    lastRenderedSceneCount = 0;
  }

  for (let i = lastRenderedSceneCount; i < job.scenes.length; i += 1) {
    const scene = job.scenes[i];
    const card = document.createElement("article");
    card.className = "scene-card";
    card.dataset.preview = scene.clip_url;
    card.dataset.number = String(scene.scene_number);
    card.dataset.downloadUnmuted = scene.download_unmuted_url;
    card.dataset.downloadMuted = scene.download_muted_url;
    card.innerHTML = `
      <img src="${scene.thumbnail_url}" alt="Scene ${scene.scene_number}" loading="lazy" />
      <div class="scene-body">
        <h3>Scene ${scene.scene_number}</h3>
        <div class="scene-meta">
          <span>Start: ${scene.start_timestamp}</span>
          <span>End: ${scene.end_timestamp}</span>
          <span>Duration: ${scene.duration_timestamp}</span>
        </div>
        <div class="scene-actions">
          <button type="button" class="preview-btn" data-preview="${scene.clip_url}" data-number="${scene.scene_number}" data-download-unmuted="${scene.download_unmuted_url}" data-download-muted="${scene.download_muted_url}">Preview</button>
          <a href="${scene.download_unmuted_url}" download="${scene.clip_name}" data-stop-card>Unmuted</a>
          <a href="${scene.download_muted_url}" download="${scene.muted_clip_name}" class="mute-btn" data-stop-card>Muted</a>
        </div>
      </div>
    `;
    gallery.appendChild(card);
  }
  lastRenderedSceneCount = job.scenes.length;
}

function updateLogLine(job) {
  const logs = Array.isArray(job.logs) ? job.logs : [];
  if (!logs.length) return;

  if (logs.length !== lastLogCount) {
    logLine.textContent = `Log: ${logs[logs.length - 1]}`;
    lastLogCount = logs.length;
  } else {
    const expected = job.expected_scenes || 0;
    logLine.textContent = `Log: ${job.stage} (${job.total_scenes}/${expected || "?"})`;
  }
}

function startPolling() {
  if (pollTimer) {
    clearInterval(pollTimer);
  }

  pollTimer = setInterval(async () => {
    if (!currentJobId) return;
    const res = await fetch(`/api/jobs/${currentJobId}`);
    if (!res.ok) return;
    const job = await res.json();

    setProgress(job.progress || 0, job.stage || "Processing...");
    updateLogLine(job);
    renderScenes(job);
    resultsCard.classList.remove("hidden");

    if (job.status === "failed") {
      clearInterval(pollTimer);
      pollTimer = null;
      alert(`Processing failed: ${job.error || "Unknown error"}`);
      return;
    }

    if (job.status === "done") {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }, 1200);
}

async function handleFile(file) {
  if (!file || !file.type.startsWith("video/")) {
    alert("Please select a valid video file.");
    return;
  }

  uploadCard.classList.add("hidden");
  progressCard.classList.remove("hidden");
  resultsCard.classList.add("hidden");
  gallery.innerHTML = "";
  lastRenderedSceneCount = 0;
  lastLogCount = 0;
  setProgress(2, "Uploading video...");
  logLine.textContent = "Log: Uploading video.";

  try {
    currentJobId = await uploadVideo(file);
    setProgress(4, "Video uploaded. Starting scene detection...");
    logLine.textContent = "Log: Video uploaded. Starting analysis.";
    startPolling();
  } catch (err) {
    alert(err.message || "Upload failed.");
    uploadCard.classList.remove("hidden");
    progressCard.classList.add("hidden");
  }
}

browseBtn.addEventListener("click", () => fileInput.click());
dropZone.addEventListener("click", () => fileInput.click());
dropZone.addEventListener("keydown", (e) => {
  if (e.key === "Enter" || e.key === " ") {
    e.preventDefault();
    fileInput.click();
  }
});

fileInput.addEventListener("change", () => handleFile(fileInput.files[0]));

["dragenter", "dragover"].forEach((evt) => {
  dropZone.addEventListener(evt, (e) => {
    e.preventDefault();
    e.stopPropagation();
    dropZone.classList.add("drag-over");
  });
});

["dragleave", "drop"].forEach((evt) => {
  dropZone.addEventListener(evt, (e) => {
    e.preventDefault();
    e.stopPropagation();
    dropZone.classList.remove("drag-over");
  });
});

dropZone.addEventListener("drop", (e) => {
  const file = e.dataTransfer?.files?.[0];
  handleFile(file);
});

gallery.addEventListener("click", (e) => {
  const target = e.target;
  if (!(target instanceof HTMLElement)) return;

  const card = target.closest(".scene-card");
  if (!card) return;

  if (target.matches("[data-stop-card]")) {
    return;
  }

  const previewUrl = card.dataset.preview;
  const sceneNumber = card.dataset.number;
  const downloadUnmutedUrl = card.dataset.downloadUnmuted;
  const downloadMutedUrl = card.dataset.downloadMuted;
  if (!previewUrl) return;

  modalTitle.textContent = `Scene ${sceneNumber} Preview`;
  modalVideo.src = previewUrl;
  modalVideo.currentTime = 0;
  modalVideo.play().catch(() => {});
  modalDownloadUnmutedBtn.href = downloadUnmutedUrl || "#";
  modalDownloadMutedBtn.href = downloadMutedUrl || "#";
  modal.showModal();
});

closeModalBtn.addEventListener("click", () => {
  modalVideo.pause();
  modalVideo.removeAttribute("src");
  modal.close();
});

modal.addEventListener("click", (e) => {
  if (e.target === modal) {
    modalVideo.pause();
    modalVideo.removeAttribute("src");
    modal.close();
  }
});
