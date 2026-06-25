"""
Online Mode — always-on voice listening + a floating window that is HIDDEN from
screen sharing.

Flow:
    The window starts listening the moment it opens (no Start/Stop). It captures BOTH
    sides of the call on two independent streams — the call audio (loopback = "Them")
    and your microphone ("You") — and each finished sentence appears live in the
    TRANSCRIPT box, labeled by who spoke.
    Press ENTER (or click "Send to RAG") -> the current transcript is sent to
    /api/chat/stream and the colored answer streams into the ANSWER box, then the
    transcript clears so it's ready for the next question.
    Toggle AUTO so the window answers the caller's questions automatically: when the
    other person stops talking and their last turn looks like a question, it sends on
    its own — no Enter needed.

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
import uuid
from urllib.parse import urlencode, quote

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

# ── Deepgram Nova-3 streaming (toggle via STT_ENGINE=deepgram) ────────────────────
# When STT_ENGINE=deepgram, the window streams the SAME 24 kHz PCM16 loopback audio
# straight to Deepgram's Nova-3 WebSocket (raw binary frames, not base64 JSON) and
# authenticates with DEEPGRAM_API_KEY directly. Both live in .env next to this script.
# Nova-3 "keyterm prompting" replaces the OpenAI WHISPER_PROMPT jargon hint. Default
# engine stays "openai" so this is opt-in and the existing path is untouched.
STT_ENGINE        = os.getenv("STT_ENGINE", "openai").strip().lower()
DEEPGRAM_API_KEY  = os.getenv("DEEPGRAM_API_KEY", "").strip()
# Language: "multi" = Nova-3 multilingual code-switching (English + Hindi/"Hinglish" in
# the same sentence). "en" = English-only (slightly higher English accuracy, but Hindi
# is mis-transcribed). Keyterm prompting (below) works in both. Default "multi".
DEEPGRAM_LANGUAGE = os.getenv("DEEPGRAM_LANGUAGE", "multi").strip()
DEEPGRAM_KEYTERMS = [
    # Core domain nouns — these are the words actually spoken every call, and the ones
    # the answer hinges on. Without biasing, Nova-3 mishears "trucks"/"clients" as
    # "jets", which collapses RAG retrieval to general knowledge (no fleet match).
    "truck", "trucks", "fleet", "fleet management", "vehicle", "vehicles",
    "client", "clients", "logistics", "location tracking", "driver", "drivers",
    # Axestrack/logistics jargon
    "overspeeding", "over-speeding", "GPS tracking", "real-time vehicle tracking",
    "geofencing", "ePOD", "electronic proof of delivery", "RFID",
    "driver monitoring system", "driver fatigue", "dashcam", "ADAS", "DMS", "FMS",
    "yard management", "weighbridge", "trip management", "route optimization",
    "telematics", "SIM tracking", "consignment", "in-plant logistics", "XSWIFT", "CPL",
]
_dg_params = urlencode([
    ("model", "nova-3"), ("language", DEEPGRAM_LANGUAGE),
    ("encoding", "linear16"), ("sample_rate", str(STREAM_SR)),
    ("channels", "1"), ("interim_results", "true"), ("smart_format", "true"),
    ("punctuate", "true"),
])
DEEPGRAM_WS_URL = ("wss://api.deepgram.com/v1/listen?" + _dg_params
                   + "".join(f"&keyterm={quote(k)}" for k in DEEPGRAM_KEYTERMS))

# ── Both-sides capture + auto-answer ──────────────────────────────────────────────
# We run TWO independent capture pipelines (the approach Natively uses): the call
# audio (loopback, "them") and your microphone ("me"). Each gets its own STT session;
# every finished utterance is tagged with which side spoke, so the transcript — and the
# question the backend extracts — knows who asked. No diarization needed; the speaker
# label is simply which pipeline produced the text.
MIC_CAPTURE  = os.getenv("MIC_CAPTURE", "1").strip().lower() not in ("0", "false", "no")
# Pin the "me" channel to a specific input (name substring, e.g. "Headset"). Empty =
# system default mic. A dedicated HEADSET mic is the cleanest both-sides setup: it
# captures only your voice, so there's no speaker echo to duck at all.
MIC_DEVICE   = os.getenv("MIC_DEVICE", "").strip()
MAX_SEGMENTS = 40            # rolling "hot window" cap — keeps the transcript focused
_LABEL       = {"them": "Them:", "me": "You:"}

# Echo ducking (software half-duplex): the remote voice comes out of your speakers and
# leaks into the mic, so it would otherwise be transcribed twice. While the call audio
# is active we DROP mic frames. This is the cheap stand-in for the hardware AEC that a
# native app would use — wearing HEADPHONES removes the echo entirely (best quality).
ECHO_GATE        = os.getenv("ECHO_GATE", "1").strip().lower() not in ("0", "false", "no")
ECHO_RMS_THRESH  = float(os.getenv("ECHO_RMS_THRESH", "0.012"))  # loopback "is speaking" level
ECHO_HANGOVER_MS = int(os.getenv("ECHO_HANGOVER_MS", "350"))     # keep ducking briefly after

# Auto-answer: when ON, we wait for the caller to stop talking, then (if their last turn
# looks like a question) answer automatically — no Enter needed. Manual Enter always
# works too. Off by default (opt-in), toggled from the window.
AUTO_ANSWER_DEFAULT = os.getenv("AUTO_ANSWER", "0").strip().lower() in ("1", "true", "yes")
AUTO_SILENCE_MS     = int(os.getenv("AUTO_SILENCE_MS", "1200"))  # caller end-of-turn debounce


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
# _segments = finalized utterances, each tagged with who spoke ('them'/'me') and a
# timestamp so the two channels interleave in time. _partials = the in-progress words
# currently streaming in, per channel. The displayed transcript (and what Enter sends)
# is the committed segments + the live partials, labeled by speaker.
_segments: list = []                 # [{"who": "them"|"me", "text": str, "ts": float}]
_partials = {"them": "", "me": ""}   # live, still-streaming text per channel
_text_lock   = threading.Lock()
_listening   = True             # master switch; False fully stops the stream
_paused      = False            # user can pause/resume without dropping the connection
_prompt_words: set = set()      # words from the biasing prompt — used to spot echoes
_session_id  = uuid.uuid4().hex  # backend follow-up memory key; rotated on Clear

# Echo ducking: timestamp until which the call audio counts as "active", so the mic
# pipeline ducks its leaked echo. Written by the 'them' loop, read by the 'me' loop.
_remote_active_until = 0.0

# Auto-answer state.
_auto_mode   = AUTO_ANSWER_DEFAULT
_auto_timer  = None             # debounce timer; reset on every new 'them' segment
_auto_lock   = threading.Lock()
_answered_ts = 0.0              # ts of the last 'them' turn we auto-answered (no repeats)
_asking      = False           # an auto-answer is in flight (don't overlap)


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
    """The full live conversation, labeled by speaker and ordered in time:
        Them: …
        You: …
    Includes both committed segments and the still-streaming partials (a partial that
    already looks like a hallucination/echo is hidden)."""
    with _text_lock:
        segs = sorted(_segments, key=lambda s: s["ts"])
        partials = dict(_partials)
    lines = [f"{_LABEL[s['who']]} {s['text']}" for s in segs]
    for who in ("them", "me"):
        p = partials.get(who, "")
        if p and not _looks_hallucinated(p):
            lines.append(f"{_LABEL[who]} {p}")
    return "\n".join(lines).strip()


def _emit_transcript():
    bridge.transcript.emit(_current_transcript())


# ── Capture sources + echo ducking ────────────────────────────────────────────────
def _open_source(who: str):
    """Open the audio source for one channel: the call audio (loopback) for 'them',
    your microphone for 'me' (MIC_DEVICE override, else the system default)."""
    spk = sc.default_speaker()
    if who == "them":
        return sc.get_microphone(spk.name, include_loopback=True)   # what you hear
    if MIC_DEVICE:
        try:
            return sc.get_microphone(MIC_DEVICE, include_loopback=False)
        except Exception as e:
            bridge.status.emit(f"Mic '{MIC_DEVICE}' not found ({e}) — using default mic.")
    return sc.get_microphone(sc.default_microphone().name)          # your mic


def _skip_audio(who: str, block) -> bool:
    """Whether to DROP this audio block before sending it to STT.

    Also updates the shared 'remote is speaking' window from the loopback channel so the
    mic can duck the echo. Returns True for paused, and (for the mic) while the call
    audio is active — that's the software half-duplex echo gate."""
    global _remote_active_until
    if _paused:
        return True
    if who == "them":
        if ECHO_GATE and block.size:
            rms = float(np.sqrt(np.mean(np.square(block))))
            if rms > ECHO_RMS_THRESH:
                _remote_active_until = time.time() + ECHO_HANGOVER_MS / 1000.0
        return False
    # who == 'me': drop mic audio while the call audio is playing, so the remote voice
    # leaking back through your speakers isn't transcribed a second time on this channel.
    return bool(ECHO_GATE and time.time() < _remote_active_until)


