"""
Online Mode — always-on voice listening + a floating window that is HIDDEN from
screen sharing.

Flow:
    The window starts listening to the call audio the moment it opens (no Start/Stop).
    As people speak, their words appear live in the TRANSCRIPT box (each finished
    sentence is sent to the backend's /api/transcribe — Whisper — and appended).
    Press ENTER (or click "Send to RAG") -> the current transcript is sent to
    /api/chat/stream and the colored answer streams into the ANSWER box, then the
    transcript clears so it's ready for the next question.

Screen-share privacy:
    On Windows 10 (2004+) / 11 the window calls SetWindowDisplayAffinity with
    WDA_EXCLUDEFROMCAPTURE, so it stays visible on your physical monitor but is
    excluded from ALL screen capture — full-screen share, single-window share, and
    screenshots. It will NOT appear in Google Meet / Zoom / Teams screen shares.

Connects to the backend at SOLUTIONSDESK_BACKEND / backend.txt / DEFAULT_BACKEND
(see Config below). Transcription and the OpenAI key live on the server, so this
client needs no API key. Normally started by the web UI ("MODES → Online · …"),
but can also be run directly:  python online_mode.py
"""

import base64
import ctypes
import html as _html
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time

import httpx
import websocket   # websocket-client — live OpenAI Realtime transcription
import numpy as np
import soundcard as sc
from dotenv import load_dotenv

from PyQt6.QtCore import Qt, QObject, QTimer, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
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
TOKEN_URL      = f"{BACKEND_URL}/api/realtime-token"
API_KEY        = os.getenv("SOLUTIONSDESK_API_KEY", "").strip()   # optional; sent if set
SINGLETON_PORT = 49222          # single-instance lock (prevents duplicate windows)

# ── Live (streaming) transcription ───────────────────────────────────────────────
# We stream the call audio straight to OpenAI's Realtime API over a WebSocket and
# receive words as they're spoken. The real OpenAI key never ships in the .exe: the
# backend mints a short-lived ephemeral token (carrying the model/prompt/VAD config),
# and we connect directly with that. Audio must be 24 kHz mono PCM16.
REALTIME_WS_URL = "wss://api.openai.com/v1/realtime?intent=transcription"
STREAM_SR       = 24000             # OpenAI Realtime expects 24 kHz PCM16
STREAM_BLOCK    = STREAM_SR // 10   # send audio in 0.1s chunks


def _auth_headers() -> dict:
    """Send an API key header only if one is configured (server may require it)."""
    return {"X-API-Key": API_KEY} if API_KEY else {}


# ── Thread → UI signal bridge ───────────────────────────────────────────────────
class Bridge(QObject):
    transcript = pyqtSignal(str)    # engine → UI: full current transcript (committed + live)
    answer     = pyqtSignal(str)
    status     = pyqtSignal(str)


bridge = Bridge()

# ── Live transcript state ────────────────────────────────────────────────────────
# _committed = finalized utterances; _partial = the in-progress words currently
# streaming in. The displayed transcript (and what Enter sends) is committed + partial.
_committed   = ""
_partial     = ""
_text_lock   = threading.Lock()
_listening   = True             # master switch; False fully stops the stream
_paused      = False            # user can pause/resume without dropping the connection
_prompt_words: set = set()      # words from the biasing prompt — used to spot echoes


# ── Hallucination filters ────────────────────────────────────────────────────────
# On silence/noise the realtime model can hallucinate: it either echoes the biasing
# prompt verbatim, or emits text in random languages. We keep only English (Latin)
# and Hindi (Devanagari), and drop any line that looks like a prompt echo.
_FOREIGN_RANGES = (
    (0x0400, 0x04FF),   # Cyrillic
    (0x0600, 0x06FF),   # Arabic
    (0x3040, 0x30FF),   # Hiragana / Katakana
    (0x1100, 0x11FF),   # Hangul Jamo
    (0xAC00, 0xD7A3),   # Hangul syllables
    (0x4E00, 0x9FFF),   # CJK
)


def _has_foreign_script(text: str) -> bool:
    """True if the text contains scripts other than Latin/Devanagari (a hallucination)."""
    for ch in text:
        o = ord(ch)
        if any(lo <= o <= hi for lo, hi in _FOREIGN_RANGES):
            return True
    return False


