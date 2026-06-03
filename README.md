# FrameCut

A dedicated web app that detects shot/scene boundaries from an uploaded video and exports each scene as its own clip.

## Screenshots

### Upload

Drag and drop a video or choose a file from your device.

![Upload workspace](Images/upload.png)

### Results

Browse detected scenes with thumbnails, timestamps, and bulk download options.

![Detected scenes gallery](Images/result.png)

### Preview

Open any scene in a full preview player with per-scene muted and unmuted downloads.

![Scene preview modal](Images/preview.png)

## Features

- Drag-and-drop video upload.
- Advanced content-based scene detection (hybrid adaptive + content detector).
- Progress indicator while processing.
- Scene gallery with:
  - Thumbnail
  - Scene number
  - Start timestamp
  - End timestamp
  - Duration
- Per-scene preview in a large modal player.
- Per-scene download + Download All Scenes (ZIP).

## Tech Stack

- Backend: FastAPI
- Scene Detection: PySceneDetect (`AdaptiveDetector` + `ContentDetector`)
- Clip/thumbnail export: FFmpeg
- Frontend: vanilla HTML/CSS/JS (responsive, modern UI)

## Setup

1. Install [FFmpeg](https://ffmpeg.org/download.html) and ensure `ffmpeg` is available in your PATH.
2. Create and activate a virtual environment.
3. Install dependencies:

```bash
pip install -r requirements.txt
```

4. Run the app:

```bash
uvicorn main:app --reload
```

5. Open `http://127.0.0.1:8000`.

## Deploy (Vercel + Render + optional Cloudinary)

### Architecture

| Part | Host | Role |
|------|------|------|
| Frontend | **Vercel** | Static UI (`web/`) |
| API + PySceneDetect + FFmpeg | **Render** (Docker, free) | Scene detection & clip export |
| Media storage (optional) | **Cloudinary** free tier | Uploads + clips + ZIPs; deleted after user leaves |

Render free has an **ephemeral disk** (no persistent volume). Cloudinary avoids losing files on restart and keeps Render disk usage lower after each job.

**Max upload size:** **200 MB** (enforced in API + UI).

### 1) Render (backend)

1. Push repo to GitHub.
2. [Render Dashboard](https://dashboard.render.com) → **New Web Service** → connect repo.
3. **Environment:** Docker (uses repo `Dockerfile`).
4. **Plan:** Free (expect cold starts ~30–60s).
5. **Environment variables** (optional but recommended):

   ```
   CLOUDINARY_CLOUD_NAME=...
   CLOUDINARY_API_KEY=...
   CLOUDINARY_API_SECRET=...
   CLOUDINARY_UPLOAD_PRESET=...   # unsigned preset for browser uploads
   ```

6. Deploy and copy your service URL, e.g. `https://framecut-backend.onrender.com`.

### 2) Cloudinary (optional storage)

1. Create a [Cloudinary](https://cloudinary.com) account.
2. Create an **unsigned upload preset** (Upload → Upload presets).
3. Add the four env vars above on Render.
4. Flow:
   - Browser uploads video **directly to Cloudinary** (not through Render).
   - Render downloads once for processing, then publishes clips/thumbs/ZIPs back to Cloudinary.
   - When the user **closes the tab after processing completes**, the app calls `/api/jobs/{id}/cleanup` to delete that job’s Cloudinary folder.

**Note:** Cleanup on tab close is best-effort (browser crash may skip it). Cloudinary free tier has monthly credits/limits—check your plan dashboard.

### 3) Vercel (frontend)

1. Import the same GitHub repo on [Vercel](https://vercel.com).
2. Edit `vercel.json`: replace `https://RENDER_BACKEND_URL` with your Render URL (no trailing slash).
3. Deploy.

Vercel serves the UI and proxies `/api/*` to Render.

### Local without Cloudinary

If Cloudinary env vars are unset, the app uses normal upload to Render (`/api/upload`) and local job folders (fine for dev).

## Accuracy Notes

- The detection pipeline prioritizes accuracy over speed:
  - Uses adaptive thresholding to reduce false cuts from camera movement or lighting shifts.
  - Uses content-based detection to catch hard transitions.
  - Uses minimum scene length guards against over-segmentation.
- Clip extraction re-encodes with near-lossless settings (`crf 18`, `preset slow`) for frame-accurate scene boundaries.

You can fine-tune thresholds in `main.py` depending on your content type (fast cuts, dark scenes, animation, etc.).
