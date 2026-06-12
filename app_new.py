import os
import re
import sys
import glob
import subprocess
import json as _json
from datetime import datetime, timezone
from flask import Flask, render_template, request, jsonify, send_file, Response, stream_with_context
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'solutionsdesk-dev-key')

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["100 per hour"],
    storage_uri="memory://"
)

from src.rag.langgraph_workflow import RAGWorkflow

rag = RAGWorkflow()
_rag_ready = rag.initialize_tier_retrieval()
rag.build_graph()

FEATURE_SHEET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'feature_sheet')
RAW_PROPOSALS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'raw_proposals')


# ── Block converters ──────────────────────────────────────────────────────────
# Each "cited" block item carries:
#   text : the sentence/bullet
#   src  : "feature" (green) | "proposal" (blue) | "llm" (amber)  → drives highlight color
#   href : clickable source link (catalog file / proposal file), or "" for none
#   ref  : short citation label shown as a chip (e.g. "XSWIFT", "ATUL.docx · p.5")

def _split_points(text: str) -> list:
    """Fallback: split a prose description into short bullet points (used only when
    the LLM didn't return a structured `points` list)."""
    parts = re.split(r'\.\s+|;\s+|\s+—\s+', (text or '').strip())
    return [p.strip().rstrip('.') for p in parts if len(p.strip()) > 2]


def _solution_item(s: dict) -> dict:
    """A recommended-solution card: bold feature name + bullet points.
    Feature-backed → green + catalog link; else LLM → amber."""
    fid  = f" ({s['id']})" if s.get("id") else ""
    name = f"{s.get('name', '')}{fid}".strip()
    pts  = s.get("points")
    points = ([str(p).strip() for p in pts if str(p).strip()]
              if isinstance(pts, list) and pts else _split_points(s.get("description", "")))
    prod = (s.get("product") or "").strip().upper()
    if s.get("id") and prod in ("XSWIFT", "CPL"):
        return {"text": name, "points": points, "src": "feature", "href": f"/api/catalog-file/{prod}", "ref": prod}
    return {"text": name, "points": points, "src": "llm", "href": "", "ref": "Model Knowledge"}


def _proposal_point_items(finding: dict) -> list:
    """One client's proposal findings as a single blue card with bullet points,
    linked to the doc; page ref shown inline per bullet."""
    fname  = finding.get("file", "")
    href   = f"/api/proposal-file/{fname}" if fname else ""
    points = []
    for kp in finding.get("key_points", []):
        if isinstance(kp, dict):
            text = kp.get("text", "")
            page = kp.get("page", "")
        else:
            text, page = str(kp), ""
        if not text:
            continue
        points.append(f"{text}  ({page})" if page else text)
    if not points:
        return []
    return [{"text": "", "points": points, "src": "proposal", "href": href, "ref": fname}]


def _past_items(past: list) -> list:
    """Similar-deployment bullets → blue (proposal-derived), no direct link."""
    items = []
    for p in past:
        text = f"{p.get('client')} ({p.get('industry')}) — {p.get('summary', '')}".strip()
        if text:
            items.append({"text": text, "src": "proposal", "href": "", "ref": p.get("client", "")})
    return items


def _cited_block(title: str, items: list) -> dict:
    return {"type": "cited", "title": title, "items": items}


