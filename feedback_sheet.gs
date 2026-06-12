/**
 * SolutionsDesk — feedback receiver for Google Sheets.
 *
 * SETUP:
 *  1) Open your Google Sheet. Add a header row:  Time | Rating | Question | Answer | Remark
 *  2) Extensions > Apps Script. Delete any sample code, paste THIS file, Save.
 *  3) Deploy > New deployment > type "Web app".
 *       - Execute as:        Me
 *       - Who has access:    Anyone
 *     Click Deploy, authorize, and COPY the "Web app URL" (ends in /exec).
 *  4) In Render > Environment, add:
 *       FEEDBACK_SHEET_URL   = <the Web app URL you copied>
 *       FEEDBACK_SHEET_TOKEN = <any secret string>   (optional; see SHARED_TOKEN below)
 *
 * To change the script later you must Deploy > Manage deployments > Edit > New version.
 */

// Optional shared secret. If you set this, also set the SAME value in Render's
// FEEDBACK_SHEET_TOKEN env var. Leave '' to accept any request (simplest).
var SHARED_TOKEN = '';

function doPost(e) {
  try {
    var data = JSON.parse(e.postData.contents);
    if (SHARED_TOKEN && data.token !== SHARED_TOKEN) {
      return ContentService.createTextOutput('unauthorized');
    }
    var sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
    sheet.appendRow([
      data.time     || new Date().toISOString(),
      data.rating   || '',     // 'up' or 'down'
      data.question || '',
      data.answer   || '',
      data.remark   || ''
    ]);
    return ContentService.createTextOutput('ok');
  } catch (err) {
    return ContentService.createTextOutput('error: ' + err);
  }
}
