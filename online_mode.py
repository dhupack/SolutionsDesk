"""
Online Mode — voice input + always-on-top floating window.

Flow:
    click ▶ Start  -> record your mic AND the call audio (system output, via loopback)
    click ■ Stop   -> mix both sides, upload to the backend's /api/transcribe (Whisper)
                   -> transcript shown in the window
    click "Send to RAG" -> POST the transcript to /api/chat/stream
                   -> colored answer streams into the window

Connects to the backend at SOLUTIONSDESK_BACKEND / backend.txt / DEFAULT_BACKEND
(see Config below). Transcription and the OpenAI key live on the server, so this
client needs no API key. Normally started by the web UI ("MODES → Online · …"),
but can also be run directly:  python online_mode.py
"""

import html as _html
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time

import httpx
import numpy as np
import soundcard as sc
import soundfile as sf
from dotenv import load_dotenv

from PyQt6.QtCore import Qt, QObject, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QTextEdit, QFrame,
)

# ── Config ─────────────────────────────────────────────────────────────────────
def _app_dir() -> str:
    """Folder the app runs from — next to the .exe when packaged, else the script dir."""
    if getattr(sys, "frozen", False):           # True inside a PyInstaller build
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


load_dotenv(os.path.join(_app_dir(), ".env"))

# Where the RAG backend lives. For the packaged app, set this to your deployed
# Render URL (e.g. "https://solutionsdesk.onrender.com"). Resolution order:
#   1) SOLUTIONSDESK_BACKEND environment variable
#   2) a "backend.txt" file placed next to the .exe (first non-comment line)
#   3) DEFAULT_BACKEND below
# This lets you change the URL without rebuilding the .exe — just edit backend.txt.
DEFAULT_BACKEND = "http://localhost:5001"