# ── Auto-answer (fires on the caller's end-of-turn) ───────────────────────────────
_QUESTION_WORDS = ("how", "what", "why", "when", "where", "which", "who", "can",
                   "could", "do", "does", "did", "is", "are", "will", "would",
                   "should", "tell me", "explain", "any")


def _looks_like_question(text: str) -> bool:
    """Cheap local gate so we don't auto-fire on statements/backchannel. The backend's
    extractor is the real judge; this just avoids spamming it."""
    t = (text or "").strip().lower()
    if not t:
        return False
    return ("?" in t) or any(t.startswith(w) for w in _QUESTION_WORDS)


def _schedule_auto_ask():
    """Debounce: (re)start a short silence timer; fire one auto-answer once the other
    party stops talking. Reset on every new 'them' segment so we wait for a real pause."""
    global _auto_timer
    if not _auto_mode:
        return
    with _auto_lock:
        if _auto_timer:
            _auto_timer.cancel()
        _auto_timer = threading.Timer(AUTO_SILENCE_MS / 1000.0, _maybe_auto_ask)
        _auto_timer.daemon = True
        _auto_timer.start()


def _maybe_auto_ask():
    """Auto-answer the caller's latest turn — only if it's a new, question-like 'them'
    utterance we haven't already answered."""
    global _answered_ts, _asking
    if not _auto_mode or _asking:
        return
    with _text_lock:
        them = [s for s in _segments if s["who"] == "them"]
    if not them:
        return
    last = them[-1]
    if last["ts"] <= _answered_ts or not _looks_like_question(last["text"]):
        return
    _answered_ts = last["ts"]
    transcript = _current_transcript()

    def _run():
        global _asking
        _asking = True
        try:
            ask_rag(transcript)        # don't clear in auto mode — keep the rolling window
        finally:
            _asking = False
    threading.Thread(target=_run, daemon=True).start()


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


