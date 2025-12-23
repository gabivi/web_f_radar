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

  // שכבת רקע (OpenStreetMap)
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap'
  }).addTo(map);

  // שכבה לסמנים
  const markersLayer = L.layerGroup().addTo(map);

  // כדי לשמר בחירה בין רענונים (כי אנחנו עושים clearLayers)
  let selectedKey = null;

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

        let icon = ''
        if (p.name !== 'here') {
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

      console.log('עודכן:', new Date().toLocaleTimeString(), 'נ"ק:', (data.points || []).length);
    } catch (err) {
      console.error('שגיאה בטעינת הנתונים', err);
    }
  }

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
                    'callsign': flight.callsign if flight.callsign else 'N/A',
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
    TOP_LEFT = (32.5, 34.5)      # (latitude, longitude) - שמאל למעלה
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
        #tracker.print_flight_info(flights)

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
    #NW = (34.25, 33.35)
    #SE = (35.90, 29.50)



    #TOP_LEFT = (32.0573501,34.7737489)      # (latitude, longitude) - שמאל למעלה
    #BOTTOM_RIGHT = (32.0655618,34.7788870)
    #TOP_LEFT = (34.25, 33.35)      # (latitude, longitude) - שמאל למעלה
    #BOTTOM_RIGHT = (35.90, 29.50)

    TOP_LEFT = (32.5, 34.5)      # (latitude, longitude) - שמאל למעלה
    BOTTOM_RIGHT = (31.5, 35.5)




    points = []
    #for i in range(5):
    #    points.append({
    #        "lat": base_lat + random.uniform(-0.5, 0.5),
    #        "lng": base_lng + random.uniform(-0.5, 0.5),
    #        "name": f"נקודה {i+1}",
    #        "info": f"זמן: {time.strftime('%H:%M:%S')}"
    #    })


    tracker = FlightTracker()
    #ff = tracker.get_flights_in_area()
    #points = tracker.get_flights_in_area((180,-90),(-180,90))

    #flight = tracker.get_flights_in_area((35.90, 29.50),(34.25, 33.35))
    flight = tracker.get_flights_in_area(TOP_LEFT, BOTTOM_RIGHT)

    #for flight1 in flight:
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
            "name" : flight['origin'] + "->" + str(flight['destination'])  , # + flight['airline'],
            "info" : flight['aircraft'] + " " + str(flight['speed']) + " "
                     + flight['callsign'] + " "
                     + str(flight['altitude'])
            ,
            "airline" : flight['airline'],
            "callsign" : flight['callsign'],
            "speed" : flight['speed'],
            "altitude" : flight['altitude'],
            "heading" : flight['heading'],
            "aircraft" : flight['aircraft']
        })

    #points.append({
    #        "lat": (35,90),
    #        "lng": (37,180),
    #        "name" : 111,
    #        "info" : 222
    #    })


    #tracker.print_flight_info(points)

    #points = tracker.get_flights_in_area(TOP_LEFT, BOTTOM_RIGHT)
    #points = tracker.get_flights_in_area((-180,90),(180,-90))


    #32.05642, 34.77310
    points.append({
            "lat": 32.05642,
            "lng": 34.77310,
            "name" : 'here',
            "info" : 'here'
        })

    return jsonify({"points": points})


if __name__ == "__main__":
    main()

if __name__ == "__main__":
    # להאזין לכל הממשק (אם תרצה להיכנס ממחשב אחר ברשת)
    # app.run(host="0.0.0.0", port=5000, debug=True)
    app.run(debug=True)
