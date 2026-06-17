# "Update chatbot" button — Google Sheet setup

This adds a **🔄 Update chatbot** button to the feature-catalogue Google Sheet. When
clicked, it tells the deployed server to re-embed the catalogue from this Sheet and
go live (~2 sec) — no git, no redeploy, no laptop. See `docs/workflow.md` for the
full architecture.

## What the click does
1. POSTs to `https://<your-app>.onrender.com/api/rebuild-catalog` with a secret token.
2. The server pulls **both tabs** from this Sheet, re-embeds all rows, swaps the new
   index into memory (live immediately), and commits the new index back to git so it
   survives restarts.
3. A toast shows success (`✅ Chatbot updated — 122 features`) or the error.

## One-time setup
1. In the Sheet: **Extensions → Apps Script**.
2. Delete any boilerplate, paste the script below.
3. Set the two constants at the top:
   - `APP_URL` — your Render service URL (e.g. `https://solutionsdesk.onrender.com`).
   - `REBUILD_TOKEN` — the **same** value you set as the `REBUILD_TOKEN` env var in Render.
4. **Save**. Reload the Sheet. A **Chatbot** menu appears → **🔄 Update chatbot**.
   (First run asks you to authorize the script — allow it.)

> Security note: the token lives in the Apps Script (only editors of this Sheet can
> see it). Anyone without the token who hits the endpoint gets 401. Rotate the token
> by changing it in both Render and this script if needed.

## The script

```javascript
// ── CONFIG — set these two ──────────────────────────────────────────────
const APP_URL       = 'https://solutionsdesk.onrender.com';   // your Render URL, no trailing slash
const REBUILD_TOKEN = 'PASTE_THE_SAME_TOKEN_AS_RENDER';       // == REBUILD_TOKEN env var on Render
// ────────────────────────────────────────────────────────────────────────

// Adds the menu when the Sheet opens.
function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('Chatbot')
    .addItem('🔄 Update chatbot', 'updateChatbot')
    .addToUI();
}

// Called by the menu button: triggers a server-side rebuild from this Sheet.
function updateChatbot() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  ss.toast('Updating chatbot… (~a few seconds)', 'Chatbot', 30);

  try {
    const resp = UrlFetchApp.fetch(APP_URL + '/api/rebuild-catalog', {
      method: 'post',
      headers: { 'X-Rebuild-Token': REBUILD_TOKEN },
      muteHttpExceptions: true,
      // Server work (embed + git push) can take a little while; UrlFetch waits up to ~5 min.
    });

    const code = resp.getResponseCode();
    const body = JSON.parse(resp.getContentText() || '{}');

    if (code === 200 && body.status === 'rebuilt') {
      const gitNote = body.git_writeback ? '' : '  (note: saved to live app, git push skipped)';
      ss.toast('✅ Chatbot updated — ' + body.features + ' features live' + gitNote, 'Chatbot', 8);
    } else if (code === 401) {
      ss.toast('❌ Unauthorized — REBUILD_TOKEN does not match Render.', 'Chatbot', 10);
    } else {
      ss.toast('❌ Update failed: ' + (body.error || ('HTTP ' + code)), 'Chatbot', 10);
    }
  } catch (e) {
    ss.toast('❌ Could not reach the server: ' + e, 'Chatbot', 10);
  }
}
```

## Notes
- **Edits and additions both work** — the rebuild re-embeds the whole catalogue, so
  edited rows update and new rows appear. Click the button *after* you finish editing
  a row (it won't fire on its own, so partial rows are never embedded).
- If the toast says "git push skipped", the chatbot is still updated for the current
  server session — the new index just won't survive a restart until `GITHUB_TOKEN` is
  set in Render.