def _stream_once(token: str, who: str):
    """Open one Realtime WebSocket session and stream ONE channel's audio until it ends.
    who = 'them' (call/loopback audio) or 'me' (your microphone)."""
    ws_open = threading.Event()
    closed  = threading.Event()

    def on_open(_ws):
        ws_open.set()
        bridge.status.emit("● Live — transcribing both sides of the call in real time.")

    def on_message(_ws, message):
        try:
            ev = json.loads(message)
        except Exception:
            return
        t = ev.get("type", "")
        if t.endswith("transcription.delta"):
            with _text_lock:
                _partials[who] += ev.get("delta", "")
            _emit_transcript()
        elif t.endswith("transcription.completed"):
            seg = (ev.get("transcript", "") or "").strip()
            real = bool(seg) and not _looks_hallucinated(seg)
            with _text_lock:
                # Drop prompt echoes / foreign-language hallucinations; keep real speech.
                if real:
                    _segments.append({"who": who, "text": seg, "ts": time.time()})
                    if len(_segments) > MAX_SEGMENTS:
                        del _segments[:-MAX_SEGMENTS]
                _partials[who] = ""
            _emit_transcript()
            if who == "them" and real:
                _schedule_auto_ask()
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

    # Capture this channel's audio and stream it as PCM16.
    try:
        source = _open_source(who)
        with source.recorder(samplerate=STREAM_SR, channels=1) as rec:
            while _listening and not closed.is_set():
                block = rec.record(numframes=STREAM_BLOCK).flatten()
                if _skip_audio(who, block):
                    continue                    # paused or echo-ducked (connection stays up)
                pcm16 = (np.clip(block, -1.0, 1.0) * 32767).astype("<i2").tobytes()
                try:
                    ws.send(json.dumps({"type": "input_audio_buffer.append",
                                        "audio": base64.b64encode(pcm16).decode("ascii")}))
                except Exception:
                    break
    except Exception as e:
        bridge.status.emit(f"Audio capture error ({who}): {e}")
    finally:
        try: ws.close()
        except Exception: pass