def _json_to_blocks(data: dict, badge) -> dict:
    blocks = []
    source_type = data.get("source_type", "feature_catalog")

    if source_type == "proposal":
        badge = {"label": "From Proposals", "tone": "blue"}
    elif source_type == "llm_knowledge":
        badge = {"label": "General Knowledge", "tone": "amber"}
    else:
        badge = {"label": "Available", "tone": "green"} if (
            data.get("solutions") or data.get("feature")
        ) else None

    solutions = data.get("solutions", [])

    # 1) Intro paragraph — neutral, no highlight
    opening = data.get("opening", "")
    if opening:
        blocks.append({"type": "p", "text": opening})

    # 2) Recommended Solutions FIRST (right after the intro)
    if source_type == "feature_catalog" and data.get("feature"):
        # Single-feature detail view → one green block linked to its product
        feat = data["feature"]
        prod = (feat.get("product") or "").strip().upper()
        href = f"/api/catalog-file/{prod}" if prod in ("XSWIFT", "CPL") else ""
        detail_items = []
        for label, key in [("What it does", "what_it_does"), ("Business Value", "business_value"),
                           ("Dependencies", "dependencies"), ("Sales Talking Point", "sales_pitch")]:
            if feat.get(key):
                detail_items.append({"text": f"{label}: {feat[key]}", "src": "feature",
                                     "href": href, "ref": prod})
        if detail_items:
            blocks.append(_cited_block(f"{feat.get('name')} ({feat.get('id')})", detail_items))
        related = [_solution_item(r) for r in data.get("related", [])]
        if related:
            blocks.append(_cited_block("Related Features", related))
    else:
        sol_items = [_solution_item(s) for s in solutions]
        if sol_items:
            blocks.append(_cited_block("Recommended Solutions", sol_items))

    # 3) Evidence from proposals (Tier 2) — blue, per-bullet doc + page links
    if source_type == "proposal":
        for finding in data.get("proposal_findings", []):
            pts = _proposal_point_items(finding)
            if pts:
                client   = finding.get("client", "")
                industry = finding.get("industry", "")
                title = f"From {client} Proposal ({industry})" if industry else f"From {client} Proposal"
                blocks.append(_cited_block(title, pts))

    # 4) Similar deployments — blue
    past = _past_items(data.get("past_implementations", []))
    if past:
        blocks.append(_cited_block("Similar Deployments", past))

    # 5) LLM reasoning note (Tier 3) — amber
    if source_type == "llm_knowledge":
        reasoning = data.get("reasoning", "") or (
            "This answer is based on general industry knowledge. "
            "No direct match was found in the Axestrack feature catalog or past proposals."
        )
        blocks.append({"type": "note", "text": reasoning})

    return {"badge": badge, "blocks": blocks}


def _text_to_blocks(answer: str, source: str) -> list:
    """Fallback parser for plain-text answers (when LLM skips JSON format)."""
    blocks = []
    current_list_title = None
    current_list_items = []
    para_lines = []

    def flush_para():
        if para_lines:
            text = ' '.join(para_lines).strip()
            if text:
                blocks.append({"type": "p", "text": text})
            para_lines.clear()

    def flush_list():
        nonlocal current_list_title, current_list_items
        if current_list_items:
            blocks.append({
                "type": "list",
                "title": current_list_title or "Details",
                "items": list(current_list_items),
            })
        current_list_title = None
        current_list_items = []

    for raw_line in answer.strip().split('\n'):
        line = raw_line.strip()
        if not line:
            flush_para()
            continue
        h = re.match(r'^#{1,3}\s+(.+)', line)
        if h:
            flush_para(); flush_list()
            current_list_title = h.group(1).strip()
            continue
        bold = re.match(r'^\*\*(.+?)\*\*:?\s*$', line)
        if bold:
            flush_para(); flush_list()
            current_list_title = bold.group(1).strip()
            continue
        if line.endswith(':') and len(line) < 80 and not line.startswith(('-', '*', '•')):
            flush_para(); flush_list()
            current_list_title = line.rstrip(':').strip()
            continue
        b = re.match(r'^[-*•]\s+(.+)', line)
        if b:
            flush_para()
            current_list_items.append(b.group(1).strip())
            continue
        nb = re.match(r'^\d+[.)]\s+(.+)', line)
        if nb:
            flush_para()
            current_list_items.append(nb.group(1).strip())
            continue
        flush_list()
        para_lines.append(line)

    flush_para()
    flush_list()

    if source and 'Feature Catalogue' in source:
        source_clean = re.sub(r'^\[Source: Feature Catalogue - Best match: (.+)\]$', r'\1', source)
        blocks.append({
            "type": "sources",
            "title": "Referenced",
            "items": [{"title": source_clean, "meta": "Feature Catalogue"}],
        })

    return blocks


