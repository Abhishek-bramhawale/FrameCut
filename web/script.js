const fileInput = document.getElementById("file-input");
const browseBtn = document.getElementById("browse-btn");
const dropZone = document.getElementById("drop-zone");
const landingPage = document.getElementById("landing-page");
const appWorkspace = document.getElementById("app-workspace");
const finalCtaBtn = document.getElementById("final-cta-btn");
const backToLandingBtn = document.getElementById("back-to-landing-btn");
const themeToggleBtn = document.getElementById("theme-toggle-btn");
const workspaceThemeToggleBtn = document.getElementById("workspace-theme-toggle-btn");
const heroGetStartedBtn = document.getElementById("hero-get-started-btn");
const personaDetail = document.getElementById("persona-detail");
const personaChips = Array.from(document.querySelectorAll(".persona-chip"));
const faqAccordion = document.getElementById("faq-accordion");
const uploadCard = document.getElementById("upload-card");
const progressCard = document.getElementById("progress-card");
const resultsCard = document.getElementById("results-card");
const processingProgressBlock = document.getElementById("processing-progress-block");
const uploadProgressBar = document.getElementById("upload-progress-bar");
const uploadProgressPercent = document.getElementById("upload-progress-percent");
const uploadProgressStage = document.getElementById("upload-progress-stage");
const processingProgressBar = document.getElementById("processing-progress-bar");
const processingProgressPercent = document.getElementById("processing-progress-percent");
const processingProgressStage = document.getElementById("processing-progress-stage");
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

const landingToHeroBtn = document.getElementById("landing-to-hero-btn");
const heroBlock = landingPage?.querySelector(".hero-block");

let currentJobId = null;
let currentJobCompleted = false;
let pollTimer = null;
let pollFailCount = 0;
const MAX_POLL_FAILS = 4;
let lastRenderedSceneCount = 0;
let lastLogCount = 0;
let syntheticLogIndex = 0;
let nextSyntheticLogAt = 0;
const THEME_KEY = "scene_splitter_theme";
const VIEW_KEY = "scene_splitter_view";
let appConfig = { max_upload_mb: 200, cloudinary: null, storage_mode: "local" };
const SYNTHETIC_PROCESSING_LOGS = [
  "Reading video metadata and validating format.",
  "Building frame analysis plan for boundary detection.",
  "Scanning visual transitions across frames.",
  "Comparing edge and color shifts between shots.",
  "Filtering out camera motion false positives.",
  "Calibrating scene threshold confidence.",
  "Collecting candidate shot boundaries.",
  "Refining start/end cut positions.",
  "Preparing clip export queue.",
  "Generating preview assets for detected scenes.",
  "Optimizing export batches for reliability.",
  "Finalizing scene manifest for gallery.",
  "Packaging scene outputs for download.",
  "Verifying clip durations and timestamps.",
  "Preparing final response for workspace.",
  "Indexing frame sequence for temporal analysis.",
  "Sampling keyframes to estimate shot density.",
  "Measuring luminance variance between adjacent frames.",
  "Detecting hard cuts versus gradual transitions.",
  "Applying motion compensation to stabilize comparisons.",
  "Grouping similar frames into shot candidates.",
  "Scoring transition strength across the timeline.",
  "Removing duplicate boundaries from overlapping detections.",
  "Normalizing frame rate for consistent analysis.",
  "Extracting color histograms for scene comparison.",
  "Tracking object movement to isolate camera pans.",
  "Evaluating fade and dissolve patterns.",
  "Checking audio-visual sync markers where available.",
  "Building a shot boundary confidence map.",
  "Merging micro-cuts below minimum scene length.",
  "Splitting over-merged segments at weak boundaries.",
  "Validating cut points against source timestamps.",
  "Running secondary pass on ambiguous regions.",
  "Comparing adaptive and content detector outputs.",
  "Weighting high-confidence transitions first.",
  "Smoothing boundary jitter near scene edges.",
  "Mapping detected scenes to export indices.",
  "Allocating encoder workers for parallel export.",
  "Writing scene metadata to job manifest.",
  "Rendering thumbnail frames at scene midpoints.",
  "Encoding unmuted clips with source audio.",
  "Encoding muted variants for each scene.",
  "Checking output file integrity after encode.",
  "Updating progress counters for live gallery.",
  "Compressing batch outputs for ZIP archives.",
  "Sorting scenes by timeline order.",
  "Attaching download URLs to scene records.",
  "Refreshing workspace state with latest exports.",
  "Estimating remaining export time from queue depth.",
  "Balancing CPU and GPU encoder load.",
  "Retrying failed encodes with fallback settings.",
  "Cleaning temporary frames from working directory.",
  "Synchronizing scene list with backend job state.",
  "Running final quality checks on clip boundaries.",
  "Publishing completed scenes to the gallery view.",
];

