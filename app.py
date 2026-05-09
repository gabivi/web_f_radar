from FlightRadar24.api import FlightRadar24API
from typing import List, Dict, Tuple
from flask import Flask, jsonify, render_template_string
import random
import time

app = Flask(__name__)

# HTML + JS + Leaflet במחרוזת אחת (שלא צריך קבצים חיצוניים)

TEMPLATE = r"""
<!DOCTYPE html>
<html lang="he">
<head>
  <meta charset="UTF-8">
  <title>Planes Map</title>

  <style>
    html, body { height: 100%; margin: 0; }
    #map { height: 100vh; width: 100vw; }

    /* Tooltip בסיסי (תמיד מוצג) */
    .plane-tooltip {
      background: rgba(255, 255, 255, 0.95);
      border: 1px solid #222;
      border-radius: 7px;
      padding: 8px 10px;
      font-size: 15px;
      line-height: 1.35;
      font-weight: 500;
      color: #111;
      box-shadow: 0 3px 10px rgba(0,0,0,0.25);
      white-space: nowrap;
      pointer-events: none;
    }

    /* Tooltip של מטוס שנבחר (בחזית + מודגש) */
    .plane-tooltip-selected {
      border: 2px solid #000;
      box-shadow: 0 6px 18px rgba(0,0,0,0.35);
      z-index: 99999 !important;
    }

    /* אייקון מטוס (DivIcon) כדי לאפשר rotate */
    .plane-icon { width: 26px; height: 26px; }
    .plane-icon img {
      width: 26px;
      height: 26px;
      display: block;
      transform-origin: 50% 50%;
    }
    .plane-icon-selected img {
      filter: drop-shadow(0 0 6px rgba(0,0,0,0.5));
    }

    /* 4X-ISR off-screen indicator */
    #isr-indicator {
      position: fixed;
      display: none;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      background: rgba(210, 30, 30, 0.92);
      border: 2px solid #fff;
      border-radius: 10px;
      padding: 5px 9px;
      z-index: 10000;
      cursor: pointer;
      box-shadow: 0 2px 12px rgba(0,0,0,0.55);
      color: #fff;
      font-weight: bold;
      font-size: 11px;
      white-space: nowrap;
      user-select: none;
      pointer-events: all;
      line-height: 1.3;
    }
    #isr-indicator #isr-icon {
      font-size: 18px;
      line-height: 1;
      display: inline-block;
    }

    /* 4X-ISR corner info panel */
    #isr-panel {
      display: none;
      position: fixed;
      bottom: 24px;
      right: 16px;
      z-index: 9999;
      background: rgba(255,255,255,0.97);
      border: 2px solid #d01e1e;
      border-radius: 10px;
      box-shadow: 0 3px 14px rgba(0,0,0,0.35);
      padding: 10px 14px 10px 14px;
      min-width: 200px;
      font-size: 12px;
      color: #111;
      pointer-events: none;
    }
    #isr-panel .isr-panel-title {
      font-size: 13px;
      font-weight: bold;
      color: #d01e1e;
      margin-bottom: 7px;
      border-bottom: 1px solid #f0c0c0;
      padding-bottom: 4px;
    }
    #isr-panel .isr-row {
      display: flex;
      justify-content: space-between;
      gap: 10px;
      margin: 2px 0;
    }
    #isr-panel .isr-label { color: #666; }
    #isr-panel .isr-val   { font-weight: 600; }

  </style>

  <!-- Leaflet CSS -->
  <link
    rel="stylesheet"
    href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
    integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY="
    crossorigin=""
  />
  <!-- Leaflet JS -->
  <script
    src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
    integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo="
    crossorigin="">
  </script>
</head>

<body>
<div id="map"></div>
<div id="isr-indicator">
  <div id="isr-icon">&#8594;</div>
  <div>4X-ISR (KNAF-ZION)</div>
</div>
<div id="isr-panel">
  <div class="isr-panel-title">✈ 4X-ISR &nbsp;(KNAF-ZION)</div>
  <div class="isr-row"><span class="isr-label">Lat</span><span class="isr-val" id="isr-lat">–</span></div>
  <div class="isr-row"><span class="isr-label">Lng</span><span class="isr-val" id="isr-lng">–</span></div>
  <div class="isr-row"><span class="isr-label">Altitude</span><span class="isr-val" id="isr-alt">–</span></div>
  <div class="isr-row"><span class="isr-label">Speed</span><span class="isr-val" id="isr-spd">–</span></div>
  <div class="isr-row"><span class="isr-label">Heading</span><span class="isr-val" id="isr-hdg">–</span></div>
  <div class="isr-row"><span class="isr-label">Callsign</span><span class="isr-val" id="isr-cs">–</span></div>
  <div class="isr-row"><span class="isr-label">Aircraft</span><span class="isr-val" id="isr-ac">–</span></div>
  <div class="isr-row"><span class="isr-label">Route</span><span class="isr-val" id="isr-rt">–</span></div>
</div>

<script>
  // כל כמה שניות לרענן (מוזן מהשרת)
  const REFRESH_SECONDS = {{ refresh_seconds|tojson }};

  // יצירת מפה (מרכז – ישראל)
  const map = L.map('map').setView([32.08, 34.78], 7);

  // שכבת רקע (OpenStreetMap)
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap'
  }).addTo(map);

  // שכבה לסמנים
  const markersLayer = L.layerGroup().addTo(map);

  // כדי לשמר בחירה בין רענונים (כי אנחנו עושים clearLayers)
  let selectedKey = null;
  let isrPosition = null; // {lat, lng} of 4X-ISR aircraft
  let isrData = null;     // full point object for 4X-ISR

  // מיפוי קידומת callsign לשם חברה (אפשר להרחיב)
  const AIRLINE_BY_PREFIX = {
    'ELY': 'El Al',
    'LY': 'El Al',
    'WZZ': 'Wizz Air',
    'ISR': 'Israir',
    'AIZ': 'Arkia',
    'ETH': 'Ethiopian Airlines',
    'HFA': 'Haifa Air',
    'ICL': 'Challenge Airlines',
    'BBG': 'Blue Bird',
    'CYF': 'Cyprus Airways',
    'RYR': 'Ryan Air',
    'CYP': 'Cyprus Air',
    'SQY': 'Vision Air',
    'FDB': 'Fly Dubai',
    'RJA': 'Royal Jordanian',
    'ETD': 'Etihad'
  };

  function cleanName(s) {
    return (s || '').replace(/\n/g, '').trim();
  }

  // חילוץ שורות מתוך info (מגיע כ-HTML עם <br>)
  function splitInfo(p) {
    const raw = String(p?.info || '');
    // שומר על תאימות גם אם בעתיד יגיע <br/> או <br />
    return raw.split(/<br\s*\/?>/i).map(x => x.trim());
  }

  // key יציב למטוס: ננסה להשתמש ב-callsign (שורה 3 ב-info)
  function extractKey(p) {
    const parts = splitInfo(p);
    const callsign = (parts[2] || '').trim();
    if (callsign && callsign !== 'N/A') return callsign;
    // fallback
    return `${cleanName(p.name)}|${p.lat}|${p.lng}`;
  }

  function extractCallsign(p) {
    const parts = splitInfo(p);
    const callsign = (parts[2] || '').trim();
    return (callsign && callsign !== 'N/A') ? callsign : null;
  }

  function airlineNameFromCallsign(callsign) {
    //if (!callsign || callsign.length < 3) return null;
    //const prefix = callsign.substring(0, 3).toUpperCase();
    //return AIRLINE_BY_PREFIX[prefix] || null;
    return AIRLINE_BY_PREFIX[callsign] || null;
  }

  // קביעת "כניסה/יציאה" בצורה גסה לפי המסלול ב-name
  // - אם יש "->TLV" / "->ETM" => נכנס (מזרחה)
  // - אם מתחיל ב "TLV->" / "ETM->" => יוצא (מערבה)
  function classifyDirection(p) {
    const name = cleanName(p.name);
    if (name.includes('->TLV') || name.includes('->ETM')) return 'IN';
    if (name.startsWith('TLV->') || name.startsWith('ETM->')) return 'OUT';
    return 'UNK';
  }

  // התאמת זווית לפי האייקון שלך:
  // אם האייקון "מצביע למעלה" כברירת מחדל:
  //   מזרחה=90, מערבה=270
  // אם האייקון "מצביע ימינה" כברירת מחדל:
  //   מזרחה=0, מערבה=180
  //
  // שנה כאן לפי מה שנראה נכון אצלך.
  function rotationDegByDirection(dir) {
    if (dir === 'IN')  return 90;   // מזרחה
    if (dir === 'OUT') return 270;  // מערבה
    return 0;
  }

  function makePlaneDivIcon(rotationDeg, isSelected) {
    const cls = isSelected ? 'plane-icon plane-icon-selected' : 'plane-icon';
    const html = `
      <div class="${cls}">
        <img src="/static/icons/plane.jpg" style="transform: rotate(${rotationDeg}deg);" />
      </div>
    `;
    return L.divIcon({
      html,
      className: '',
      iconSize: [26, 26],
      iconAnchor: [13, 13]
    });
  }

  function makeStaticDivIcon(rotationDeg, isSelected) {
    const cls = isSelected ? 'plane-icon plane-icon-selected' : 'plane-icon';
    const html = `
      <div class="${cls}">
        <img src="/static/icons/point.jpg" style="transform: rotate(${rotationDeg}deg);" />
      </div>
    `;
    return L.divIcon({
      html,
      className: '',
      iconSize: [26, 26],
      iconAnchor: [13, 13]
    });
  }

  function makeIsrDivIcon(rotationDeg) {
    const html = `
      <div style="text-align:center;line-height:0;">
        <div style="width:26px;height:26px;display:inline-block;">
          <img src="/static/icons/plane.jpg"
               style="width:26px;height:26px;transform:rotate(${rotationDeg}deg);
                      filter:drop-shadow(0 0 4px rgba(210,30,30,1));" />
        </div>
        <div style="font-size:8px;font-weight:bold;color:#d01e1e;
                    background:rgba(255,255,255,0.88);border-radius:3px;
                    padding:1px 3px;margin-top:2px;line-height:1.1;
                    white-space:nowrap;">4X-ISR (KNAF-ZION)</div>
      </div>
    `;
    return L.divIcon({html, className: '', iconSize: [40, 38], iconAnchor: [20, 13]});
  }

  function updateIsrIndicator() {
    const el = document.getElementById('isr-indicator');
    const iconEl = document.getElementById('isr-icon');

    if (!isrPosition) {
      // Not in flight – show question mark pinned to bottom-left corner
      iconEl.textContent = '?';
      iconEl.style.transform = '';
      el.style.left = '16px';
      el.style.top = (window.innerHeight - 80) + 'px';
      el.style.transform = '';
      el.title = '4X-ISR not currently located';
      el.style.display = 'flex';
      return;
    }

    const bounds = map.getBounds();
    if (bounds.contains([isrPosition.lat, isrPosition.lng])) {
      el.style.display = 'none';
      return;
    }

    // Off-screen – show arrow at screen edge pointing toward 4X-ISR
    iconEl.textContent = '→';
    const point = map.latLngToContainerPoint([isrPosition.lat, isrPosition.lng]);
    const W = map.getContainer().clientWidth;
    const H = map.getContainer().clientHeight;
    const margin = 44;
    const cx = W / 2, cy = H / 2;
    const dx = point.x - cx, dy = point.y - cy;

    const scaleX = dx !== 0 ? (dx > 0 ? (W - margin - cx) : (cx - margin)) / Math.abs(dx) : Infinity;
    const scaleY = dy !== 0 ? (dy > 0 ? (H - margin - cy) : (cy - margin)) / Math.abs(dy) : Infinity;
    const scale = Math.min(scaleX, scaleY);

    const ex = Math.round(cx + dx * scale);
    const ey = Math.round(cy + dy * scale);

    iconEl.style.transform = `rotate(${Math.atan2(dy, dx) * 180 / Math.PI}deg)`;
    el.style.left = ex + 'px';
    el.style.top = ey + 'px';
    el.style.transform = 'translate(-50%, -50%)';
    el.title = 'Click to go to 4X-ISR';
    el.style.display = 'flex';
  }

  function updateIsrPanel() {
    const panel = document.getElementById('isr-panel');
    if (!isrData) { panel.style.display = 'none'; return; }

    const fmt = (v, unit) => (v != null && v !== 'N/A' && v !== '') ? `${v}${unit || ''}` : '–';
    document.getElementById('isr-lat').textContent = isrData.lat.toFixed(4);
    document.getElementById('isr-lng').textContent = isrData.lng.toFixed(4);
    document.getElementById('isr-alt').textContent = fmt(isrData.altitude, ' ft');
    document.getElementById('isr-spd').textContent = fmt(isrData.speed, ' kt');
    document.getElementById('isr-hdg').textContent = fmt(isrData.heading, '°');
    document.getElementById('isr-cs').textContent  = fmt((isrData.callsign || '').trim());
    document.getElementById('isr-ac').textContent  = fmt(isrData.aircraft);
    document.getElementById('isr-rt').textContent  = fmt(isrData.name);
    panel.style.display = 'block';
  }

  function tooltipClass(isSelected) {
    return isSelected ? 'plane-tooltip plane-tooltip-selected' : 'plane-tooltip';
  }

  // כאן קובעים מה יוצג בפועל ב-tooltip (נקודת שליטה אחת)
  function buildTooltipHtml(p) {
    const name = cleanName(p.name);

    const infoParts = splitInfo(p);
    // לפי הדוגמה שלך:
    // infoParts[0]=aircraft_type, infoParts[1]=speed?, infoParts[2]=callsign, infoParts[3]=altitude
    const aircraftType = p.aircraft || '';
    const speedOrOther = p.speed || '';
    const callsign = p.callsign //extractCallsign(p);
    const altOrOther = p.altitude || '';

    //const airlineName = airlineNameFromCallsign(callsign);
    const airlineName = AIRLINE_BY_PREFIX[p.airline];

    let html = '';
    if (name) html += `<strong>${name}</strong><br>`;

    // שורה: callsign + שם חברה
    //if (callsign) {
    //  if (airlineName) html += `<b>${callsign}</b> – ${airlineName}<br>`;
    //  else html += `<b>${callsign}</b><br>`;
   // }

    // מה להציג מתוך info (אתה שולט כאן)

    if (p.registration) html += `<b>${p.registration}</b><br>`;
    if (airlineName) html += `${airlineName}<br>`;
    if (callsign) html += `${callsign}<br>`;
    if (aircraftType) html += `Aircraft type :${aircraftType}<br>`;
    if (speedOrOther) html += `Speed :${speedOrOther}<br>`;
    if (altOrOther) html += `Altitude :${altOrOther}`;

    return html.trim();
  }

  async function loadData() {
    try {
      const res = await fetch('/data?ts=' + Date.now(), { cache: 'no-store' });
      if (!res.ok) {
        console.error('HTTP error from /data:', res.status, res.statusText);
        return;
      }

      const data = await res.json();

      markersLayer.clearLayers();
      isrPosition = null;
      isrData = null;

      (data.points || []).forEach(p => {
        if (typeof p.lat !== 'number' || typeof p.lng !== 'number') return;

        const key = extractKey(p);
        const isSelected = (selectedKey && key && selectedKey === key);

        const dir = classifyDirection(p);
        //const rot = rotationDegByDirection(dir);

        const ICON_BASE_HEADING = 45; // האייקון שלך מצביע 45° ימינה כברירת מחדל

        let rot = 0;
        if (typeof p.heading === 'number') {
          rot = (p.heading - ICON_BASE_HEADING + 360) % 360;  // <-- התיקון
        } else {
          rot = rotationDegByDirection(classifyDirection(p));
        }

        let icon = '';
        if (p.is_isr_tracked) {
          isrPosition = {lat: p.lat, lng: p.lng};
          isrData = p;
          icon = makeIsrDivIcon(rot);
        } else if (p.name !== 'here' && p.name !== '.') {
          icon = makePlaneDivIcon(rot, isSelected);
        } else {
          icon = makeStaticDivIcon(rot, isSelected);
        }
        const marker = L.marker([p.lat, p.lng], { icon });

        // להעלות את הנבחר בחזית
        if (isSelected) {
          marker.setZIndexOffset(10000);
        }

        const html = buildTooltipHtml(p);
        if (html) {
          marker.bindTooltip(html, {
            permanent: true,
            direction: 'top',
            offset: [0, -10],
            opacity: 0.97,
            className: tooltipClass(isSelected)
          });
        }

        // בלחיצה: לסמן כנבחר (והרינדור הבא ישים אותו בחזית + class מודגש)
        marker.on('click', () => {
          selectedKey = key;
          loadData(); // רינדור מחדש כדי להחיל selected על כולם
        });

        marker.addTo(markersLayer);
      });

      updateIsrIndicator();
      updateIsrPanel();
      console.log('עודכן:', new Date().toLocaleTimeString(), 'נ"ק:', (data.points || []).length);
    } catch (err) {
      console.error('שגיאה בטעינת הנתונים', err);
    }
  }

  map.on('moveend zoomend', updateIsrIndicator);

  document.getElementById('isr-indicator').addEventListener('click', () => {
    if (isrPosition) {
      map.setView([isrPosition.lat, isrPosition.lng], Math.max(map.getZoom(), 7));
    }
  });

  loadData();
  setInterval(loadData, REFRESH_SECONDS * 1000);
</script>

</body>
</html>
"""

