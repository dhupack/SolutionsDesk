// solutionsdesk-data.jsx — mock content + simulated reply engine for SolutionsDesk
// Exported to window for use by other babel scripts.

// ---- Suggestion groups (sidebar) ----
const SUGGESTION_GROUPS = [
  {
    label: "Feature Readiness",
    color: "#2563eb",
    items: [
      "Do we have this feature ready with us?",
      "The client is asking for this solution, do we have that?",
    ],
  },
  {
    label: "Backlog & Feedback",
    color: "#0ea5e9",
    items: [
      "Summarize this week's feature requests",
      "What's the status of geofence alerts?",
    ],
  },
];

// ---- Resources (lower-left, doc links — placeholders the user fills later) ----
const RESOURCES = [
  { id: "r1", title: "Feature Catalog", meta: "Google Sheet", icon: "sheet" },
  { id: "r2", title: "Q3 Roadmap", meta: "Doc", icon: "doc" },
  { id: "r3", title: "Client Requests Tracker", meta: "Sheet", icon: "sheet" },
  { id: "r4", title: "Spec Template", meta: "Doc", icon: "doc" },
];

// ---- Seeded recent conversations ----
const SEED_CHATS = [
  {
    id: "c1",
    title: "Does the SDK support offline?",
    updated: "2h ago",
    messages: [
      { role: "user", text: "Does our tracking SDK support offline mode?" },
      {
        role: "assistant",
        badge: { label: "Partially available", tone: "amber" },
        blocks: [
          { type: "p", text: "Offline buffering exists in the mobile SDK but isn't exposed on the web SDK yet." },
          { type: "list", title: "Where it stands", items: [
            "Mobile SDK v3.2 — queues events offline, syncs on reconnect ✓",
            "Web SDK — in design, targeted for next sprint",
            "No admin-facing toggle yet; enabled per-tenant on request",
          ]},
          { type: "p", text: "For a client demo this week, the mobile path is safe to show. Want me to draft the talking points?" },
        ],
      },
    ],
  },
  {
    id: "c2",
    title: "Client wants SAP integration",
    updated: "Yesterday",
    messages: [
      { role: "user", text: "A client is asking for SAP integration — do we have that?" },
      {
        role: "assistant",
        badge: { label: "Available", tone: "green" },
        blocks: [
          { type: "p", text: "Yes — SAP S/4HANA is a supported integration via the Connectors module." },
          { type: "list", title: "What's covered", items: [
            "Orders & dispatch sync (bi-directional)",
            "Master data: vehicles, drivers, plants",
            "OAuth + IDoc transport, sandbox available",
          ]},
          { type: "sources", title: "Referenced", items: [
            { title: "Feature Catalog → Integrations", meta: "row 14" },
            { title: "Connectors spec", meta: "Doc" },
          ]},
        ],
      },
    ],
  },
  {
    id: "c3",
    title: "This week's feature requests",
    updated: "2 days ago",
    messages: [
      { role: "user", text: "Summarize this week's feature requests" },
      {
        role: "assistant",
        blocks: [
          { type: "p", text: "17 requests came in this week across 9 accounts. Top themes:" },
          { type: "list", title: "By volume", items: [
            "Custom report exports — 5 requests",
            "Driver mobile app — dark mode — 4 requests",
            "Webhook for geofence events — 3 requests",
          ]},
          { type: "p", text: "Custom report exports keeps recurring across enterprise accounts — worth flagging for prioritization." },
        ],
      },
    ],
  },
];

// ---- Simulated reply engine ----
function replyFor(text) {
  const q = text.toLowerCase();

  if (/(sap|salesforce|oracle|netsuite|integrat|connector)/.test(q)) {
    return {
      badge: { label: "Available", tone: "green" },
      blocks: [
        { type: "p", text: "Yes — that integration is supported through the Connectors module. Here's the quick read:" },
        { type: "list", title: "What's covered", items: [
          "Bi-directional data sync with field mapping",
          "OAuth authentication, sandbox environment available",
          "Typical onboarding: 1–2 weeks with the client's IT",
        ]},
        { type: "sources", title: "Referenced", items: [
          { title: "Feature Catalog → Integrations", meta: "Sheet" },
        ]},
      ],
    };
  }

  if (/(offline|sync|buffer)/.test(q)) {
    return {
      badge: { label: "Partially available", tone: "amber" },
      blocks: [
        { type: "p", text: "Offline support is partially there — solid on mobile, in progress on web." },
        { type: "list", title: "Where it stands", items: [
          "Mobile SDK — queues offline, syncs on reconnect ✓",
          "Web SDK — in design, next sprint",
        ]},
      ],
    };
  }

  if (/(do we have|ready|support|can we|is there|does (it|the|our))/.test(q)) {
    return {
      badge: { label: "Available", tone: "green" },
      blocks: [
        { type: "p", text: "Short answer: yes, the core of this exists today. Here's the readiness breakdown:" },
        { type: "list", title: "Readiness", items: [
          "Core capability — shipped and in production",
          "Configuration — available per-tenant",
          "Edge cases — a couple of gaps, listed below",
        ]},
        { type: "p", text: "If you can share the exact client requirement, I'll match it against the catalog line by line." },
      ],
    };
  }

  if (/(summar|request|feedback|theme|this week|backlog)/.test(q)) {
    return {
      blocks: [
        { type: "p", text: "Here's a rollup of recent feature requests:" },
        { type: "list", title: "Top themes", items: [
          "Custom report exports — recurring across enterprise",
          "Mobile app polish — dark mode, faster sync",
          "More webhook events — geofence, ETA changes",
        ]},
        { type: "p", text: "Want this as a prioritized list with effort estimates?" },
      ],
    };
  }

  if (/(status|progress|when|eta|timeline|roadmap)/.test(q)) {
    return {
      badge: { label: "In progress", tone: "blue" },
      blocks: [
        { type: "p", text: "That item is mid-flight. Current status:" },
        { type: "list", title: "Status", items: [
          "Design — complete",
          "Build — ~60%, on track for this sprint",
          "QA + rollout — following sprint",
        ]},
      ],
    };
  }

  // Generic fallback
  return {
    blocks: [
      { type: "p", text: "Good question. Based on what we have in the feature catalog and recent discussions, here's my take:" },
      { type: "list", title: "Summary", items: [
        "There's a related capability already in the product",
        "It would need light configuration for this use case",
        "No major blockers flagged",
      ]},
      { type: "p", text: "Share a bit more detail — the client, the exact ask — and I'll get specific." },
    ],
  };
}

Object.assign(window, { SUGGESTION_GROUPS, RESOURCES, SEED_CHATS, replyFor });