def _stream_once_deepgram(who: str):
    """Open one Deepgram Nova-3 streaming session and stream ONE channel's audio until
    it ends. who = 'them' (call/loopback audio) or 'me' (your microphone).

    Differences from the OpenAI path: we authenticate with the API key directly, send
    raw PCM16 *binary* frames (not base64 JSON), and each interim result is the full
    current-segment text (replace the partial), with is_final marking a committed segment.
    """
    ws_open = threading.Event()
    closed  = threading.Event()

    def on_open(_ws):
        ws_open.set()
        bridge.status.emit("● Live — Deepgram Nova-3 transcribing both sides in real time.")

    def on_message(_ws, message):
        try:
            ev = json.loads(message)
        except Exception:
            return
        if ev.get("type") != "Results":
            return
        alt = (ev.get("channel", {}).get("alternatives") or [{}])[0]
        seg = (alt.get("transcript") or "").strip()
        if ev.get("is_final"):
            with _text_lock:
                if seg:
                    _segments.append({"who": who, "text": seg, "ts": time.time()})
                    if len(_segments) > MAX_SEGMENTS:
                        del _segments[:-MAX_SEGMENTS]
                _partials[who] = ""
            _emit_transcript()
            if who == "them" and seg:
                _schedule_auto_ask()
        else:
            # Interim = full text of the in-progress segment → replace, don't append.
            with _text_lock:
                _partials[who] = seg
            _emit_transcript()

    def on_close(_ws, *_a):
        closed.set()

    def on_error(_ws, err):
        bridge.status.emit(f"Deepgram error: {err}")
        closed.set()

    ws = websocket.WebSocketApp(
        DEEPGRAM_WS_URL,
        header=[f"Authorization: Token {DEEPGRAM_API_KEY}"],
        on_open=on_open, on_message=on_message, on_close=on_close, on_error=on_error,
    )
    threading.Thread(target=ws.run_forever, daemon=True).start()
    if not ws_open.wait(timeout=12):
        try: ws.close()
        except Exception: pass
        return

    # Capture this channel's audio and stream it as raw PCM16.
    try:
        source = _open_source(who)
        with source.recorder(samplerate=STREAM_SR, channels=1) as rec:
            while _listening and not closed.is_set():
                block = rec.record(numframes=STREAM_BLOCK).flatten()
                if _skip_audio(who, block):
                    # No audio while paused / echo-ducked — keep Deepgram's socket alive
                    # (it drops the connection after ~10s of silence otherwise).
                    try: ws.send(json.dumps({"type": "KeepAlive"}))
                    except Exception: break
                    continue
                pcm16 = (np.clip(block, -1.0, 1.0) * 32767).astype("<i2").tobytes()
                try:
                    ws.send(pcm16, opcode=websocket.ABNF.OPCODE_BINARY)
                except Exception:
                    break
    except Exception as e:
        bridge.status.emit(f"Audio capture error ({who}): {e}")
    finally:
        try:
            ws.send(json.dumps({"type": "CloseStream"}))
            ws.close()
        except Exception:
            pass