function nextSyntheticDelayMs() {
  // Random cadence between 5s and 13s.
  return Math.floor(Math.random() * 8001) + 5000;
}

// Always start at top on refresh/open.
if ("scrollRestoration" in history) {
  history.scrollRestoration = "manual";
}

function applyTheme(theme) {
  const root = document.documentElement;
  if (theme === "dark") root.classList.add("dark");
  else root.classList.remove("dark");

  const iconDark =
    '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M21 12.79A9 9 0 1 1 11.21 3a7 7 0 1 0 9.79 9.79Z" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  const iconLight =
    '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="12" cy="12" r="4" stroke="currentColor" stroke-width="1.7"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>';

  const icon = theme === "dark" ? iconDark : iconLight;
  if (themeToggleBtn) themeToggleBtn.innerHTML = icon;
  if (workspaceThemeToggleBtn) workspaceThemeToggleBtn.innerHTML = icon;
}

function initializeTheme() {
  const saved = localStorage.getItem(THEME_KEY);
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  applyTheme(saved || (prefersDark ? "dark" : "light"));
}

function toggleTheme() {
  const current = document.documentElement.classList.contains("dark") ? "dark" : "light";
  const next = current === "dark" ? "light" : "dark";
  localStorage.setItem(THEME_KEY, next);
  applyTheme(next);
}

function showWorkspace() {
  try {
    sessionStorage.setItem(VIEW_KEY, "workspace");
  } catch {}
  landingPage.style.transition = "opacity 220ms ease";
  landingPage.style.opacity = "0";
  setTimeout(() => {
    landingPage.classList.add("hidden");
    appWorkspace.classList.remove("hidden");
    appWorkspace.style.opacity = "0";
    appWorkspace.style.transition = "opacity 220ms ease";
    requestAnimationFrame(() => {
      appWorkspace.style.opacity = "1";
    });
  }, 220);
}

function showLanding() {
  try {
    sessionStorage.setItem(VIEW_KEY, "landing");
  } catch {}
  appWorkspace.style.transition = "opacity 180ms ease";
  appWorkspace.style.opacity = "0";
  setTimeout(() => {
    appWorkspace.classList.add("hidden");
    landingPage.classList.remove("hidden");
    landingPage.style.opacity = "0";
    landingPage.style.transition = "opacity 180ms ease";
    requestAnimationFrame(() => {
      landingPage.style.opacity = "1";
    });
    window.scrollTo({ top: 0, left: 0, behavior: "auto" });
  }, 180);
}

function restoreViewOnLoad() {
  let savedView = "landing";
  try {
    savedView = sessionStorage.getItem(VIEW_KEY) || "landing";
  } catch {}

  if (savedView === "workspace") {
    landingPage.classList.add("hidden");
    appWorkspace.classList.remove("hidden");
    landingPage.style.opacity = "0";
    appWorkspace.style.opacity = "1";
    return;
  }

  appWorkspace.classList.add("hidden");
  landingPage.classList.remove("hidden");
  landingPage.style.opacity = "1";
}

function initializeLandingToHero() {
  if (!landingToHeroBtn || !heroBlock) return;

  const setVisible = (v) => {
    landingToHeroBtn.style.display = v ? "flex" : "none";
  };

  // Only show button when landing page is visible and user scrolls past hero.
  const onScroll = () => {
    if (!landingPage || landingPage.classList.contains("hidden")) {
      setVisible(false);
      return;
    }
    const heroBottom = heroBlock.getBoundingClientRect().bottom;
    // If hero is mostly above the viewport, show the button.
    setVisible(heroBottom < window.innerHeight * 0.55);
  };

  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  landingToHeroBtn.addEventListener("click", () => {
    heroBlock.scrollIntoView({
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
      block: "start",
    });
  });
}