def _is_prompt_echo(text: str) -> bool:
    """True if the line is mostly words from the biasing prompt (a leaked prompt echo)."""
    if not _prompt_words:
        return False
    words = re.findall(r"[a-z]+", text.lower())
    if len(words) < 6:
        return False
    hits = sum(1 for w in words if w in _prompt_words)
    return hits / len(words) >= 0.6


def _looks_hallucinated(text: str) -> bool:
    t = (text or "").strip()
    return bool(t) and (_has_foreign_script(t) or _is_prompt_echo(t))


def _current_transcript() -> str:
    with _text_lock:
        committed, partial = _committed, _partial
    # Hide a still-streaming partial that already looks like a hallucination/echo.
    if partial and _looks_hallucinated(partial):
        partial = ""
    return (f"{committed} {partial}".strip()) if partial else committed.strip()


def _emit_transcript():
    bridge.transcript.emit(_current_transcript())


def _get_token() -> str:
    """Ask our backend for a short-lived OpenAI Realtime ephemeral token."""
    global _prompt_words
    r = httpx.post(TOKEN_URL, headers=_auth_headers(), timeout=20)
    r.raise_for_status()
    data = r.json() or {}
    tok = data.get("token")
    if not tok:
        raise RuntimeError("backend returned no token")
    _prompt_words = set(re.findall(r"[a-z]+", (data.get("prompt") or "").lower()))
    return tok


def _stream_once(token: str):
    """Open one Realtime WebSocket session and stream the call audio until it ends."""
    ws_open = threading.Event()
    closed  = threading.Event()

    def on_open(_ws):
        ws_open.set()
        bridge.status.emit("● Live — transcribing the call in real time.")

    def on_message(_ws, message):
        global _committed, _partial
        try:
            ev = json.loads(message)
        except Exception:
            return
        t = ev.get("type", "")
        if t.endswith("transcription.delta"):
            with _text_lock:
                _partial += ev.get("delta", "")
            _emit_transcript()
        elif t.endswith("transcription.completed"):
            seg = (ev.get("transcript", "") or "").strip()
            with _text_lock:
                # Drop prompt echoes / foreign-language hallucinations; keep real speech.
                if seg and not _looks_hallucinated(seg):
                    _committed = (f"{_committed} {seg}".strip()) if _committed else seg
                _partial = ""
            _emit_transcript()
        elif t == "error":
            msg = (ev.get("error") or {}).get("message", "stream error")
            bridge.status.emit(f"OpenAI: {msg}")

    def on_close(_ws, *_a):
        closed.set()

    def on_error(_ws, err):
        bridge.status.emit(f"Stream error: {err}")
        closed.set()

    ws = websocket.WebSocketApp(
        REALTIME_WS_URL,
        header=[f"Authorization: Bearer {token}"],   # GA API: no OpenAI-Beta header
        on_open=on_open, on_message=on_message, on_close=on_close, on_error=on_error,
    )
    threading.Thread(target=ws.run_forever, daemon=True).start()
    if not ws_open.wait(timeout=12):
        try: ws.close()
        except Exception: pass
        return

    # Capture the call audio (loopback = "what you hear") and stream it as PCM16.
    try:
        speaker = sc.default_speaker()
        source  = sc.get_microphone(speaker.name, include_loopback=True)
        with source.recorder(samplerate=STREAM_SR, channels=1) as rec:
            while _listening and not closed.is_set():
                block = rec.record(numframes=STREAM_BLOCK).flatten()
                if _paused:
                    continue                    # drop audio while paused (connection stays up)
                pcm16 = (np.clip(block, -1.0, 1.0) * 32767).astype("<i2").tobytes()
                try:
                    ws.send(json.dumps({"type": "input_audio_buffer.append",
                                        "audio": base64.b64encode(pcm16).decode("ascii")}))
                except Exception:
                    break
    except Exception as e:
        bridge.status.emit(f"Audio capture error: {e}")
    finally:
        try: ws.close()
        except Exception: pass


def _run_stream():
    """Keep a live transcription session up, reconnecting if it drops."""
    while _listening:
        try:
            token = _get_token()
        except Exception as e:
            bridge.status.emit(f"Token error: {e} — retrying…")
            time.sleep(3)
            continue
        _stream_once(token)
        if _listening:
            bridge.status.emit("Reconnecting…")
            time.sleep(1)


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
def ask_rag(query: str):
    query = (query or "").strip()
    if not query:
        bridge.answer.emit("(Nothing to send yet — let the other person speak first.)")
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