def _repair_json(s: str) -> str:
    """Best-effort close of a partially-streamed JSON string so it can be parsed.
    Closes any open string and brackets, drops dangling keys/colons."""
    s = s.strip()
    s = re.sub(r'^```(?:json)?\s*', '', s)
    stack, in_str, esc = [], False, False
    for ch in s:
        if esc:
            esc = False; continue
        if ch == '\\':
            if in_str: esc = True
            continue
        if ch == '"':
            in_str = not in_str; continue
        if in_str:
            continue
        if ch in '{[':
            stack.append(ch)
        elif ch == '}' and stack and stack[-1] == '{':
            stack.pop()
        elif ch == ']' and stack and stack[-1] == '[':
            stack.pop()
    rep = s
    if in_str:
        rep += '"'
    rep = rep.rstrip().rstrip(',')
    if re.search(r':\s*$', rep):         # dangling "key": with no value yet
        rep += 'null'
    rep = re.sub(r',\s*"[^"]*"$', '', rep)   # dangling key after a comma
    rep = re.sub(r'\{\s*"[^"]*"$', '{', rep) # dangling key right after {
    for ch in reversed(stack):
        rep += '}' if ch == '{' else ']'
    return rep


def _safe_partial_json(text: str):
    """Parse a partial/streaming JSON answer, returning a dict or None."""
    t = text.strip()
    t = re.sub(r'^```(?:json)?\s*', '', t)
    t = re.sub(r'\s*```$', '', t)
    if not t:
        return None
    try:
        return _json.loads(_repair_json(t))
    except Exception:
        return None


def _partial_to_blocks(text: str, source_type: str):
    """Build blocks from an in-progress streamed answer; None if not yet parseable."""
    data = _safe_partial_json(text)
    if not isinstance(data, dict):
        return None
    data["source_type"] = source_type
    try:
        return _json_to_blocks(data, None)
    except Exception:
        return None


def _answer_to_blocks(answer: str, source: str, tier: int, source_type: str = "feature_catalog") -> dict:
    # Badge is determined after JSON parse so source_type is known — set placeholder here
    badge = None  # will be set inside _json_to_blocks based on source_type

    text = answer.strip()
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)

    try:
        data = _json.loads(text)
        # Inject the programmatically determined source_type so the renderer uses the right branch
        data["source_type"] = source_type
        return _json_to_blocks(data, badge)
    except _json.JSONDecodeError:
        return {"badge": badge, "blocks": _text_to_blocks(text, source)}


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/chat', methods=['POST'])
@limiter.limit("30 per hour")
def chat():
    data = request.get_json()
    messages = data.get('messages', []) if data else []

    if not messages:
        return jsonify({'error': 'No messages provided'}), 400

    query = ''
    for m in reversed(messages):
        if m.get('role') == 'user':
            query = str(m.get('content', '')).strip()
            break

    if not query:
        return jsonify({'error': 'No user query found'}), 400

    try:
        result = rag.invoke(query, session_id='default')
        if not result.get('success'):
            return jsonify({'error': result.get('answer', 'Pipeline error')}), 500

        return jsonify(_answer_to_blocks(
            result['answer'],
            result['source'],
            result['tier_resolved'],
            result.get('source_type', 'feature_catalog'),
        ))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/chat/stream', methods=['POST'])