def _run_stream(who: str):
    """Keep a live transcription session up for one channel, reconnecting if it drops.
    who = 'them' (call/loopback audio) or 'me' (your microphone)."""
    while _listening:
        # Deepgram path: connect directly with the key (no backend token needed).
        if STT_ENGINE == "deepgram":
            if not DEEPGRAM_API_KEY:
                bridge.status.emit("DEEPGRAM_API_KEY not set — add it to .env, then restart.")
                time.sleep(5)
                continue
            _stream_once_deepgram(who)
            if _listening:
                bridge.status.emit("Reconnecting…")
                time.sleep(1)
            continue
        # Default path: OpenAI Realtime via a short-lived backend token.
        try:
            token = _get_token()
        except Exception as e:
            bridge.status.emit(f"Token error: {e} — retrying…")
            time.sleep(3)
            continue
        _stream_once(token, who)
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


def _q_header(q: str) -> str:
    """Small 'Q: …' banner showing the question the backend extracted from the transcript."""
    if not q:
        return ""
    return (f'<div style="margin:0 0 10px 0;padding:7px 10px;background:#eef2ff;'
            f'border-left:3px solid #6366f1;border-radius:6px;color:#3730a3;'
            f'font-size:11px;"><b>Q:</b> {_esc(q)}</div>')


# ── Send the transcript to the backend (which extracts the relevant question) ─────
def ask_rag(transcript: str):
    transcript = (transcript or "").strip()
    if not transcript:
        bridge.answer.emit("(Nothing to send yet — let the other person speak first.)")
        return
    bridge.answer.emit("Thinking…")
    # Send the whole transcript; the backend extracts the latest relevant question and
    # streams the answer. session_id lets the backend remember prior turns so follow-ups
    # resolve even though we clear the box each Enter. (messages[] is an older-backend fallback.)
    payload = {"transcript": transcript, "session_id": _session_id,
               "messages": [{"role": "user", "content": transcript}]}
    picked = ""
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
                        if ev == "question":       # the relevant part the backend picked
                            picked = obj.get("text", "")
                            bridge.answer.emit(_q_header(picked) + '<p style="color:#64748b;">Thinking…</p>')
                            continue
                        got_any = True
                        bridge.answer.emit(_q_header(picked) + blocks_to_html(obj))
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
        self.setWindowOpacity(0.99)          # subtle see-through, like the web chat
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
        # Send the whole transcript, then clear the box so the next turn starts fresh.
        # The backend remembers this turn (via session_id), so follow-ups still resolve.
        transcript = _current_transcript()
        if not transcript.strip():
            self.status.setText("Nothing to send yet — wait for some speech.")
            return
        threading.Thread(target=ask_rag, args=(transcript,), daemon=True).start()
        with _text_lock:
            _segments.clear()
            _partials["them"] = _partials["me"] = ""
        self.caption.clear()

    def on_clear(self):
        # Full reset: wipe the box AND start a new session so the backend forgets
        # the previous conversation (no follow-up carryover into the next topic).
        global _session_id, _answered_ts
        with _text_lock:
            _segments.clear()
            _partials["them"] = _partials["me"] = ""
        _session_id = uuid.uuid4().hex
        _answered_ts = 0.0
        self.caption.clear()
        self.status.setText("Cleared — new conversation.")

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

    # Start the always-on live transcription — one stream per side of the call:
    # 'them' = the call audio (loopback), 'me' = your microphone. Each runs its own STT
    # session and tags its text, so the transcript knows who spoke (no diarization).
    threading.Thread(target=_run_stream, args=("them",), daemon=True).start()
    if MIC_CAPTURE:
        threading.Thread(target=_run_stream, args=("me",), daemon=True).start()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