function getLandingSections() {
  if (!landingPage) return [];
  const hero = landingPage.querySelector(".hero-block");
  const sections = Array.from(landingPage.querySelectorAll(".content-section"));
  return [hero, ...sections].filter(Boolean);
}

function currentSectionIndex(sections) {
  const centerY = window.innerHeight / 2;
  let bestIdx = 0;
  let bestDist = Infinity;
  sections.forEach((el, idx) => {
    const r = el.getBoundingClientRect();
    const elCenter = r.top + r.height / 2;
    const dist = Math.abs(elCenter - centerY);
    if (dist < bestDist) {
      bestDist = dist;
      bestIdx = idx;
    }
  });
  return bestIdx;
}

let landingWheelLock = false;
function enableLandingWheelPaging() {
  const sections = getLandingSections();
  if (!sections.length) return;

  // Avoid hijacking on touch devices / small screens.
  if (window.matchMedia("(pointer: coarse)").matches) return;

  window.addEventListener(
    "wheel",
    (e) => {
      // Only when landing is visible.
      if (!landingPage || landingPage.classList.contains("hidden")) return;
      if (landingWheelLock) {
        e.preventDefault();
        return;
      }

      // If user is interacting with expandable content (FAQ), don't hijack.
      const inDetails = e.target instanceof Element ? e.target.closest("details") : null;
      if (inDetails) return;

      const dy = e.deltaY;
      if (Math.abs(dy) < 12) return;

      const idx = currentSectionIndex(sections);
      const nextIdx = dy > 0 ? Math.min(sections.length - 1, idx + 1) : Math.max(0, idx - 1);
      if (nextIdx === idx) return;

      e.preventDefault();
      landingWheelLock = true;

      sections[nextIdx].scrollIntoView({
        behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
        block: "center",
      });

      window.setTimeout(() => {
        landingWheelLock = false;
      }, 750);
    },
    { passive: false }
  );
}

const PERSONA_CONTENT = {
  editors: {
    title: "Video Editors",
    description: "Quickly isolate usable shots from large footage collections and reduce manual timeline work.",
  },
  creators: {
    title: "Content Creators",
    description: "Extract B-roll, transitions, and highlights for shorts, reels, and upcoming projects.",
  },
  youtube: {
    title: "YouTubers",
    description: "Organize footage and find reusable segments faster while building long-form channels.",
  },
  research: {
    title: "Researchers",
    description: "Analyze videos scene by scene and inspect transitions without creating cuts manually.",
  },
  marketing: {
    title: "Marketing Teams",
    description: "Repurpose campaign videos into smaller reusable assets for multiple channels.",
  },
  archives: {
    title: "Media Archives",
    description: "Break large video files into manageable scene collections for retrieval and tagging.",
  },
};

function setPersona(key) {
  const content = PERSONA_CONTENT[key];
  if (!content || !personaDetail) return;
  personaDetail.innerHTML = `<h3>${content.title}</h3><p>${content.description}</p>`;
  personaChips.forEach((chip) => {
    chip.classList.toggle("active", chip.dataset.persona === key);
  });
}

function initializeFaqAccordion() {
  if (!faqAccordion) return;
  const rows = Array.from(faqAccordion.querySelectorAll(".faq-row"));

  function closeRow(row) {
    row.dataset.open = "false";
    const btn = row.querySelector(".faq-q");
    const panel = row.querySelector(".faq-a");
    if (btn) btn.setAttribute("aria-expanded", "false");
    if (panel) {
      panel.setAttribute("aria-hidden", "true");
      panel.style.maxHeight = "0px";
    }
  }

  function openRow(row) {
    rows.forEach((r) => {
      if (r !== row) closeRow(r);
    });
    row.dataset.open = "true";
    const btn = row.querySelector(".faq-q");
    const panel = row.querySelector(".faq-a");
    const inner = row.querySelector(".faq-a-inner");
    if (btn) btn.setAttribute("aria-expanded", "true");
    if (panel && inner) {
      panel.setAttribute("aria-hidden", "false");
      panel.style.maxHeight = `${inner.scrollHeight + 18}px`;
    }
  }

  rows.forEach((row) => {
    closeRow(row);
    const btn = row.querySelector(".faq-q");
    if (!btn) return;
    btn.addEventListener("click", () => {
      const isOpen = row.dataset.open === "true";
      if (isOpen) closeRow(row);
      else openRow(row);
    });
  });

  // Open the first one by default for a nicer feel.
  if (rows[0]) openRow(rows[0]);

  window.addEventListener("resize", () => {
    const open = rows.find((r) => r.dataset.open === "true");
    if (!open) return;
    const panel = open.querySelector(".faq-a");
    const inner = open.querySelector(".faq-a-inner");
    if (panel && inner) panel.style.maxHeight = `${inner.scrollHeight + 18}px`;
  });
}

