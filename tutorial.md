## yt2mp3 1.0.0 — Initial release

Native macOS YouTube → MP3 converter with a beautiful PyQt6 GUI.

### ✨ Features
- Native macOS-style GUI (frameless window, traffic lights, system palette)
- Download queue with per-item progress bars
- Selectable bitrate: 128 / 192 / 256 / 320 kbps
- Drag & drop URL support
- ID3 metadata + embedded thumbnail
- Real-time technical log
- Self-contained `.app` bundle (ffmpeg included)

### 📥 Installation

1. Download `yt2mp3-1.0.dmg` below.
2. Open it and drag `yt2mp3.app` to `/Applications`.
3. **First launch:** since the app is not signed with an Apple Developer ID, macOS Gatekeeper will warn you. Bypass with:

```bash
xattr -cr /Applications/yt2mp3.app
```

Or right-click the app → *Open* → *Open* the first time.

### 🖥 Requirements
macOS 11 (Big Sur) or later.

### 🔐 SHA256
