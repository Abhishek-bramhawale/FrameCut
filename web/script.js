const fileInput = document.getElementById("file-input");
const browseBtn = document.getElementById("browse-btn");
const dropZone = document.getElementById("drop-zone");
const uploadCard = document.getElementById("upload-card");
const progressCard = document.getElementById("progress-card");
const resultsCard = document.getElementById("results-card");
const progressBar = document.getElementById("progress-bar");
const progressPercent = document.getElementById("progress-percent");
const progressStage = document.getElementById("progress-stage");
const gallery = document.getElementById("gallery");
const sceneTotal = document.getElementById("scene-total");
const downloadAllBtn = document.getElementById("download-all-btn");

const modal = document.getElementById("preview-modal");
const modalVideo = document.getElementById("modal-video");
const modalTitle = document.getElementById("modal-title");
const modalDownloadBtn = document.getElementById("modal-download-btn");
const closeModalBtn = document.getElementById("close-modal-btn");

let currentJobId = null;
let pollTimer = null;

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
  gallery.innerHTML = "";
  sceneTotal.textContent = `${job.total_scenes} scenes`;
  downloadAllBtn.onclick = () => {
    if (job.download_all_url) {
      window.location.href = job.download_all_url;
    }
  };

  for (const scene of job.scenes) {
    const card = document.createElement("article");
    card.className = "scene-card";
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
          <button type="button" data-preview="${scene.clip_url}" data-number="${scene.scene_number}" data-download="${scene.download_url}">Preview</button>
          <a href="${scene.download_url}" download="${scene.clip_name}">Download</a>
        </div>
      </div>
    `;
    gallery.appendChild(card);
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

    if (job.status === "failed") {
      clearInterval(pollTimer);
      pollTimer = null;
      alert(`Processing failed: ${job.error || "Unknown error"}`);
      return;
    }

    if (job.status === "done") {
      clearInterval(pollTimer);
      pollTimer = null;
      renderScenes(job);
      resultsCard.classList.remove("hidden");
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
  setProgress(2, "Uploading video...");

  try {
    currentJobId = await uploadVideo(file);
    setProgress(4, "Video uploaded. Starting scene detection...");
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
  if (!(target instanceof HTMLButtonElement)) return;
  const previewUrl = target.dataset.preview;
  const sceneNumber = target.dataset.number;
  const downloadUrl = target.dataset.download;
  if (!previewUrl) return;

  modalTitle.textContent = `Scene ${sceneNumber} Preview`;
  modalVideo.src = previewUrl;
  modalVideo.currentTime = 0;
  modalVideo.play().catch(() => {});
  modalDownloadBtn.href = downloadUrl || "#";
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