function clampPercent(value) {
  return Math.max(0, Math.min(100, Math.round(Number(value) || 0)));
}

function setUploadProgress(progress, stage) {
  const pct = clampPercent(progress);
  uploadProgressBar.style.width = `${pct}%`;
  uploadProgressPercent.textContent = `${pct}%`;
  if (stage) uploadProgressStage.textContent = stage;
}

function setProcessingProgress(progress, stage) {
  const pct = clampPercent(progress);
  processingProgressBar.style.width = `${pct}%`;
  processingProgressPercent.textContent = `${pct}%`;
  if (stage) processingProgressStage.textContent = stage;
}

function setProcessingEnabled(enabled) {
  if (!processingProgressBlock) return;
  processingProgressBlock.classList.toggle("is-disabled", !enabled);
}

function resetProgressUi() {
  setUploadProgress(0, "Waiting for file...");
  setProcessingProgress(0, "Waiting for upload to finish...");
  setProcessingEnabled(false);
}

function xhrUpload(url, body, headers = {}, onUploadProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    Object.entries(headers).forEach(([key, value]) => xhr.setRequestHeader(key, value));
    xhr.upload.onprogress = (event) => {
      if (!event.lengthComputable || !onUploadProgress) return;
      onUploadProgress(clampPercent((event.loaded / event.total) * 100));
    };
    xhr.onload = () => {
      let payload = {};
      try {
        payload = xhr.responseText ? JSON.parse(xhr.responseText) : {};
      } catch {
        payload = { detail: xhr.responseText || "Invalid server response." };
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(payload);
        return;
      }
      const detail =
        payload.detail ||
        payload.error?.message ||
        payload.message ||
        `Request failed (${xhr.status}).`;
      reject(new Error(typeof detail === "string" ? detail : JSON.stringify(detail)));
    };
    xhr.onerror = () => reject(new Error("Network error during upload."));
    xhr.send(body);
  });
}

function formatDurationHuman(durationSeconds) {
  const total = Math.max(0, Math.round(Number(durationSeconds) || 0));
  const mins = Math.floor(total / 60);
  const secs = total % 60;
  if (mins <= 0) return `${secs} secs`;
  if (secs <= 0) return `${mins} min`;
  return `${mins} min ${secs} secs`;
}

async function loadAppConfig() {
  try {
    const res = await fetch("/api/config");
    if (res.ok) {
      appConfig = await res.json();
    }
  } catch {}
}

function maxUploadBytes() {
  return (appConfig.max_upload_mb || 200) * 1024 * 1024;
}

async function uploadViaCloudinary(file, onUploadProgress) {
  const cloudinary = appConfig.cloudinary;
  if (!cloudinary?.cloud_name || !cloudinary?.upload_preset) {
    throw new Error("Cloudinary is not configured.");
  }

  const formData = new FormData();
  formData.append("file", file);
  formData.append("upload_preset", cloudinary.upload_preset);
  formData.append("folder", "framecut/incoming");

  const uploaded = await xhrUpload(
    `https://api.cloudinary.com/v1_1/${cloudinary.cloud_name}/video/upload`,
    formData,
    {},
    onUploadProgress
  );

  const startPayload = await xhrUpload(
    "/api/jobs/start",
    JSON.stringify({
      source_public_id: uploaded.public_id,
      original_name: file.name,
    }),
    { "Content-Type": "application/json" }
  );
  return startPayload.job_id;
}

