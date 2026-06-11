// solutionsdesk-app.jsx — root: state, chat switching, simulated replies, tweaks
const { useState, useEffect, useRef } = React;

const ACCENTS = {
  "#2563eb": { hover: "#1d4ed8", soft: "#eff6ff", ring: "rgba(37,99,235,.18)" },
  "#4f46e5": { hover: "#4338ca", soft: "#eef2ff", ring: "rgba(79,70,229,.18)" },
  "#0f766e": { hover: "#0e6660", soft: "#effbf9", ring: "rgba(15,118,110,.18)" },
  "#0ea5e9": { hover: "#0284c7", soft: "#f0f9ff", ring: "rgba(14,165,233,.18)" },
};

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "accent": "#2563eb",
  "emptyStyle": "greeting",
  "density": "regular",
  "font": "Plus Jakarta Sans"
}/*EDITMODE-END*/;

let UID = 100;
const uid = () => "c" + (++UID);

function App() {
  const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);
  const [chats, setChats] = useState(() => SEED_CHATS.map((c) => ({ ...c })));
  const [activeId, setActiveId] = useState(null); // null = fresh empty state
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState(null);
  const [collapsed, setCollapsed] = useState(false);
  const [resHeight, setResHeight] = useState(208);
  const [sideWidth, setSideWidth] = useState(288);
  const scrollRef = useRef(null);
  const timers = useRef([]);

  const active = chats.find((c) => c.id === activeId) || null;
  const messages = active ? active.messages : [];

  // apply accent + density + font as CSS vars
  useEffect(() => {
    const a = ACCENTS[t.accent] || ACCENTS["#2563eb"];
    const r = document.documentElement.style;
    r.setProperty("--accent", t.accent);
    r.setProperty("--accent-hover", a.hover);
    r.setProperty("--accent-soft", a.soft);
    r.setProperty("--accent-ring", a.ring);
    r.setProperty("--ui-font", `'${t.font}', system-ui, sans-serif`);
    document.body.dataset.density = t.density;
  }, [t.accent, t.density, t.font]);

  useEffect(() => { document.body.dataset.collapsed = collapsed ? "true" : "false"; }, [collapsed]);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages.length, busy, activeId]);

  useEffect(() => () => timers.current.forEach(clearTimeout), []);

  function newChat() { setActiveId(null); setDraft(""); }
  function clearHistory() { setChats([]); setActiveId(null); }
  function selectChat(id) { setActiveId(id); }
  function deleteChat(id) {
    setChats((prev) => prev.filter((c) => c.id !== id));
    if (activeId === id) setActiveId(null);
  }

  function showToast(msg) {
    setToast(msg);
    const tm = setTimeout(() => setToast(null), 2600);
    timers.current.push(tm);
  }

  function onResource(r) {
    if (!r) { showToast("Connect a doc or sheet — paste a link here later."); return; }
    showToast(`Opening “${r.title}” (${r.meta}) — links go live once you add them.`);
  }

  function send(textArg) {
    const text = (textArg != null ? textArg : draft).trim();
    if (!text || busy) return;

    const isNew = !activeId;
    const id = activeId || uid();
    setChats((prev) => {
      if (!isNew) {
        return prev.map((c) =>
          c.id === id ? { ...c, messages: [...c.messages, { role: "user", text }], updated: "Just now" } : c
        );
      }
      const title = text.length > 38 ? text.slice(0, 38).trim() + "…" : text;
      const nc = { id, title, updated: "Just now", messages: [{ role: "user", text }] };
      return [nc, ...prev];
    });
    if (isNew) setActiveId(id);
    setDraft("");
    setBusy(true);

    const tm = setTimeout(() => {
      const reply = replyFor(text);
      setChats((prev) =>
        prev.map((c) =>
          c.id === id ? { ...c, messages: [...c.messages, { role: "assistant", ...reply }], updated: "Just now" } : c
        )
      );
      setBusy(false);
    }, 900 + Math.random() * 600);
    timers.current.push(tm);
  }

  function onSuggest(s) { send(s); }

  return (
    <div className="sd-app">
      <header className="sd-header">
        <div className="sd-header-left">
          <button className="sd-side-toggle" onClick={() => setCollapsed((c) => !c)} title={collapsed ? "Show sidebar" : "Hide sidebar"}>
            <Icon name="panel" size={18} color="#64748b" />
          </button>
          <div className="sd-brand">
          <div className="sd-logo"><Icon name="logo" size={18} color="#fff" stroke={2.2} /></div>
          <div className="sd-brand-text">
            <div className="sd-brand-name">Solutions<b>Desk</b></div>
            <div className="sd-brand-tag">FEATURE INTELLIGENCE</div>
          </div>
          </div>
        </div>
        <div className="sd-header-right">
        </div>
      </header>

      <div className="sd-body">
        {collapsed ? (
          <MiniRail onNewChat={newChat} onExpand={() => setCollapsed(false)} />
        ) : (
          <Sidebar
            chats={chats}
            activeId={activeId}
            onNewChat={newChat}
            onSelect={selectChat}
            onDelete={deleteChat}
            onClear={clearHistory}
            onSuggest={onSuggest}
            onResource={onResource}
            resHeight={resHeight}
            onResize={setResHeight}
            width={sideWidth}
            onWidth={setSideWidth}
          />
        )}

        <main className="sd-main">
          <div className="sd-scroll" ref={scrollRef}>
            {!active ? (
              <EmptyState style={t.emptyStyle} onSuggest={onSuggest} />
            ) : (
              <div className="sd-thread">
                <div className="sd-thread-head">
                  <span className="sd-thread-title">{active.title}</span>
                </div>
                {messages.map((m, i) => <Message m={m} key={i} />)}
                {busy && <Typing />}
              </div>
            )}
          </div>

          <Composer value={draft} onChange={setDraft} onSend={() => send()} disabled={busy} />
        </main>
      </div>

      {toast && <div className="sd-toast">{toast}</div>}

      <TweaksPanel>
        <TweakSection label="Theme" />
        <TweakColor label="Accent" value={t.accent}
          options={["#2563eb", "#4f46e5", "#0f766e", "#0ea5e9"]}
          onChange={(v) => setTweak("accent", v)} />
        <TweakSelect label="UI font" value={t.font}
          options={["Plus Jakarta Sans", "Public Sans", "IBM Plex Sans"]}
          onChange={(v) => setTweak("font", v)} />
        <TweakSection label="Layout" />
        <TweakRadio label="Empty state" value={t.emptyStyle}
          options={["greeting", "grid"]}
          onChange={(v) => setTweak("emptyStyle", v)} />
        <TweakRadio label="Density" value={t.density}
          options={["compact", "regular", "comfy"]}
          onChange={(v) => setTweak("density", v)} />
      </TweaksPanel>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
