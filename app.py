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
            "name" : "\n" + flight['origin'] + "->" + str(flight['destination']) + "<br>" + "<br>" + flight['airline'],
            "info" : flight['aircraft'] + "<br>" + str(flight['speed']) + "<br>" + flight['callsign'] + "<br>" + str(flight['altitude'])
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




    return jsonify({"points": points})


if __name__ == "__main__":
    main()

if __name__ == "__main__":
    # להאזין לכל הממשק (אם תרצה להיכנס ממחשב אחר ברשת)
    # app.run(host="0.0.0.0", port=5000, debug=True)
    app.run(debug=True)
