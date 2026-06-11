// solutionsdesk-chat.jsx — message blocks, empty state, composer
const { useRef, useEffect } = React;

const TONE = {
  green: { bg: "#ecfdf5", fg: "#047857", dot: "#10b981" },
  amber: { bg: "#fffbeb", fg: "#b45309", dot: "#f59e0b" },
  blue:  { bg: "#eff6ff", fg: "#1d4ed8", dot: "#3b82f6" },
};

function Badge({ badge }) {
  const t = TONE[badge.tone] || TONE.blue;
  return (
    <span className="sd-badge" style={{ background: t.bg, color: t.fg }}>
      <span className="sd-badge-dot" style={{ background: t.dot }} />
      {badge.label}
    </span>
  );
}

function Block({ b }) {
  if (b.type === "p") return <p className="sd-p">{b.text}</p>;
  if (b.type === "list")
    return (
      <div className="sd-listwrap">
        {b.title && <div className="sd-list-title">{b.title}</div>}
        <ul className="sd-list">
          {b.items.map((it, i) => (
            <li key={i}><span className="sd-li-mark" />{it}</li>
          ))}
        </ul>
      </div>
    );
  if (b.type === "sources")
    return (
      <div className="sd-sources">
        {b.title && <div className="sd-src-title">{b.title}</div>}
        <div className="sd-src-row">
          {b.items.map((s, i) => (
            <span className="sd-src" key={i}>
              <Icon name="doc" size={12} color="#64748b" />
              {s.title}<em>{s.meta}</em>
            </span>
          ))}
        </div>
      </div>
    );
  return null;
}

function Message({ m }) {
  if (m.role === "user")
    return (
      <div className="sd-msg sd-msg-user">
        <div className="sd-bubble-user">{m.text}</div>
      </div>
    );
  return (
    <div className="sd-msg sd-msg-ai">
      <div className="sd-ai-avatar"><Icon name="logo" size={15} color="#fff" /></div>
      <div className="sd-ai-body">
        {m.badge && <Badge badge={m.badge} />}
        {m.blocks && m.blocks.map((b, i) => <Block b={b} key={i} />)}
      </div>
    </div>
  );
}

function Typing() {
  return (
    <div className="sd-msg sd-msg-ai">
      <div className="sd-ai-avatar"><Icon name="logo" size={15} color="#fff" /></div>
      <div className="sd-ai-body">
        <div className="sd-typing"><span /><span /><span /></div>
      </div>
    </div>
  );
}

function EmptyState({ style, onSuggest }) {
  const chips = [
    "Do we have this feature ready with us?",
    "The client is asking for this solution, do we have that?",
    "Summarize this week's feature requests",
  ];
  if (style === "grid") {
    const cards = [
      { t: "Check feature readiness", d: "Match a client ask against the catalog", q: chips[0] },
      { t: "Answer a client request", d: "See if we already solve it", q: chips[1] },
      { t: "Summarize requests", d: "This week's themes & volume", q: chips[2] },
      { t: "Track a feature's status", d: "Where something stands today", q: "What's the status of geofence alerts?" },
    ];
    return (
      <div className="sd-empty">
        <h2 className="sd-empty-h">Ask anything about your features</h2>
        <p className="sd-empty-sub">Pick a starting point or type your own question below.</p>
        <div className="sd-cardgrid">
          {cards.map((c) => (
            <button className="sd-card" key={c.t} onClick={() => onSuggest(c.q)}>
              <span className="sd-card-t">{c.t}</span>
              <span className="sd-card-d">{c.d}</span>
            </button>
          ))}
        </div>
      </div>
    );
  }
  return (
    <div className="sd-empty">
      <h2 className="sd-empty-h">Ask anything about your features</h2>
      <p className="sd-empty-sub">Discuss ideas, check readiness, and summarize requests — grounded in your team's docs.</p>
      <div className="sd-chips">
        {chips.map((c) => (
          <button className="sd-chip" key={c} onClick={() => onSuggest(c)}>{c}</button>
        ))}
      </div>
    </div>
  );
}

function Composer({ value, onChange, onSend, disabled }) {
  const ref = useRef(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 160) + "px";
  }, [value]);
  function onKey(e) {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); onSend(); }
  }
  return (
    <div className="sd-composer-wrap">
      <div className="sd-composer">
        <textarea
          ref={ref}
          className="sd-input"
          rows={1}
          placeholder="Ask about a feature, a client request, or this week's feedback…"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={onKey}
        />
        <button className="sd-send" onClick={onSend} disabled={disabled || !value.trim()}>
          <span>Ask</span>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12h14M13 6l6 6-6 6" /></svg>
        </button>
      </div>
      <div className="sd-composer-hint">SolutionsDesk can make mistakes — verify against the catalog before promising a client.</div>
    </div>
  );
}

Object.assign(window, { Message, Typing, EmptyState, Composer });