async function uploadVideo(file, onUploadProgress) {
  if (appConfig.cloudinary) {
    return uploadViaCloudinary(file, onUploadProgress);
  }

  const formData = new FormData();
  formData.append("file", file);
  const payload = await xhrUpload("/api/upload", formData, {}, onUploadProgress);
  return payload.job_id;
}

function handleJobPollFailure(message) {
  clearInterval(pollTimer);
  pollTimer = null;
  setProcessingProgress(0, "Processing interrupted.");
  logLine.textContent = `Log: Error - ${message}`;
  alert(message);
  uploadCard.classList.remove("hidden");
  progressCard.classList.add("hidden");
}

function requestJobCleanup() {
  if (!currentJobId || !currentJobCompleted) return;
  const url = `/api/jobs/${currentJobId}/cleanup`;
  try {
    navigator.sendBeacon(url, new Blob([], { type: "application/json" }));
  } catch {
    fetch(url, { method: "POST", keepalive: true }).catch(() => {});
  }
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
    const durationHuman = formatDurationHuman(scene.duration_seconds);
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
          <span>Duration: ${durationHuman}</span>
        </div>
        <div class="scene-actions">
          <button type="button" class="preview-btn icon-btn" data-preview="${scene.clip_url}" data-number="${scene.scene_number}" data-download-unmuted="${scene.download_unmuted_url}" data-download-muted="${scene.download_muted_url}">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M2.5 12s3.5-7 9.5-7 9.5 7 9.5 7-3.5 7-9.5 7-9.5-7-9.5-7Z" stroke="currentColor" stroke-width="1.7"/><path d="M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z" stroke="currentColor" stroke-width="1.7"/></svg>
            Preview
          </button>
          <a href="${scene.download_unmuted_url}" download="${scene.clip_name}" class="icon-btn" data-stop-card>
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 3v10m0 0l4-4m-4 4-4-4M4 20h16" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>
            Unmuted
          </a>
          <a href="${scene.download_muted_url}" download="${scene.muted_clip_name}" class="mute-btn icon-btn" data-stop-card>
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M4 9h4l5-4v14l-5-4H4V9Z" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/><path d="M17 9l4 6M21 9l-4 6" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>
            Muted
          </a>
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
  const now = Date.now();

  if (logs.length !== lastLogCount) {
    logLine.textContent = `Log: ${logs[logs.length - 1]}`;
    lastLogCount = logs.length;
    nextSyntheticLogAt = now + nextSyntheticDelayMs();
  } else {
    if (job.status === "processing" && (job.progress || 0) <= 65) {
      if (!nextSyntheticLogAt || now >= nextSyntheticLogAt) {
        const line = SYNTHETIC_PROCESSING_LOGS[syntheticLogIndex % SYNTHETIC_PROCESSING_LOGS.length];
        syntheticLogIndex += 1;
        logLine.textContent = `Log: ${line}`;
        nextSyntheticLogAt = now + nextSyntheticDelayMs();
      }
    } else {
      const expected = job.expected_scenes || 0;
      logLine.textContent = `Log: ${job.stage} (${job.total_scenes}/${expected || "?"})`;
    }
  }
}

