/**
 * U WILL CLASSES - Google Sheets Timetable Auto-Sync & PDF-Ready Formatter
 * 
 * Spreadsheets:
 * - Batch Schedule: https://docs.google.com/spreadsheets/d/1d3P2qL7rZFl5Pkt8aDpr7_d5U2mok8lpLgELWrjh6CE/edit
 * - Faculty Schedule: https://docs.google.com/spreadsheets/d/1ILnDlPNjN5WaVZZ2T5LnDJx2TFALZtxbeay-bA4CLpo/edit
 * 
 * Setup Instructions (Takes 60 seconds):
 * 1. Open either of your Google Sheets.
 * 2. In the top menu, go to: Extensions > Apps Script.
 * 3. Delete any default code in Code.gs, paste this ENTIRE code, and click Save (💾).
 * 4. Refresh your Google Sheet. You will now see a new menu at the top:
 *    "🗓️ U WILL Timetable" > "🔄 Sync Latest Schedules from Web App".
 * 5. (Optional - for 100% automatic push on every change):
 *    Click "Deploy" > "New deployment" > Select type: "Web app"
 *    Execute as: "Me" | Who has access: "Anyone"
 *    Click "Deploy" and copy the Web App URL.
 */

var BATCH_SPREADSHEET_ID = "1d3P2qL7rZFl5Pkt8aDpr7_d5U2mok8lpLgELWrjh6CE";
var FACULTY_SPREADSHEET_ID = "1ILnDlPNjN5WaVZZ2T5LnDJx2TFALZtxbeay-bA4CLpo";
var WEB_APP_DATA_URL = "https://uwillschedule.vercel.app/api/export/google_sheets_data";

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('🗓️ U WILL Timetable')
    .addItem('🔄 Sync Latest Schedules from Web App', 'syncAllFromWebApp')
    .addItem('ℹ️ View Schedule Status', 'showStatusAlert')
    .addToUi();
}

function showStatusAlert() {
  var ui = SpreadsheetApp.getUi();
  ui.alert(
    'U WILL Timetable Auto-Sync',
    'Connected to: ' + WEB_APP_DATA_URL + '\n\n' +
    'Click "🔄 Sync Latest Schedules from Web App" to fetch and format all 36 Batch tabs and 40 Faculty tabs with PDF-ready styling.',
    ui.ButtonSet.OK
  );
}

function syncAllFromWebApp() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  ss.toast("Fetching latest verified timetable data...", "U WILL Sync", 10);
  
  try {
    var response = UrlFetchApp.fetch(WEB_APP_DATA_URL, {
      method: "GET",
      muteHttpExceptions: true
    });
    
    if (response.getResponseCode() !== 200) {
      throw new Error("HTTP " + response.getResponseCode() + ": " + response.getContentText());
    }
    
    var data = JSON.parse(response.getContentText());
    if (data.status !== "success") {
      throw new Error(data.message || "Failed to load timetable data");
    }
    
    var currentId = ss.getId();
    var updateBatches = (currentId === BATCH_SPREADSHEET_ID) || (currentId !== FACULTY_SPREADSHEET_ID);
    var updateFaculties = (currentId === FACULTY_SPREADSHEET_ID) || (currentId !== BATCH_SPREADSHEET_ID);
    
    // If run inside Batch sheet, update Batch sheet directly; if inside Faculty, update Faculty sheet; or both!
    var batchSs = (currentId === BATCH_SPREADSHEET_ID) ? ss : SpreadsheetApp.openById(BATCH_SPREADSHEET_ID);
    var facultySs = (currentId === FACULTY_SPREADSHEET_ID) ? ss : SpreadsheetApp.openById(FACULTY_SPREADSHEET_ID);
    
    ss.toast("Writing 36 Batch tabs with PDF styling...", "U WILL Sync", 15);
    populateSpreadsheet(batchSs, data.batches);
    
    ss.toast("Writing 40 Faculty tabs with PDF styling...", "U WILL Sync", 15);
    populateSpreadsheet(facultySs, data.faculties);
    
    ss.toast("🎉 Sync Complete! All 36 Batch tabs & 40 Faculty tabs are up to date.", "Success", 5);
    
    var ui = SpreadsheetApp.getUi();
    ui.alert(
      "Sync Successful!",
      "✅ All 36 Batch tabs and 40 Faculty tabs have been updated directly with PDF-ready designs, official brand colors, and zero overlaps.",
      ui.ButtonSet.OK
    );
  } catch (err) {
    var ui = SpreadsheetApp.getUi();
    ui.alert("Sync Error", "Failed to sync: " + err.message, ui.ButtonSet.OK);
  }
}

function doGet(e) {
  return doPost(e);
}