OK_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="he">
<head>
  <meta charset="UTF-8">
  <title>מפה עם JSON מתעדכן</title>
  <style>
    html, body { height: 100%; margin: 0; }
    #map { height: 100vh; width: 100vw; }

    /* Tooltip בסיסי */
    .plane-tooltip {
      background: rgba(255, 255, 255, 0.95);
      border: 1px solid #222;
      border-radius: 7px;
      padding: 8px 10px;
      font-size: 15px;          /* הגדלת פונט */
      line-height: 1.35;
      font-weight: 500;
      color: #111;
      box-shadow: 0 3px 10px rgba(0,0,0,0.25);
      white-space: nowrap;
      pointer-events: none;     /* שלא "יתפוס" קליקים */
    }

    /* Tooltip מסומן (בחזית) */
    .plane-tooltip-selected {
      border: 2px solid #000;
      box-shadow: 0 6px 18px rgba(0,0,0,0.35);
      z-index: 99999 !important;
    }

    /* אייקון המטוס (DivIcon) */
    .plane-icon {
      width: 26px;
      height: 26px;
    }
    .plane-icon img {
      width: 26px;
      height: 26px;
      display: block;
      transform-origin: 50% 50%;
    }
    /* הדגשת אייקון שנבחר */
    .plane-icon-selected img {
      filter: drop-shadow(0 0 6px rgba(0,0,0,0.5));
    }
  </style>

  <!-- Leaflet CSS -->
  <link
    rel="stylesheet"
    href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
    integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY="
    crossorigin=""
  />
  <!-- Leaflet JS -->
  <script
    src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
    integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo="
    crossorigin="">
  </script>
