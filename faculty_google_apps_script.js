/**
 * U WILL CLASSES - FACULTY-WISE SCHEDULE AUTO-SYNC
 * For Google Sheet: https://docs.google.com/spreadsheets/d/1ILnDlPNjN5WaVZZ2T5LnDJx2TFALZtxbeay-bA4CLpo/edit
 * 
 * Creates and updates ONLY the 40 Faculty tabs with PDF-ready styling.
 */

var FACULTY_DATA_URL = "https://uwillschedule.vercel.app/api/export/faculties_data";

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('🗓️ U WILL Timetable')
    .addItem('🔄 Sync All 40 Faculty Tabs Now', 'syncFaculties')
    .addToUi();
}

function syncFaculties() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  ss.toast("Fetching latest faculty schedules from Web App...", "U WILL Sync", 10);
  
  try {
    var response = UrlFetchApp.fetch(FACULTY_DATA_URL, { method: "GET", muteHttpExceptions: true });
    if (response.getResponseCode() !== 200) {
      throw new Error("HTTP " + response.getResponseCode() + ": " + response.getContentText());
    }
    
    var data = JSON.parse(response.getContentText());
    if (!data.faculties || data.faculties.length === 0) {
      throw new Error("No faculty data received from server.");
    }
    
    ss.toast("Writing 40 Faculty tabs with PDF styling...", "U WILL Sync", 15);
    populateSheets(ss, data.faculties);
    
    ss.toast("🎉 Done! All 40 Faculty tabs updated.", "Success", 5);
    SpreadsheetApp.getUi().alert("Sync Successful!", "✅ All " + data.faculties.length + " Faculty tabs have been created and styled with PDF colors.", SpreadsheetApp.getUi().ButtonSet.OK);
  } catch (err) {
    SpreadsheetApp.getUi().alert("Sync Error", "Failed to sync: " + err.message, SpreadsheetApp.getUi().ButtonSet.OK);
  }
}

function doGet(e) {
  return doPost(e);
}

function doPost(e) {
  try {
    var ss = SpreadsheetApp.getActiveSpreadsheet();
    var response = UrlFetchApp.fetch(FACULTY_DATA_URL, { method: "GET", muteHttpExceptions: true });
    if (response.getResponseCode() !== 200) {
      throw new Error("HTTP " + response.getResponseCode() + ": " + response.getContentText());
    }
    var data = JSON.parse(response.getContentText());
    if (data.faculties && data.faculties.length > 0) {
      populateSheets(ss, data.faculties);
    }
    return ContentService.createTextOutput(JSON.stringify({ status: "success", count: data.faculties ? data.faculties.length : 0 })).setMimeType(ContentService.MimeType.JSON);
  } catch (err) {
    return ContentService.createTextOutput(JSON.stringify({ status: "error", message: err.message })).setMimeType(ContentService.MimeType.JSON);
  }
}

function populateSheets(ss, sheetsList) {
  var existingSheets = ss.getSheets();
  var defaultSheet = existingSheets.length === 1 && (existingSheets[0].getName() === "Sheet1") ? existingSheets[0] : null;
  
  for (var i = 0; i < sheetsList.length; i++) {
    var item = sheetsList[i];
    var sheetName = item.name.substring(0, 31);
    
    var sheet = ss.getSheetByName(sheetName);
    if (!sheet) {
      sheet = ss.insertSheet(sheetName);
    } else {
      sheet.clear();
      try { sheet.getRange(1, 1, sheet.getMaxRows(), sheet.getMaxColumns()).breakApart(); } catch(e) {}
    }
    
    var numRows = item.max_r;
    var numCols = item.max_c;
    if (numRows === 0 || numCols === 0) continue;
    
    if (sheet.getMaxRows() < numRows) sheet.insertRowsAfter(sheet.getMaxRows(), numRows - sheet.getMaxRows());
    if (sheet.getMaxColumns() < numCols) sheet.insertColumnsAfter(sheet.getMaxColumns(), numCols - sheet.getMaxColumns());
    
    var range = sheet.getRange(1, 1, numRows, numCols);
    range.setValues(item.values);
    range.setBackgrounds(item.backgrounds);
    range.setFontColors(item.fontColors);
    range.setFontWeights(item.fontWeights);
    range.setFontSizes(item.fontSizes);
    range.setHorizontalAlignments(item.alignments);
    range.setVerticalAlignment("middle");
    range.setWrap(true);
    range.setBorder(true, true, true, true, true, true, '#CBD5E1', SpreadsheetApp.BorderStyle.SOLID);
    
    if (item.merges && item.merges.length > 0) {
      for (var m = 0; m < item.merges.length; m++) {
        try { sheet.getRange(item.merges[m]).merge(); } catch(e) {}
      }
    }
    
    sheet.setColumnWidth(1, 130);
    for (var c = 2; c <= numCols; c++) sheet.setColumnWidth(c, 150);
    
    sheet.setRowHeight(1, 32);
    sheet.setRowHeight(2, 26);
    sheet.setRowHeight(3, 10);
    sheet.setRowHeight(4, 38);
    for (var r = 5; r <= numRows; r++) {
      var val = (item.values[r - 1] && item.values[r - 1][0]) ? item.values[r - 1][0] : "";
      if (val === "LUNCH BREAK" || (item.values[r - 1] && item.values[r - 1][1] === "★ LUNCH BREAK ★")) {
        sheet.setRowHeight(r, 26);
      } else {
        sheet.setRowHeight(r, 52);
      }
    }
    
    try { sheet.setFrozenRows(4); } catch(e) {}
    sheet.setHiddenGridlines(false);
  }
  
  if (defaultSheet && ss.getSheets().length > 1) {
    try { ss.deleteSheet(defaultSheet); } catch(e) {}
  }
}