function startPolling() {
  if (pollTimer) {
    clearInterval(pollTimer);
  }
  pollFailCount = 0;
  setProcessingEnabled(true);
  setProcessingProgress(0, "Starting scene detection...");

  pollTimer = setInterval(async () => {
    if (!currentJobId) return;

    let res;
    try {
      res = await fetch(`/api/jobs/${currentJobId}`);
    } catch {
      pollFailCount += 1;
      if (pollFailCount >= MAX_POLL_FAILS) {
        handleJobPollFailure("Lost connection to server. Please upload again.");
      }
      return;
    }

    if (res.status === 404) {
      handleJobPollFailure("Job not found. The server may have restarted — please upload your video again.");
      return;
    }

    if (res.status === 502 || res.status === 503) {
      pollFailCount += 1;
      const retryPct = clampPercent(
        parseFloat(String(processingProgressPercent.textContent).replace("%", "")) || 0
      );
      setProcessingProgress(retryPct, "Server waking up, retrying...");
      if (pollFailCount >= MAX_POLL_FAILS) {
        handleJobPollFailure("Server unavailable (502/503). Please try again in a minute.");
      }
      return;
    }

    if (!res.ok) {
      pollFailCount += 1;
      if (pollFailCount >= MAX_POLL_FAILS) {
        handleJobPollFailure(`Status check failed (${res.status}). Please upload again.`);
      }
      return;
    }

    pollFailCount = 0;
    const job = await res.json();

    setProcessingProgress(job.progress || 0, job.stage || "Processing...");
    updateLogLine(job);
    renderScenes(job);
    resultsCard.classList.remove("hidden");

    if (job.status === "failed") {
      logLine.textContent = `Log: Error - ${job.error || "Unknown error"}`;
      clearInterval(pollTimer);
      pollTimer = null;
      alert(`Processing failed: ${job.error || "Unknown error"}`);
      uploadCard.classList.remove("hidden");
      progressCard.classList.add("hidden");
      return;
    }

    if (job.status === "done") {
      currentJobCompleted = true;
      setProcessingProgress(100, "Completed");
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

  if (file.size > maxUploadBytes()) {
    alert(`Max upload size is ${appConfig.max_upload_mb || 200} MB.`);
    return;
  }

  uploadCard.classList.add("hidden");
  progressCard.classList.remove("hidden");
  resultsCard.classList.add("hidden");
  gallery.innerHTML = "";
  lastRenderedSceneCount = 0;
  lastLogCount = 0;
  syntheticLogIndex = 0;
  nextSyntheticLogAt = Date.now() + nextSyntheticDelayMs();
  currentJobCompleted = false;
  pollFailCount = 0;
  resetProgressUi();
  setUploadProgress(0, appConfig.cloudinary ? "Uploading to Cloudinary..." : "Uploading to server...");
  logLine.textContent = appConfig.cloudinary
    ? "Log: Uploading to Cloudinary, then processing on server."
    : "Log: Uploading video to server.";

  try {
    currentJobId = await uploadVideo(file, (pct) => {
      setUploadProgress(pct, `Uploading... ${pct}%`);
    });
    setUploadProgress(100, "Upload complete.");
    setProcessingProgress(0, "Starting scene detection...");
    logLine.textContent = "Log: Upload finished. Processing started.";
    startPolling();
  } catch (err) {
    alert(err.message || "Upload failed.");
    uploadCard.classList.remove("hidden");
    progressCard.classList.add("hidden");
  }
}

browseBtn.addEventListener("click", (e) => {
  e.preventDefault();
  e.stopPropagation();
  fileInput.click();
});
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
  openPreviewModal();
});

function lockPageScroll() {
  document.documentElement.classList.add("modal-open");
  document.body.classList.add("modal-open");
}

function unlockPageScroll() {
  document.documentElement.classList.remove("modal-open");
  document.body.classList.remove("modal-open");
}

function openPreviewModal() {
  lockPageScroll();
  modal.showModal();
}

function closePreviewModal() {
  modalVideo.pause();
  modalVideo.removeAttribute("src");
  modal.close();
}

closeModalBtn.addEventListener("click", closePreviewModal);

modal.addEventListener("click", (e) => {
  if (e.target === modal) closePreviewModal();
});

modal.addEventListener("close", unlockPageScroll);

themeToggleBtn.addEventListener("click", toggleTheme);
if (workspaceThemeToggleBtn) workspaceThemeToggleBtn.addEventListener("click", toggleTheme);

finalCtaBtn.addEventListener("click", showWorkspace);
if (backToLandingBtn) backToLandingBtn.addEventListener("click", showLanding);
personaChips.forEach((chip) => {
  chip.addEventListener("click", () => setPersona(chip.dataset.persona));
});
if (heroGetStartedBtn) heroGetStartedBtn.addEventListener("click", showWorkspace);

initializeTheme();
loadAppConfig();
restoreViewOnLoad();
enableLandingWheelPaging();
initializeFaqAccordion();
initializeLandingToHero();

window.addEventListener("load", () => {
  if (!landingPage.classList.contains("hidden")) {
    window.scrollTo({ top: 0, left: 0, behavior: "auto" });
  }
});

window.addEventListener("pagehide", requestJobCleanup);
window.addEventListener("beforeunload", requestJobCleanup);
