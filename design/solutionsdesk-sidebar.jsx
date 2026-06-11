// solutionsdesk-sidebar.jsx — left rail: collapsible mini-rail, history, resizable resources
function Icon({ name, size = 16, stroke = 1.6, color = "currentColor" }) {
  const common = { width: size, height: size, viewBox: "0 0 24 24", fill: "none",
    stroke: color, strokeWidth: stroke, strokeLinecap: "round", strokeLinejoin: "round" };
  const P = {
    plus: <g><path d="M12 5v14M5 12h14" /></g>,
    trash: <g><path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14" /></g>,
    chat: <g><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" /></g>,
    sheet: <g><rect x="4" y="3" width="16" height="18" rx="2" /><path d="M4 9h16M4 15h16M10 3v18" /></g>,
    doc: <g><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" /><path d="M14 3v5h5M9 13h6M9 17h6" /></g>,
    link: <g><path d="M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1" /><path d="M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1" /></g>,
    spark: <g><path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z" /></g>,
    x: <g><path d="M18 6 6 18M6 6l12 12" /></g>,
    panel: <g><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M9 4v16" /></g>,
    compose: <g><path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z" /></g>,
    search: <g><circle cx="11" cy="11" r="7" /><path d="m20 20-3-3" /></g>,
    logo: <g><path d="m5 13.5 7-6.5 7 6.5" /><path d="m5 18 7-6.5 7 6.5" /></g>,
  };
  return <svg {...common} style={{ flexShrink: 0 }}>{P[name]}</svg>;
}

// Slim icon rail shown when the sidebar is collapsed (Claude / ChatGPT style)
function MiniRail({ onNewChat, onExpand }) {
  return (
    <nav className="sd-rail">
      <button className="sd-railbtn" data-tip="New chat" onClick={onNewChat}>
        <Icon name="compose" size={17} />
      </button>
      <button className="sd-railbtn" data-tip="Search chats" onClick={onExpand}>
        <Icon name="search" size={17} />
      </button>
      <button className="sd-railbtn" data-tip="Recent chats" onClick={onExpand}>
        <Icon name="chat" size={17} />
      </button>
    </nav>
  );
}

function Sidebar({ chats, activeId, onNewChat, onSelect, onDelete, onClear, onResource, resHeight, onResize, width, onWidth }) {
  function startResize(e) {
    e.preventDefault();
    const startY = e.clientY;
    const startH = resHeight;
    function move(ev) {
      const d = startY - ev.clientY;
      onResize(Math.max(96, Math.min(460, startH + d)));
    }
    function up() {
      document.body.style.userSelect = "";
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
    }
    document.body.style.userSelect = "none";
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
  }

  function startWidthResize(e) {
    e.preventDefault();
    const startX = e.clientX;
    const startW = width;
    function move(ev) {
      onWidth(Math.max(232, Math.min(440, startW + (ev.clientX - startX))));
    }
    function up() {
      document.body.style.userSelect = "";
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
    }
    document.body.style.userSelect = "none";
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
  }

  return (
    <aside className="sd-sidebar" style={{ width: width }}>
      <div className="sd-side-top">
        <button className="sd-newchat" onClick={onNewChat}>
          <span className="sd-nc-ic"><Icon name="plus" size={14} /></span>
          New chat
        </button>
        <button className="sd-clear" onClick={onClear}>
          <span className="sd-ic-plain"><Icon name="trash" size={15} /></span>
          Clear history
        </button>
      </div>

      <div className="sd-side-scroll">
        <div className="sd-group">
          <div className="sd-group-label">Recent</div>
          {chats.length === 0 && <div className="sd-empty-hint">No conversations yet</div>}
          {chats.map((c) => (
            <div
              key={c.id}
              className={"sd-chatrow" + (c.id === activeId ? " is-active" : "")}
              onClick={() => onSelect(c.id)}
              title={c.title}
              role="button"
            >
              <Icon name="chat" size={15} color="#94a3b8" />
              <span className="sd-chatrow-title">{c.title}</span>
              <button
                className="sd-chatdel"
                title="Delete chat"
                onClick={(e) => { e.stopPropagation(); onDelete(c.id); }}
              >
                <Icon name="x" size={14} />
              </button>
            </div>
          ))}
        </div>
      </div>

      <div className="sd-resources" style={{ height: resHeight }}>
        <div className="sd-res-resize" onMouseDown={startResize} title="Drag to resize">
          <span className="sd-res-grip" />
        </div>
        <div className="sd-res-head">
          <span className="sd-group-label">Resources</span>
        </div>
        <div className="sd-res-list">
          {RESOURCES.map((r) => (
            <button className="sd-res" key={r.id} onClick={() => onResource(r)}>
              <span className="sd-res-ico"><Icon name={r.icon} size={15} color="#2563eb" /></span>
              <span className="sd-res-text">
                <span className="sd-res-title">{r.title}</span>
                <span className="sd-res-meta">{r.meta}</span>
              </span>
              <Icon name="link" size={13} color="#cbd5e1" />
            </button>
          ))}
        </div>
      </div>
      <div className="sd-width-resize" onMouseDown={startWidthResize} title="Drag to resize" />
    </aside>
  );
}

Object.assign(window, { Sidebar, Icon, MiniRail });