</head>

<body>
<div id="map"></div>

<script>
  const REFRESH_SECONDS = {{ refresh_seconds|tojson }};

  const map = L.map('map').setView([32.08, 34.78], 7);

  const AIRLINE_BY_PREFIX = {
  'ELY': 'El Al',
  'WZZ': 'Wizz Air',
  'ISR': 'Israir',
  'AIZ': 'Arkia',
  'ETH': 'Ethiopian Airlines',
  'HFA': 'Haifa Air',
  'ICL': 'Challenge Airlines',
  'BBG': 'Blue Bird',
  'CYF': 'Cyprus Airways',
  'RYR': 'RYAN Air'
  // אפשר להוסיף חופשי
};

  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap'
  }).addTo(map);

  const markersLayer = L.layerGroup().addTo(map);

  // כדי לשמור "בחירה" גם אחרי refresh (כי אתה עושה clearLayers)
  let selectedKey = null;

  function cleanName(s) {
    return (s || '').replace(/\n/g, '').trim();
  }

  // מפתח יציב למטוס: ננסה לחלץ callsign מתוך p.info (השורה השלישית)
  // info שלך נראה בערך: "B738<br>403<br>ELY5401<br>18200"
  function extractKey(p) {
    if (!p || !p.info) return null;
    const parts = String(p.info).split('<br>');
    const callsign = (parts[2] || '').trim(); // ELY5401 / WZZ85PG / ...
    if (callsign && callsign !== 'N/A') return callsign;
    // fallback
    return (cleanName(p.name) + '|' + p.lat + '|' + p.lng);
  }

  // קביעת כיוון "גס" לפי name:
  // - אם המסלול מכיל "->TLV" (או "->ETM" אם זה שדה ישראלי אצלך) => נכנס לישראל (מזרחה)
  // - אם מתחיל ב "TLV->" (או "ETM->") => יוצא מישראל (מערבה)
  //
  // אם תרצה לכלול עוד שדות (כמו IL), פשוט תוסיף כאן.
  function classifyDirection(p) {
    const name = cleanName(p.name);
    // יעד ישראלי (כניסה)
    if (name.includes('->TLV') || name.includes('->ETM')) return 'IN';
    // יציאה מישראל
    if (name.startsWith('TLV->') || name.startsWith('ETM->')) return 'OUT';
    // ברירת מחדל
    return 'UNK';
  }

  function extractCallsignAndAirline(p) {
    if (!p || !p.info) return { callsign: null, airline: null };

    const parts = String(p.info).split('<br>');
    const airline = AIRLINE_BY_PREFIX[p.airline] || null;
    const callsign = p.callsign 

    return { callsign, airline };
    }

  // IMPORTANT:
  // צריך לבחור זווית שמתאימה לציור שלך.
  // אם ה-plane.jpg "מצביע ימינה" כברירת מחדל — שים 0 ל-מזרחה ו-180 למערבה.
  // אם הוא "מצביע למעלה" כברירת מחדל — מזרחה יהיה 90 ומערבה 270.
  //
  // אני מניח שכברירת מחדל הוא "מצביע למעלה" (נפוץ באייקונים).
  function rotationDegByDirection(dir) {
    if (dir === 'IN')  return 90;   // מזרחה (אל ישראל)
    if (dir === 'OUT') return 270;  // מערבה (מישראל)
    return 0;                       // לא ידוע
  }

  function makePlaneDivIcon(rotationDeg, isSelected) {
    const cls = isSelected ? 'plane-icon plane-icon-selected' : 'plane-icon';
    const html = `<div class="${cls}">
      <img src="/static/icons/plane.jpg" style="transform: rotate(${rotationDeg}deg);" />
    </div>`;

    return L.divIcon({
      html,
      className: '',      // חשוב: שלא יהיה class ברירת מחדל שמוסיף padding
      iconSize: [26, 26],
      iconAnchor: [13, 13]
    });
  }

  function tooltipClass(isSelected) {
    return isSelected ? 'plane-tooltip plane-tooltip-selected' : 'plane-tooltip';
  }

  async function loadData() {
    try {
      const res = await fetch('/data?ts=' + Date.now(), { cache: 'no-store' });
      if (!res.ok) {
        console.error('HTTP error from /data:', res.status, res.statusText);
        return;
      }
      const data = await res.json();

      markersLayer.clearLayers();

      (data.points || []).forEach(p => {
        if (typeof p.lat !== 'number' || typeof p.lng !== 'number') return;

        const key = extractKey(p);
        const isSelected = (selectedKey && key && selectedKey === key);

        const dir = classifyDirection(p);
        const rot = rotationDegByDirection(dir);

        const icon = makePlaneDivIcon(rot, isSelected);
        const marker = L.marker([p.lat, p.lng], { icon });

        const name = cleanName(p.name);
        const { callsign, airline } = extractCallsignAndAirline(p);

        let html = '';
        if (name) html += `<strong>${name}</strong><br>`;
        if (p.info) html += `${p.info}`;

        if (callsign) {
         if (airline) {
           html += `<b>${callsign}</b> – ${airline}<br>`;
            } else {
            html += `<b>${callsign}</b><br>`;
            }
        }
        if (p.info) {
          // מדלגים על שורת callsign המקורית כדי שלא תהיה כפילות
          const parts = String(p.info).split('<br>');
          // parts[0]=type, parts[1]=?, parts[2]=callsign, parts[3]=alt
          if (parts.length >= 4) {
            html += `${parts[0]}<br>${parts[3]}`;
          }
        }


        if (html) {
          marker.bindTooltip(html, {
            permanent: true,
            direction: 'top',
            offset: [0, -10],
            opacity: 0.97,
            className: tooltipClass(isSelected)
          });
        }

        // בלחיצה: להעלות לחזית + לשמור בחירה
        marker.on('click', () => {
          selectedKey = key;

          // רינדור מחדש כדי שכל ה-markers יקבלו "מי נבחר" (כי אנחנו עובדים עם clearLayers)
          loadData();
        });

        // אם זה הנבחר, תן לו z-index גבוה יותר כדי שיהיה בחזית
        if (isSelected) {
          marker.setZIndexOffset(10000);
        }

        marker.addTo(markersLayer);
      });

      console.log('עודכן:', new Date().toLocaleTimeString(), 'נ"ק:', (data.points || []).length);
    } catch (err) {
      console.error('שגיאה בטעינת הנתונים', err);
    }
  }

  function buildTooltipHtml(p) {
      // כאן קובעים בדיוק מה יוצג ומה לא

      const name = cleanName(p.name);

      // דוגמה: אם בעתיד תוסיף ב-JSON שדות מסודרים:
      // p.callsign, p.airline_name, p.airline_code, p.alt_ft, p.speed_kt וכו'
      // אתה בוחר מה להציג.

      let html = '';

      if (name) {
        html += `<strong>${name}</strong><br>`;
      }

      // אם יש callsign + שם חברה ב-JSON:
      if (p.callsign) {
        if (p.airline_name) {
          html += `<b>${p.callsign}</b> – ${p.airline_name}<br>`;
        } else {
          html += `<b>${p.callsign}</b><br>`;
        }
      }

      // דוגמה לשדות שתבחר להציג או להסתיר:
      if (p.aircraft_type) html += `${p.aircraft_type}<br>`;
      if (p.alt_ft != null) html += `ALT: ${p.alt_ft} ft<br>`;
      if (p.speed_kt != null) html += `SPD: ${p.speed_kt} kt<br>`;

      // fallback: אם עדיין משתמשים ב-info כ-HTML מוכן
      // if (p.info) html += `${p.info}`;

      return html.trim();
    }



  loadData();
  setInterval(loadData, REFRESH_SECONDS * 1000);