@limiter.limit("30 per hour")
def chat_stream():
    """Server-Sent Events stream of the answer: blocks are pushed incrementally as
    the LLM generates, so the UI fills in progressively instead of all at once."""
    data = request.get_json()
    messages = data.get('messages', []) if data else []
    query = ''
    for m in reversed(messages):
        if m.get('role') == 'user':
            query = str(m.get('content', '')).strip()
            break
    if not query:
        return jsonify({'error': 'No user query found'}), 400

    def _sse(event: str, payload: dict) -> str:
        line = f"data: {_json.dumps(payload, ensure_ascii=False)}\n\n"
        return (f"event: {event}\n" + line) if event != 'message' else line

    def generate():
        source_type, source, tier = 'feature_catalog', '', 0
        acc, last_sent = [], None
        try:
            for ev in rag.stream_generate(query):
                kind = ev.get('type')
                if kind == 'meta':
                    source_type = ev.get('source_type', source_type)
                    source = ev.get('source', source)
                    tier = ev.get('tier', tier)
                elif kind == 'delta':
                    acc.append(ev.get('text', ''))
                    blocks = _partial_to_blocks(''.join(acc), source_type)
                    if blocks:
                        payload = _json.dumps(blocks, ensure_ascii=False)
                        if payload != last_sent:
                            last_sent = payload
                            yield _sse('message', blocks)
                elif kind == 'done':
                    final = _answer_to_blocks(ev.get('answer', ''), source, tier, source_type)
                    yield _sse('done', final)
        except Exception as e:
            yield _sse('error', {'error': str(e)})

    return Response(stream_with_context(generate()), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@app.route('/api/reload-catalog', methods=['POST'])
def reload_catalog():
    token    = request.headers.get('X-Reload-Token', '')
    expected = os.getenv('RELOAD_TOKEN', '')
    if not expected or token != expected:
        return jsonify({'error': 'Unauthorized'}), 401

    global rag, _rag_ready
    try:
        rag = RAGWorkflow()
        _rag_ready = rag.initialize_tier_retrieval()
        rag.build_graph()
        return jsonify({
            'status': 'reloaded',
            'feature_index': rag.tier_retrieval.feature_loader_initialized,
            'proposal_index': rag.tier_retrieval.proposal_loader_initialized,
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/catalog-file/<product>')
def catalog_file(product):
    slug = product.upper()
    mapping = {}
    for fpath in glob.glob(os.path.join(FEATURE_SHEET_DIR, '*.xlsx')):
        fname = os.path.basename(fpath).upper()
        if 'XSWIFT' in fname:
            mapping['XSWIFT'] = fpath
        elif 'CPL' in fname:
            mapping['CPL'] = fpath
    if slug not in mapping:
        return jsonify({'error': 'Not found'}), 404
    return send_file(mapping[slug], as_attachment=False)


@app.route('/api/proposal-file/<path:filename>')
def proposal_file(filename):
    """Serve a proposal document by its basename (searched recursively, traversal-safe)."""
    target = os.path.basename(filename)   # strip any path components
    for root, _dirs, files in os.walk(RAW_PROPOSALS_DIR):
        for f in files:
            if f == target:
                full = os.path.join(root, f)
                # Ensure the resolved path stays inside RAW_PROPOSALS_DIR
                if os.path.commonpath([os.path.abspath(full), RAW_PROPOSALS_DIR]) == RAW_PROPOSALS_DIR:
                    return send_file(full, as_attachment=False)
    return jsonify({'error': 'Not found'}), 404


_online_proc = None  # handle to the running floating-window subprocess


def _kill_orphan_online_windows():
    """Terminate any stray online_mode.py processes left over from prior sessions.

    The tracked handle (_online_proc) is lost whenever the server restarts, so an
    old floating window can keep running (hidden, no taskbar icon) and block new
    launches. This sweeps them so we always launch exactly one fresh window.
    """
    if os.name != 'nt':
        return
    try:
        ps = (
            "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
            "Where-Object { $_.CommandLine -like '*online_mode.py*' } | "
            "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
        )
        subprocess.run(['powershell', '-NoProfile', '-Command', ps],
                       capture_output=True, timeout=10)
    except Exception:
        pass


@app.route('/api/online-mode/start', methods=['POST'])
def online_mode_start():
    """(Re)launch the PyQt floating window (Meet caption reader) as a local subprocess.

    Always relaunches: any existing window (tracked or an orphan hidden behind the
    browser) is killed first, so each click reliably brings up one fresh, visible window.
    """
    global _online_proc
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'online_mode.py')
    if not os.path.exists(script):
        return jsonify({'error': 'online_mode.py not found'}), 404
    # Kill the tracked process and any orphaned windows from earlier sessions.
    if _online_proc is not None and _online_proc.poll() is None:
        try:
            _online_proc.terminate()
        except Exception:
            pass
    _kill_orphan_online_windows()
    try:
        _online_proc = subprocess.Popen([sys.executable, script])
        return jsonify({'status': 'started', 'pid': _online_proc.pid})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/online-mode/stop', methods=['POST'])
def online_mode_stop():
    global _online_proc
    if _online_proc is not None and _online_proc.poll() is None:
        _online_proc.terminate()
        _online_proc = None
        return jsonify({'status': 'stopped'})
    return jsonify({'status': 'not_running'})


@app.route('/api/feedback', methods=['POST'])
def feedback():
    """Record a thumbs up/down on an answer (and an optional remark) to feedback.jsonl."""
    data = request.get_json(silent=True) or {}
    entry = {
        'time':     datetime.now(timezone.utc).isoformat(),
        'rating':   data.get('rating', ''),      # 'up' | 'down'
        'question': data.get('question', ''),
        'answer':   data.get('answer', ''),
        'remark':   data.get('remark', ''),
    }
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'feedback.jsonl')
    try:
        with open(path, 'a', encoding='utf-8') as f:
            f.write(_json.dumps(entry, ensure_ascii=False) + '\n')
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    return jsonify({'status': 'ok'})


# Biases Whisper toward Axestrack/logistics vocabulary so it stops substituting
# common words (e.g. "overspeeding" → "oversteering"). Whisper uses this as a hint
# of the expected terms/style (max ~224 tokens).
WHISPER_PROMPT = (
    "Axestrack fleet and logistics software. Likely terms: overspeeding, over-speeding, "
    "GPS tracking, real-time vehicle tracking, geofencing, ePOD, electronic proof of delivery, "
    "RFID, driver monitoring system, driver fatigue, dashcam, ADAS, DMS, FMS, yard management, "
    "weighbridge, trip management, route optimization, telematics, SIM tracking, consignment, "
    "in-plant logistics, trucks, drivers, XSWIFT, CPL, plant, port."
)


@app.route('/api/transcribe', methods=['POST'])
def transcribe():
    """Speech-to-text for the in-page mic via OpenAI Whisper.
    Receives an audio blob (multipart 'audio') + optional 'lang', returns {text}."""
    import httpx
    key = os.getenv('OPENAI_API_KEY', '')
    if not key:
        return jsonify({'error': 'OPENAI_API_KEY not set on server'}), 500
    f = request.files.get('audio')
    if f is None:
        return jsonify({'error': 'no audio uploaded'}), 400
    model = os.getenv('OPENAI_WHISPER_MODEL', 'whisper-1')
    lang = (request.form.get('lang') or '').strip()  # 'en' | 'hi' | ''
    data = {'model': model, 'prompt': WHISPER_PROMPT}
    if lang:
        data['language'] = lang
    files = {'file': (f.filename or 'audio.webm', f.stream, f.mimetype or 'audio/webm')}
    try:
        r = httpx.post(
            'https://api.openai.com/v1/audio/transcriptions',
            headers={'Authorization': f'Bearer {key}'},
            data=data, files=files, timeout=120,
        )
        r.raise_for_status()
        return jsonify({'text': (r.json().get('text') or '').strip()})
    except httpx.HTTPStatusError as e:
        return jsonify({'error': f'whisper {e.response.status_code}: {e.response.text[:200]}'}), 502
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/health')
@limiter.exempt   # Render polls this every ~5s; never rate-limit it or Render kills the instance
def health():
    import config
    fl = rag.tier_retrieval.feature_loader
    dim = fl.faiss_index.d if (fl is not None and getattr(fl, 'faiss_index', None) is not None) else None
    model = (config.OPENAI_EMBEDDING_MODEL if config.EMBEDDING_PROVIDER == 'openai'
             else config.EMBEDDING_MODEL)
    return jsonify({
        'status': 'ok',
        'rag_ready': _rag_ready,
        'feature_index': rag.tier_retrieval.feature_loader_initialized,
        'proposal_index': rag.tier_retrieval.proposal_loader_initialized,
        'embedding_provider': config.EMBEDDING_PROVIDER,
        'embedding_model': model,            # what queries are embedded with
        'feature_index_dim': dim,            # 1536 = small, 3072 = large (must match model)
    })


if __name__ == '__main__':
    debug = os.getenv('FLASK_ENV') == 'development'
    app.run(debug=debug, host='0.0.0.0', port=5001, threaded=True)