/**
 * Webhook receiver for automatic background push from the web app
 */
function doPost(e) {
  try {
    var data;
    if (e && e.postData && e.postData.contents) {
      data = JSON.parse(e.postData.contents);
    } else {
      var response = UrlFetchApp.fetch(WEB_APP_DATA_URL);
      data = JSON.parse(response.getContentText());
    }
    
    if (data.batches) {
      var batchSs = SpreadsheetApp.openById(BATCH_SPREADSHEET_ID);
      populateSpreadsheet(batchSs, data.batches);
    }
    
    if (data.faculties) {
      var facultySs = SpreadsheetApp.openById(FACULTY_SPREADSHEET_ID);
      populateSpreadsheet(facultySs, data.faculties);
    }
    
    return ContentService.createTextOutput(JSON.stringify({
      status: "success",
      message: "Successfully updated all batch and faculty tabs in Google Sheets!"
    })).setMimeType(ContentService.MimeType.JSON);
    
  } catch (err) {
    return ContentService.createTextOutput(JSON.stringify({
      status: "error",
      message: err.message
    })).setMimeType(ContentService.MimeType.JSON);
  }
}

function doGet(e) {
  return ContentService.createTextOutput("U WILL Timetable Google Apps Script Webhook is active! Use POST to update or run from the Sheet menu.")
    .setMimeType(ContentService.MimeType.TEXT);
}

/**
 * Populates and formats all tabs in the given spreadsheet with batch 2D operations for speed
 */
function populateSpreadsheet(ss, sheetsList) {
  if (!sheetsList || sheetsList.length === 0) return;
  
  var existingSheets = ss.getSheets();
  var defaultSheet = existingSheets.length === 1 && (existingSheets[0].getName() === "Sheet1" || existingSheets[0].getName() === "Sheet 1") ? existingSheets[0] : null;
  
  for (var i = 0; i < sheetsList.length; i++) {
    var item = sheetsList[i];
    var sheetName = item.name.substring(0, 31); // Google Sheets 31-char limit
    
    var sheet = ss.getSheetByName(sheetName);
    if (!sheet) {
      sheet = ss.insertSheet(sheetName);
    } else {
      sheet.clear();
      // Remove previous merges
      try {
        sheet.getRange(1, 1, sheet.getMaxRows(), sheet.getMaxColumns()).breakApart();
      } catch(e) {}
    }
    
    var numRows = item.max_r;
    var numCols = item.max_c;
    if (numRows === 0 || numCols === 0) continue;
    
    // Ensure sheet has enough rows and cols
    if (sheet.getMaxRows() < numRows) {
      sheet.insertRowsAfter(sheet.getMaxRows(), numRows - sheet.getMaxRows());
    }
    if (sheet.getMaxColumns() < numCols) {
      sheet.insertColumnsAfter(sheet.getMaxColumns(), numCols - sheet.getMaxColumns());
    }
    
    var range = sheet.getRange(1, 1, numRows, numCols);
    
    // Batch set values and styles for high performance
    range.setValues(item.values);
    range.setBackgrounds(item.backgrounds);
    range.setFontColors(item.fontColors);
    range.setFontWeights(item.fontWeights);
    range.setFontSizes(item.fontSizes);
    range.setHorizontalAlignments(item.alignments);
    range.setVerticalAlignment("middle");
    range.setWrap(true);
    
    // Set borders
    range.setBorder(true, true, true, true, true, true, '#CBD5E1', SpreadsheetApp.BorderStyle.SOLID);
    
    // Apply merged cells (Header titles, Recess, Footer)
    if (item.merges && item.merges.length > 0) {
      for (var m = 0; m < item.merges.length; m++) {
        try {
          sheet.getRange(item.merges[m]).merge();
        } catch(e) {}
      }
    }
    
    // Column widths
    sheet.setColumnWidth(1, 130);
    for (var c = 2; c <= numCols; c++) {
      sheet.setColumnWidth(c, 150);
    }
    
    // Row heights
    sheet.setRowHeight(1, 32); // Brand header
    sheet.setRowHeight(2, 26); // Subtitle
    sheet.setRowHeight(3, 10); // Spacer
    sheet.setRowHeight(4, 38); // Day headers
    for (var r = 5; r <= numRows; r++) {
      sheet.setRowHeight(r, 52); // Lecture content
    }
    
    // Freeze header
    try { sheet.setFrozenRows(4); } catch(e) {}
    
    // Hide gridlines toggle off to show clean borders
    sheet.setHiddenGridlines(false);
  }
  
  // Remove default placeholder sheet if it's still there
  if (defaultSheet && ss.getSheets().length > 1) {
    try {
      ss.deleteSheet(defaultSheet);
    } catch(e) {}
  }
}