</script>

</body>
</html>
"""

OK_WITH_ICON_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="he">
<head>
    <meta charset="UTF-8">
    <title>מפה עם JSON מתעדכן</title>
    <style>
        html, body {
            height: 100%;
            margin: 0;
        }
        #map {
            height: 100vh;
            width: 100vw;
        }
    </style>

    <!-- Leaflet CSS -->
    <link
      rel="stylesheet"
      href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
      integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY="
      crossorigin=""
    />
    <!-- Leaflet JS -->
    <script
      src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
      integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo="
      crossorigin="">
    </script>
</head>
<body>
<div id="map"></div>

<script>
  // כל כמה שניות לרענן (מוזן מהשרת)
  const REFRESH_SECONDS = {{ refresh_seconds|tojson }};

  // יצירת מפה (מרכז – ישראל)
  const map = L.map('map').setView([32.08, 34.78], 7);

  // שכבת רקע (OpenStreetMap חינמי)
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; OpenStreetMap'
  }).addTo(map);

  // שכבה שמכילה את כל הסמנים – קל למחוק ולהוסיף מחדש
  const markersLayer = L.layerGroup().addTo(map);

  // אייקון מטוס (מוגדר פעם אחת)
  const planeIcon = L.icon({
    iconUrl: '/static/icons/plane.jpg',
    iconSize: [26, 26],
    iconAnchor: [13, 13],        // מרכז האייקון
    tooltipAnchor: [0, -16]      // tooltip מעל האייקון
  });

  function cleanName(s) {
    return (s || '').replace(/\n/g, '').trim();
  }

  async function loadData() {
    try {
      const res = await fetch('/data?ts=' + Date.now(), { cache: 'no-store' });
      if (!res.ok) {
        console.error('HTTP error from /data:', res.status, res.statusText);
        return;
      }

      const data = await res.json();
      // אבחון מהיר:
      // console.log('data sample:', data);

      markersLayer.clearLayers();

      (data.points || []).forEach(p => {
        // הגנה בסיסית מנתונים חסרים
        if (typeof p.lat !== 'number' || typeof p.lng !== 'number') return;

        const marker = L.marker([p.lat, p.lng], { icon: planeIcon });

        const name = cleanName(p.name);

        let html = '';
        if (name) html += `<strong>${name}</strong><br>`;
        if (p.info) html += `${p.info}`;

        if (html) {
          marker.bindTooltip(html, {
            permanent: true,
            direction: 'top',
            offset: [0, -10],
            opacity: 0.97,
            className: 'plane-tooltip'
          });
        }

        marker.addTo(markersLayer);
      });

      console.log('עודכן:', new Date().toLocaleTimeString(), 'נ"ק:', (data.points || []).length);
    } catch (err) {
      console.error('שגיאה בטעינת הנתונים', err);
    }
  }

  loadData();
  setInterval(loadData, REFRESH_SECONDS * 1000);
</script>
"""