# ── Hide the window from screen capture (Windows 10 2004+ / 11) ──────────────────
WDA_EXCLUDEFROMCAPTURE = 0x00000011


def _exclude_from_capture(widget) -> bool:
    """Make the window invisible to screen sharing / screenshots (Windows only).

    Returns True if the OS accepted the call. The window stays visible on the real
    monitor; capture pipelines (Meet/Zoom/Teams, PrintScreen) simply don't see it.
    """
    if os.name != "nt":
        return False
    try:
        hwnd = int(widget.winId())
        ok = ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)
        return bool(ok)
    except Exception:
        return False


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
            QPushButton#mini{background:#eef2ff;color:#4338ca;font-size:10px;font-weight:700;
                  border:1px solid #e0e7ff;border-radius:7px;padding:4px 10px;}
            QPushButton#mini:hover{background:#e0e7ff;}
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

        self.status = QLabel("Starting microphone…")
        self.status.setObjectName("status"); self.status.setWordWrap(True)
        v.addWidget(self.status)

        # Transcript header + live controls (Pause / Clear)
        caphead = QHBoxLayout()
        capL = QLabel("LIVE TRANSCRIPT"); capL.setObjectName("capLabel")
        self.pauseb = QPushButton("⏸ Pause"); self.pauseb.setObjectName("mini")
        self.pauseb.setToolTip("Pause / resume listening")
        self.pauseb.clicked.connect(self.on_pause)
        self.clearb = QPushButton("Clear"); self.clearb.setObjectName("mini")
        self.clearb.setToolTip("Clear the current transcript")
        self.clearb.clicked.connect(self.on_clear)
        caphead.addWidget(capL); caphead.addStretch(1)
        caphead.addWidget(self.pauseb); caphead.addWidget(self.clearb)
        v.addLayout(caphead)

        self.caption = QTextEdit(); self.caption.setReadOnly(True); self.caption.setFixedHeight(110)
        v.addWidget(self.caption)

        self.sendb = QPushButton("Send to RAG  (Enter)"); self.sendb.setObjectName("send")
        self.sendb.clicked.connect(self.on_send)
        v.addWidget(self.sendb)

        ansL = QLabel("ANSWER"); ansL.setObjectName("ansLabel"); v.addWidget(ansL)
        self.answer = QTextEdit(); self.answer.setReadOnly(True)
        self.answer.setObjectName("answer"); self.answer.setMinimumHeight(300)
        v.addWidget(self.answer, 1)

        bridge.transcript.connect(self.on_transcript)
        bridge.answer.connect(self.answer.setHtml)
        bridge.status.connect(self.status.setText)

        # ENTER (main + numpad) sends the transcript from anywhere in the window.
        for key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            sc_ = QShortcut(QKeySequence(key), self)
            sc_.setContext(Qt.ShortcutContext.WindowShortcut)
            sc_.activated.connect(self.on_send)

    # ── live transcript ──
    def on_transcript(self, text):
        """Render the full live transcript (committed words + the streaming partial)."""
        self.caption.setPlainText(text)
        sb = self.caption.verticalScrollBar(); sb.setValue(sb.maximum())

    def on_send(self):
        global _committed, _partial
        query = _current_transcript()
        with _text_lock:
            _committed, _partial = "", ""     # clear so the next question starts fresh
        self.caption.clear()
        if not query:
            self.status.setText("Nothing to send yet — wait for some speech.")
            return
        threading.Thread(target=ask_rag, args=(query,), daemon=True).start()

    def on_clear(self):
        global _committed, _partial
        with _text_lock:
            _committed, _partial = "", ""
        self.caption.clear()

    def on_pause(self):
        global _paused
        _paused = not _paused
        self.pauseb.setText("▶ Resume" if _paused else "⏸ Pause")
        self.status.setText("⏸ Paused — not listening." if _paused
                            else "● Live — transcribing the call in real time.")

    def closeEvent(self, e):
        global _listening
        _listening = False
        super().closeEvent(e)

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

    # Hide from screen sharing/screenshots. winId() is valid only after show();
    # a 0ms timer also re-applies once the native handle is fully realized.
    def _apply_hide():
        if not _exclude_from_capture(win):
            bridge.status.emit("⚠ Screen-hide unavailable on this Windows version.")
    _apply_hide()
    QTimer.singleShot(0, _apply_hide)

    # Start the always-on live transcription stream.
    threading.Thread(target=_run_stream, daemon=True).start()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