def _resolve_backend() -> str:
    env = os.getenv("SOLUTIONSDESK_BACKEND", "").strip()
    if env:
        return env.rstrip("/")
    try:
        with open(os.path.join(_app_dir(), "backend.txt"), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    return line.rstrip("/")
    except OSError:
        pass
    return DEFAULT_BACKEND.rstrip("/")


BACKEND_URL    = _resolve_backend()
RAG_STREAM_URL = f"{BACKEND_URL}/api/chat/stream"
TRANSCRIBE_URL = f"{BACKEND_URL}/api/transcribe"
API_KEY        = os.getenv("SOLUTIONSDESK_API_KEY", "").strip()   # optional; sent if set
REC_SR         = 48000          # capture rate; Whisper handles it fine
SINGLETON_PORT = 49222          # single-instance lock (prevents duplicate windows)


def _auth_headers() -> dict:
    """Send an API key header only if one is configured (server may require it)."""
    return {"X-API-Key": API_KEY} if API_KEY else {}


# ── Thread → UI signal bridge ───────────────────────────────────────────────────
class Bridge(QObject):
    transcribed = pyqtSignal(str)   # worker → UI: transcription finished
    answer      = pyqtSignal(str)
    status      = pyqtSignal(str)


bridge = Bridge()
_captured = ""                  # the transcript that "Send to RAG" will use
_capture_both = True            # True = mic + call audio (loopback); False = mic only

# ── Audio recorder: your mic + system output (the call audio), mixed ────────────
_recording   = False
_mic_buf     = []               # frames from your microphone
_loop_buf    = []               # frames from system output (client / call audio)
_mic_thread  = None
_loop_thread = None


def _record_into(make_recorder, buf):
    """Run a soundcard recorder, appending 0.1s blocks to buf until recording stops."""
    try:
        with make_recorder() as rec:
            while _recording:
                buf.append(rec.record(numframes=REC_SR // 10).copy())
    except Exception as e:
        bridge.status.emit(f"Audio capture error: {e}")


def start_recording():
    """Capture the microphone, and (if _capture_both) the call audio via loopback."""
    global _recording, _mic_buf, _loop_buf, _mic_thread, _loop_thread
    _mic_buf, _loop_buf = [], []
    _recording = True
    mic = sc.default_microphone()
    _mic_thread = threading.Thread(
        target=_record_into,
        args=(lambda: mic.recorder(samplerate=REC_SR, channels=1), _mic_buf), daemon=True)
    _mic_thread.start()
    if _capture_both:
        speaker  = sc.default_speaker()
        loopback = sc.get_microphone(speaker.name, include_loopback=True)   # "what you hear"
        _loop_thread = threading.Thread(
            target=_record_into,
            args=(lambda: loopback.recorder(samplerate=REC_SR, channels=1), _loop_buf), daemon=True)
        _loop_thread.start()
    else:
        _loop_thread = None


def stop_and_transcribe() -> str:
    """Stop both streams, mix you + the call audio into one clip, transcribe via Whisper."""
    global _recording
    _recording = False
    for th in (_mic_thread, _loop_thread):
        if th is not None:
            th.join(timeout=2)
    mic  = np.concatenate(_mic_buf).flatten()  if _mic_buf  else np.zeros(0, dtype="float32")
    loop = np.concatenate(_loop_buf).flatten() if _loop_buf else np.zeros(0, dtype="float32")
    if mic.size == 0 and loop.size == 0:
        return ""
    n = max(mic.size, loop.size)
    mic  = np.pad(mic,  (0, n - mic.size))
    loop = np.pad(loop, (0, n - loop.size))
    mixed = np.clip(mic + loop, -1.0, 1.0).astype("float32")   # you + client in one track
    wav_path = os.path.join(tempfile.gettempdir(), "solutionsdesk_voice.wav")
    sf.write(wav_path, mixed, REC_SR)

    # Transcribe via the backend's /api/transcribe (keeps the OpenAI key on the
    # server — never shipped inside the distributed .exe).
    with open(wav_path, "rb") as f:
        files = {"audio": ("voice.wav", f, "audio/wav")}
        r = httpx.post(TRANSCRIBE_URL, files=files, headers=_auth_headers(), timeout=120)
    r.raise_for_status()
    return (r.json().get("text") or "").strip()


# ── Convert the RAG block JSON into colored HTML (matches the web chat) ─────────
# Per-source palette: (left-bar color, tinted background, text color)
_SRC_STYLE = {
    "feature":  ("#10b981", "#ecfdf5", "#065f46"),   # green  → feature sheet
    "proposal": ("#3b82f6", "#eff6ff", "#1e3a8a"),   # blue   → proposals
    "llm":      ("#f59e0b", "#fffbeb", "#92400e"),   # amber  → LLM knowledge
}
_NEUTRAL = ("#cbd5e1", "#f8fafc", "#334155")
_BADGE_TONE = {
    "blue":  ("#eff6ff", "#1e40af"),
    "amber": ("#fffbeb", "#92400e"),
    "green": ("#ecfdf5", "#065f46"),
}


def _esc(s) -> str:
    return _html.escape(str(s or ""))


def _callout(bar: str, bg: str, inner: str) -> str:
    """A tinted block with a colored left border (two-cell table — Qt-friendly)."""
    return (
        f'<table width="100%" cellspacing="0" cellpadding="0" style="margin:0 0 8px 0;">'
        f'<tr>'
        f'<td width="5" bgcolor="{bar}" style="background-color:{bar};">&#160;</td>'
        f'<td bgcolor="{bg}" style="background-color:{bg};padding:8px 11px;">{inner}</td>'
        f'</tr></table>'
    )


def _item_html(it: dict) -> str:
    bar, bg, fg = _SRC_STYLE.get(it.get("src", ""), _NEUTRAL)
    text = it.get("text", "")
    points = it.get("points") or []
    if points:
        head = (f'<div style="color:{fg};font-size:12px;font-weight:bold;margin-bottom:4px;">{_esc(text)}</div>'
                if text else "")
        lis = "".join(f'<li style="color:{fg};font-size:12px;">{_esc(p)}</li>' for p in points)
        inner = f'{head}<ul style="margin:0;padding-left:16px;">{lis}</ul>'
    else:
        inner = f'<span style="color:{fg};font-size:12px;">{_esc(text)}</span>'
    ref = it.get("ref", "")
    if ref:
        inner += (f'<div style="margin-top:5px;font-size:9px;color:#94a3b8;">'
                  f'[{_esc(ref)}]</div>')
    return _callout(bar, bg, inner)


def blocks_to_html(data: dict) -> str:
    parts = []
    badge = data.get("badge")
    if badge and badge.get("label"):
        bg, fg = _BADGE_TONE.get(badge.get("tone"), ("#f1f5f9", "#334155"))
        parts.append(
            f'<div style="margin-bottom:11px;"><span style="background-color:{bg};'
            f'color:{fg};padding:3px 10px;border-radius:8px;font-size:10px;'
            f'font-weight:bold;">{_esc(badge["label"])}</span></div>'
        )
    for b in data.get("blocks", []):
        t = b.get("type")
        if t == "p":
            parts.append(f'<p style="color:#334155;font-size:12px;'
                         f'margin:0 0 11px 0;line-height:140%;">{_esc(b.get("text", ""))}</p>')
        elif t == "note":
            bar, bg, fg = _SRC_STYLE["llm"]
            parts.append(_callout(
                bar, bg, f'<span style="color:{fg};font-size:12px;">{_esc(b.get("text", ""))}</span>'))
        elif t == "cited":
            if b.get("title"):
                parts.append(f'<div style="color:#0f172a;font-size:11px;font-weight:bold;'
                             f'margin:6px 0 8px 0;letter-spacing:.03em;">{_esc(b["title"]).upper()}</div>')
            for it in b.get("items", []):
                parts.append(_item_html(it))
        elif t == "list":
            if b.get("title"):
                parts.append(f'<div style="color:#0f172a;font-size:11px;font-weight:bold;'
                             f'margin:6px 0 6px 0;">{_esc(b["title"])}</div>')
            for it in b.get("items", []):
                parts.append(f'<p style="color:#334155;font-size:12px;margin:0 0 5px 0;">'
                             f'&#8226;&#160;{_esc(it)}</p>')
        elif t == "sources":
            for it in b.get("items", []):
                parts.append(f'<p style="color:#64748b;font-size:11px;margin:0 0 4px 0;">'
                             f'&#8226;&#160;{_esc(it.get("title", ""))}</p>')
    return "".join(parts) or '<p style="color:#94a3b8;">(empty answer)</p>'


# ── Send the current transcript to the RAG backend ──────────────────────────────
def ask_rag():
    query = _captured.strip()
    if not query:
        bridge.answer.emit("(Nothing to send — press ▶ Start, speak, then ■ Stop.)")
        return
    bridge.answer.emit("Thinking…")
    payload = {"messages": [{"role": "user", "content": query}]}
    try:
        got_any = False
        with httpx.stream("POST", RAG_STREAM_URL, json=payload,
                          headers=_auth_headers(), timeout=120) as res:
            if res.status_code != 200:
                res.read()
                bridge.answer.emit(f"Error: HTTP {res.status_code}")
                return
            event, data_buf = "message", []
            for line in res.iter_lines():          # SSE: blank line terminates an event
                if line == "":
                    if data_buf:
                        raw = "".join(data_buf)
                        data_buf = []
                        ev, event = event, "message"
                        try:
                            obj = json.loads(raw)
                        except Exception:
                            continue
                        if ev == "error":
                            bridge.answer.emit(f"Error: {obj.get('error', 'stream error')}")
                            return
                        got_any = True
                        bridge.answer.emit(blocks_to_html(obj))   # partial + final both render
                    continue
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:"):
                    data_buf.append(line[5:].lstrip())
        if not got_any:
            bridge.answer.emit("(No answer was produced — please try again.)")
    except Exception as e:
        bridge.answer.emit(f"Request failed: {e}")


# ── Floating window ─────────────────────────────────────────────────────────────
class FloatingWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setGeometry(60, 60, 470, 640)
        self.setWindowOpacity(0.97)          # subtle see-through, like the web chat
        self._drag = None

        card = QFrame(self)
        card.setObjectName("card")
        card.setStyleSheet("""
            #card{background:rgba(255,255,255,0.95);border-radius:16px;
                  border:1px solid rgba(15,23,42,0.08);}
            QLabel{color:#0f172a;}
            QLabel#title{font-size:13px;font-weight:700;color:#0f172a;}
            QLabel#status{font-size:10px;color:#64748b;}
            QLabel#capLabel,QLabel#ansLabel{font-size:10px;font-weight:700;
                  color:#64748b;letter-spacing:.05em;}
            QTextEdit{background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;
                  color:#0f172a;font-size:12px;padding:9px;}
            QTextEdit#answer{background:#ffffff;}
            QPushButton#send{background:#2563eb;color:#fff;font-size:13px;font-weight:600;
                  border:none;border-radius:10px;padding:10px;}
            QPushButton#send:hover{background:#1d4ed8;}
            QPushButton#close{background:transparent;color:#94a3b8;font-size:16px;border:none;}
            QPushButton#close:hover{color:#0f172a;}
            QPushButton#play{background:#16a34a;color:#fff;font-size:10px;font-weight:700;
                  border:none;border-radius:7px;padding:4px 12px;}
            QPushButton#play:hover{background:#15803d;}
            QPushButton#stop{background:#dc2626;color:#fff;font-size:10px;font-weight:700;
                  border:none;border-radius:7px;padding:4px 12px;}
            QPushButton#stop:hover{background:#b91c1c;}
            QPushButton#play:disabled,QPushButton#stop:disabled{background:#e2e8f0;color:#94a3b8;}
            QPushButton#modebtn{background:#eef2ff;color:#4338ca;font-size:10px;font-weight:700;
                  border:1px solid #e0e7ff;border-radius:7px;padding:4px 10px;}
            QPushButton#modebtn:hover{background:#e0e7ff;}
            QPushButton#modebtn:disabled{background:#f1f5f9;color:#94a3b8;border-color:#e2e8f0;}
        """)
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0); outer.addWidget(card)

        v = QVBoxLayout(card); v.setContentsMargins(14, 12, 14, 14); v.setSpacing(8)

        # Header (drag handle + close)
        head = QHBoxLayout()
        title = QLabel("SolutionsDesk · Voice"); title.setObjectName("title")
        closeb = QPushButton("✕"); closeb.setObjectName("close"); closeb.setFixedWidth(28)
        closeb.clicked.connect(self.close)
        head.addWidget(title); head.addStretch(1); head.addWidget(closeb)
        v.addLayout(head)

        self.status = QLabel("Ready. Press ▶ Start and speak your question.")
        self.status.setObjectName("status"); self.status.setWordWrap(True)
        v.addWidget(self.status)

        caphead = QHBoxLayout()
        capL = QLabel("TRANSCRIPT"); capL.setObjectName("capLabel")
        self.modeb = QPushButton(); self.modeb.setObjectName("modebtn")
        self.modeb.setToolTip("Switch between capturing just your mic, or your mic + the call audio")
        self.modeb.clicked.connect(self.on_toggle_mode)
        self.playb = QPushButton("▶ Start"); self.playb.setObjectName("play")
        self.playb.clicked.connect(self.on_play)
        self.stopb = QPushButton("■ Stop"); self.stopb.setObjectName("stop")
        self.stopb.clicked.connect(self.on_stop)
        self.stopb.setEnabled(False)
        caphead.addWidget(capL); caphead.addStretch(1)
        caphead.addWidget(self.modeb); caphead.addWidget(self.playb); caphead.addWidget(self.stopb)
        v.addLayout(caphead)
        self._refresh_mode_btn()
        self.caption = QTextEdit(); self.caption.setReadOnly(True); self.caption.setFixedHeight(70)
        v.addWidget(self.caption)

        self.sendb = QPushButton("Send to RAG"); self.sendb.setObjectName("send")
        self.sendb.clicked.connect(self.on_send)
        v.addWidget(self.sendb)

        ansL = QLabel("ANSWER"); ansL.setObjectName("ansLabel"); v.addWidget(ansL)
        self.answer = QTextEdit(); self.answer.setReadOnly(True)
        self.answer.setObjectName("answer"); self.answer.setMinimumHeight(330)
        v.addWidget(self.answer, 1)

        bridge.transcribed.connect(self.on_transcribed)
        bridge.answer.connect(self.answer.setHtml)
        bridge.status.connect(self.status.setText)

    def on_send(self):
        threading.Thread(target=ask_rag, daemon=True).start()

    def _refresh_mode_btn(self):
        self.modeb.setText("🎙 Me + call" if _capture_both else "🎙 Me only")

    def on_toggle_mode(self):
        global _capture_both
        _capture_both = not _capture_both
        self._refresh_mode_btn()
        self.status.setText("Capturing your mic + the call audio." if _capture_both
                            else "Capturing your mic only.")

    def on_play(self):
        """Start recording from the microphone (+ call audio if 'Me + call')."""
        global _captured
        _captured = ""
        self.caption.clear()
        try:
            start_recording()
        except Exception as e:
            self.status.setText(f"Microphone error: {e}")
            return
        self.playb.setEnabled(False)
        self.stopb.setEnabled(True)
        self.modeb.setEnabled(False)
        self.status.setText("● Recording you + call audio… press ■ Stop when done." if _capture_both
                            else "● Recording your mic… press ■ Stop when done.")

    def on_stop(self):
        """Stop recording and transcribe (in a worker thread — Whisper is a network call)."""
        self.stopb.setEnabled(False)
        self.status.setText("Transcribing…")
        threading.Thread(target=self._do_transcribe, daemon=True).start()

    def _do_transcribe(self):
        try:
            text = stop_and_transcribe()
        except Exception as e:
            bridge.status.emit(f"Transcription failed: {e}")
            bridge.transcribed.emit("")
            return
        bridge.transcribed.emit(text)

    def on_transcribed(self, text):
        global _captured
        _captured = text
        self.caption.setPlainText(text or "(Nothing heard — press ▶ Start to try again.)")
        self.playb.setEnabled(True)
        self.stopb.setEnabled(False)
        self.modeb.setEnabled(True)
        self.status.setText("Transcribed. Press Send to RAG, or ▶ Start to record again."
                            if text else "No speech detected. Press ▶ Start to try again.")

    # Frameless window dragging
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
    def mouseMoveEvent(self, e):
        if self._drag and e.buttons() & Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag)
    def mouseReleaseEvent(self, e):
        self._drag = None


def _kill_lock_holder():
    """Kill whatever process currently holds the single-instance lock port."""
    if os.name != "nt":
        return
    ps = (f"$c = Get-NetTCPConnection -LocalPort {SINGLETON_PORT} -State Listen "
          f"-ErrorAction SilentlyContinue; if ($c) {{ Stop-Process -Id $c.OwningProcess "
          f"-Force -ErrorAction SilentlyContinue }}")
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, timeout=8)
    except Exception:
        pass


def _claim_singleton():
    """Take over the single-instance lock so the NEWEST launch always wins."""
    def _try_bind():
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", SINGLETON_PORT))
        s.listen(1)
        return s
    try:
        return _try_bind()
    except OSError:
        _kill_lock_holder()
        for _ in range(20):
            try:
                return _try_bind()
            except OSError:
                time.sleep(0.25)
    return None


def main():
    lock = _claim_singleton()
    if lock is None:
        print("Could not claim single-instance lock — another window may be stuck.")
        return
    main._lock = lock  # keep the socket alive for the process lifetime

    app = QApplication(sys.argv)
    win = FloatingWindow()
    screen = app.primaryScreen().availableGeometry()
    win.move(screen.x() + 60, screen.y() + 60)
    win.show()
    win.raise_()
    win.activateWindow()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