ORIG_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="he">
<head>
    <meta charset="UTF-8">
    <title>מפה עם JSON מתעדכן</title>
    <style>
        html, body {
            height: 100%;
            margin: 0;
        }
        #map {
            height: 100vh;
            width: 100vw;
        }
    </style>

    <!-- Leaflet CSS -->
    <link
      rel="stylesheet"
      href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
      integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY="
      crossorigin=""
    />
    <!-- Leaflet JS -->
    <script
      src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
      integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo="
      crossorigin="">
    </script>
</head>
<body>
<div id="map"></div>

<script>
  // כל כמה שניות לרענן (מוזן מהשרת)
  const REFRESH_SECONDS = {{ refresh_seconds|tojson }};

  // יצירת מפה (מרכז – ישראל)
  const map = L.map('map').setView([32.08, 34.78], 7);

  // שכבת רקע (OpenStreetMap חינמי)
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; OpenStreetMap'
  }).addTo(map);

  // שכבה שמכילה את כל הסמנים – קל למחוק ולהוסיף מחדש
  const markersLayer = L.layerGroup().addTo(map);

  async function loadData() {
    try {
      const res = await fetch('/data?ts=' + Date.now());
      const data = await res.json();

      // ניקוי סימנים ישנים
      markersLayer.clearLayers();

      // הוספת סימנים חדשים מהמופע האחרון של ה-JSON
      (data.points || []).forEach(p => {
        const marker = L.marker([p.lat, p.lng]);
        let popupHtml = '';

        if (p.name) {
          popupHtml += `<strong>${p.name}</strong><br>`;
        }
        if (p.info) {
          popupHtml += `${p.info}<br>`;
        }

        // אפשר להוסיף כאן עוד שדות:
        // popupHtml += `מהירות: ${p.speed || ''}<br>`;

        if (popupHtml) {
          marker.bindPopup(popupHtml);
        }

        marker.addTo(markersLayer);
      });

      console.log('עודכן:', new Date().toLocaleTimeString(), 'נ"ק:', data.points?.length || 0);
    } catch (err) {
      console.error('שגיאה בטעינת הנתונים', err);
    }
  }

  // טעינה ראשונית
  loadData();
  // רענון כל REFRESH_SECONDS שניות
  setInterval(loadData, REFRESH_SECONDS * 1000);
</script>
</body>
</html>
"""


class FlightTracker:
    def __init__(self):
        """אתחול ה-API של FlightRadar24"""
        self.fr_api = FlightRadar24API()

    def is_point_in_polygon(self, lat: float, lon: float,
                            top_left: Tuple[float, float],
                            bottom_right: Tuple[float, float]) -> bool:
        """
        בדיקה אם נקודה נמצאת בתוך פוליגון מלבני

        Args:
            lat: קו רוחב של הנקודה
            lon: קו אורך של הנקודה
            top_left: (lat, lon) של הפינה השמאלית העליונה
            bottom_right: (lat, lon) של הפינה הימנית התחתונה

        Returns:
            True אם הנקודה בתוך הפוליגון
        """
        top_lat, left_lon = top_left
        bottom_lat, right_lon = bottom_right

        return (bottom_lat <= lat <= top_lat and
                left_lon <= lon <= right_lon)

    def get_flights_in_area(self,
                            top_left: Tuple[float, float],
                            bottom_right: Tuple[float, float]) -> List[Dict]:
        """
        מציאת כל הטיסות שנמצאות כרגע באזור המוגדר

        Args:
            top_left: (latitude, longitude) של הפינה השמאלית העליונה
            bottom_right: (latitude, longitude) של הפינה הימנית התחתונה

        Returns:
            רשימת טיסות עם המידע שלהן
        """
        # יצירת bounds בפורמט הנכון
        bounds_zone = f"{top_left[0]},{bottom_right[0]},{top_left[1]},{bottom_right[1]}"

        # קבלת הטיסות באזור
        flights = self.fr_api.get_flights(bounds=bounds_zone)

        flights_in_area = []

        for flight in flights:
            try:
                # פרטי הטיסה
                flight_info = {
                    'id': flight.id,
                    'callsign': flight.callsign + ' ' if flight.callsign else 'N/A', 
                    'registration': flight.registration if flight.registration else 'N/A',
                    'aircraft': flight.aircraft_code if flight.aircraft_code else 'N/A',
                    'airline': flight.airline_icao if flight.airline_icao else 'N/A',
                    'origin': flight.origin_airport_iata if flight.origin_airport_iata else 'N/A',
                    'destination': flight.destination_airport_iata if flight.destination_airport_iata else 'N/A',
                    'latitude': flight.latitude,
                    'longitude': flight.longitude,
                    'altitude': flight.altitude,
                    'speed': flight.ground_speed,
                    'heading': flight.heading,
                    'vertical_speed': flight.vertical_speed if hasattr(flight, 'vertical_speed') else 0
                }

                # בדיקה שהטיסה באמת בתוך הפוליגון
                if self.is_point_in_polygon(flight.latitude, flight.longitude,
                                            top_left, bottom_right):
                    flights_in_area.append(flight_info)
            except AttributeError:
                # מדלגים על טיסות עם נתונים חסרים
                continue

        return flights_in_area

    def print_flight_info(self, flights: List[Dict]):
        """הדפסה מסודרת של מידע הטיסות"""
        if not flights:
            print("לא נמצאו טיסות באזור המבוקש")
            return

        print(f"\nנמצאו {len(flights)} טיסות באזור:")
        print("=" * 80)

        for i, flight in enumerate(flights, 1):
            print(f"\nטיסה #{i}:")
            print(f"  שם קריאה: {flight['callsign']}")
            print(f"  רישום: {flight['registration']}")
            print(f"  מטוס: {flight['aircraft']}")
            print(f"  חברת תעופה: {flight['airline']}")
            print(f"  מוצא: {flight['origin']} → יעד: {flight['destination']}")
            print(f"  מיקום: ({flight['latitude']:.4f}, {flight['longitude']:.4f})")
            print(f"  גובה: {flight['altitude']} רגל")
            print(f"  מהירות: {flight['speed']} קשר")
            print(f"  כיוון: {flight['heading']}°")
            print(f"  מהירות אנכית: {flight['vertical_speed']} רגל/דקה")


def main():
    # הגדרת הפוליגון - ניתן לשנות את הקואורדינטות כאן
    # דוגמה: אזור מרכז ישראל (תל אביב-ירושלים)
    TOP_LEFT = (32.5, 34.5)  # (latitude, longitude) - שמאל למעלה
    BOTTOM_RIGHT = (31.5, 35.5)  # (latitude, longitude) - ימין למטה

    print(f"מחפש טיסות באזור:")
    print(f"  פינה שמאלית עליונה: {TOP_LEFT}")
    print(f"  פינה ימנית תחתונה: {BOTTOM_RIGHT}")

    # יצירת אובייקט FlightTracker
    tracker = FlightTracker()

    try:
        # חיפוש טיסות באזור
        flights = tracker.get_flights_in_area(TOP_LEFT, BOTTOM_RIGHT)

        # הצגת התוצאות
        # tracker.print_flight_info(flights)

    except Exception as e:
        print(f"שגיאה: {e}")
        import traceback
        traceback.print_exc()


@app.route("/")
def index():
    # אפשר לשנות כאן את זמן הרענון בשניות
    return render_template_string(TEMPLATE, refresh_seconds=5)


@app.route("/data")
def data():
    """
    כאן מחזירים JSON שמייצג נקודות.
    כרגע – דוגמה רנדומלית. במקום זה אתה יכול לקרוא ל-API שלך.
    הפורמט:
    {
      "points": [
        {"lat": ..., "lng": ..., "name": "...", "info": "..."},
        ...
      ]
    }
    """
    # NW = (34.25, 33.35)
    # SE = (35.90, 29.50)

    # TOP_LEFT = (32.0573501,34.7737489)      # (latitude, longitude) - שמאל למעלה
    # BOTTOM_RIGHT = (32.0655618,34.7788870)
    # TOP_LEFT = (34.25, 33.35)      # (latitude, longitude) - שמאל למעלה
    # BOTTOM_RIGHT = (35.90, 29.50)

    TOP_LEFT = (32.5, 34.5)  # (latitude, longitude) - שמאל למעלה
    BOTTOM_RIGHT = (31.5, 35.5)

    points = []
    # for i in range(5):
    #    points.append({
    #        "lat": base_lat + random.uniform(-0.5, 0.5),
    #        "lng": base_lng + random.uniform(-0.5, 0.5),
    #        "name": f"נקודה {i+1}",
    #        "info": f"זמן: {time.strftime('%H:%M:%S')}"
    #    })

    tracker = FlightTracker()
    # ff = tracker.get_flights_in_area()
    # points = tracker.get_flights_in_area((180,-90),(-180,90))

    # flight = tracker.get_flights_in_area((35.90, 29.50),(34.25, 33.35))
    flight = tracker.get_flights_in_area(TOP_LEFT, BOTTOM_RIGHT)

    # for flight1 in flight:
    #    points.append(flight1)

    for i, flight in enumerate(flight, 1):
        print(f"\nטיסה                           #{i}      :")
        print(f"  שם קריאה: {flight['callsign']}")
        print(f"  רישום: {flight['registration']}")
        print(f"  מטוס: {flight['aircraft']}")
        print(f"  חברת תעופה: {flight['airline']}")
        print(f"  מוצא: {flight['origin']} → יעד: {flight['destination']}")
        print(f"  מיקום: ({flight['latitude']:.4f}, {flight['longitude']:.4f})")
        print(f"  גובה: {flight['altitude']} רגל")
        print(f"  מהירות: {flight['speed']} קשר")
        print(f"  כיוון: {flight['heading']}°")
        print(f"  מהירות אנכית: {flight['vertical_speed']} רגל/דקה")
        points.append({
            "lat": flight['latitude'],
            "lng": flight['longitude'],
            "name": flight['origin'] + "->" + str(flight['destination']),  # + flight['airline'],
            "info": flight['aircraft'] + " " + str(flight['speed']) + " "
                    + flight['callsign'] + " "
                    + str(flight['altitude'])
            ,
            "airline": flight['airline'],
            "callsign": flight['callsign'],
            "speed": flight['speed'],
            "altitude": flight['altitude'],
            "heading": flight['heading'],
            "aircraft": flight['aircraft']
        })

    # points.append({
    #        "lat": (35,90),
    #        "lng": (37,180),
    #        "name" : 111,
    #        "info" : 222
    #    })

    # tracker.print_flight_info(points)

    # points = tracker.get_flights_in_area(TOP_LEFT, BOTTOM_RIGHT)
    # points = tracker.get_flights_in_area((-180,90),(180,-90))

    # Search for 4X-ISR aircraft specifically (anywhere in the world)
    try:
        isr_flights = tracker.fr_api.get_flights(registration='4X-ISR')
        for fl in isr_flights:
            try:
                if fl.latitude and fl.longitude:
                    origin = fl.origin_airport_iata or 'N/A'
                    dest = fl.destination_airport_iata or 'N/A'
                    points.append({
                        "lat": fl.latitude,
                        "lng": fl.longitude,
                        "name": f"{origin}->{dest}",
                        "airline": fl.airline_icao or 'N/A',
                        "callsign": (fl.callsign or 'N/A').strip(),
                        "speed": fl.ground_speed or 0,
                        "altitude": fl.altitude or 0,
                        "heading": fl.heading or 0,
                        "aircraft": fl.aircraft_code or 'N/A',
                        "registration": "4X-ISR",
                        "is_isr_tracked": True
                    })
                    print(f"  4X-ISR found: ({fl.latitude:.4f}, {fl.longitude:.4f})")
            except AttributeError:
                continue
    except Exception as e:
        print(f"  Could not find 4X-ISR: {e}")

    # 32.05642, 34.77310
    points.append({
        "lat": 32.05642,
        "lng": 34.77310,
        "name": 'here',
        "info": 'here'
    })

    points.append({
        #"lat": 32.0791771,  # 32.0720497,
        #"lng": 34.7031657,  # 34.7296015,
        "lat" : 32.10137 ,
        "lng" : 34.71449,
        "name": '.',
        "info": '.'
    })
    points.append({
        "lat": 32.0276367,
        "lng": 34.8127718,
        "name": '.',
        "info": '.'
    })
    points.append({
        "lat": 32.065613,  # 32.0577571,
        "lng": 34.6939822,  # 34.7202464,
        "name": '.',
        "info": '.'
    })
    points.append({
        "lat": 32.0446625,
        "lng": 34.8220416,
        "name": '.',
        "info": '.'
    })

    return jsonify({"points": points})


@app.route("/data1")
def data1():
    """
    כאן מחזירים JSON שמייצג נקודות.
    כרגע – דוגמה רנדומלית. במקום זה אתה יכול לקרוא ל-API שלך.
    הפורמט:
    {
      "points": [
        {"lat": ..., "lng": ..., "name": "...", "info": "..."},
        ...
      ]
    }
    """
    # NW = (34.25, 33.35)
    # SE = (35.90, 29.50)

    # TOP_LEFT = (32.0573501,34.7777337489)      # (latitude, longitude) - שמאל למעלה
    # BOTTOM_RIGHT = (32.0655618,34.7788870)
    # TOP_LEFT = (34.25, 33.35)      # (latitude, longitude) - שמאל למעלה
    # BOTTOM_RIGHT = (35.90, 29.50)

    # TOP_LEFT = (32.5, 34.5)      # (latitude, longitude) - שמאל למעלה
    # BOTTOM_RIGHT = (31.5, 35.5)
    # changed 10/1/26  # TOP_LEFT = (32.0720497, 34.7296015)  # 32.057, 34.773)      # (latitude, longitude) - שמאל למעלה
    TOP_LEFT = (32.10137, 34.71449)
    BOTTOM_RIGHT = (32.0276367, 34.8127718)  # 31.065, 34.778)

    points = []

    tracker = FlightTracker()

    # flight = tracker.get_flights_in_area((35.90, 29.50),(34.25, 33.35))
    flight = tracker.get_flights_in_area(TOP_LEFT, BOTTOM_RIGHT)


  
    for i, flight in enumerate(flight, 1):
        print(f"\nטיסה                           #{i}      :")
        print(f"  שם קריאה: {flight['callsign']}")
        print(f"  רישום: {flight['registration']}")
        print(f"  מטוס: {flight['aircraft']}")
        print(f"  חברת תעופה: {flight['airline']}")
        print(f"  מוצא: {flight['origin']} → יעד: {flight['destination']}")
        print(f"  מיקום: ({flight['latitude']:.4f}, {flight['longitude']:.4f})")
        print(f"  גובה: {flight['altitude']} רגל")
        print(f"  מהירות: {flight['speed']} קשר")
        print(f"  כיוון: {flight['heading']}°")
        print(f"  מהירות אנכית: {flight['vertical_speed']} רגל/דקה")
        points.append({
            "lat": flight['latitude'],
            "lng": flight['longitude'],
            "name": flight['origin'] + "->" + str(flight['destination']),  # + flight['airline'],
            "info": flight['aircraft'] + " " + str(flight['speed']) + " "
                    + flight['callsign'] + " "
                    + str(flight['altitude'])
            ,
            "airline": flight['airline'],
            "callsign": flight['callsign'],
            "speed": flight['speed'],
            "altitude": flight['altitude'],
            "heading": flight['heading'],
            "aircraft": flight['aircraft']
        })

    # points.append({
    #        "lat": (35,90),
    #        "lng": (37,180),
    #        "name" : 111,
    #        "info" : 222
    #    })

    # tracker.print_flight_info(points)

    # points = tracker.get_flights_in_area(TOP_LEFT, BOTTOM_RIGHT)
    # points = tracker.get_flights_in_area((-180,90),(180,-90))

    # 32.05642, 34.77310

    # 32.10137, 34.71449


    points.append({
        "lat": 32.05642,
        "lng": 34.77310,
        "name": 'here',
        "info": 'here'
    })

    return jsonify({"points": points})


@app.route("/isr-debug")
def isr_debug():
    tracker = FlightTracker()
    result = {"registration": "4X-ISR", "found": [], "error": None}
    try:
        isr_flights = tracker.fr_api.get_flights(registration='4X-ISR')
        result["raw_count"] = len(isr_flights)
        for fl in isr_flights:
            try:
                result["found"].append({
                    "registration": fl.registration,
                    "callsign": fl.callsign,
                    "lat": fl.latitude,
                    "lng": fl.longitude,
                    "altitude": fl.altitude,
                    "aircraft": fl.aircraft_code,
                })
            except AttributeError as e:
                result["found"].append({"attr_error": str(e)})
    except Exception as e:
        result["error"] = str(e)
    return jsonify(result)


if __name__ == "__main__":
    main()

if __name__ == "__main__":
    # להאזין לכל הממשק (אם תרצה להיכנס ממחשב אחר ברשת)
    # app.run(host="0.0.0.0", port=5000, debug=True)
    app.run(debug=True)
