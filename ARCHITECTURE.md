# web_f_radar — Requirements & Architecture

A personal Flask web app that displays a live map of flights around Israel, with special tracking for a specific aircraft (4X-ISR) and a configurable watchlist of callsigns.

## Requirements

### Functional

- **Live flight map.** Show all flights currently inside a configurable bounding box around Israel on an interactive Leaflet/OpenStreetMap. Auto-refresh every few seconds.
- **Per-plane tooltip.** Each plane shows registration, airline name, callsign, aircraft type, speed, altitude, and ETA to destination. Tooltip is always visible (not click-to-open).
- **Heading-accurate icons.** Plane icons rotate to match the flight's actual heading.
- **Click-to-select.** Clicking a plane highlights it (bolder tooltip, raised z-index); selection persists across refreshes.
- **4X-ISR special tracking.** A specific aircraft (registration `4X-ISR`, "KNAF-ZION") is tracked globally — not just inside the bounding box. When visible on the map: highlighted icon with green glow and label. When off-screen: an arrow indicator pinned to the map edge points toward it (click to recenter). When not airborne: a "?" indicator is shown.
- **4X-ISR info panel.** Bottom-right corner panel shows live lat/lng/altitude/speed/heading/callsign/aircraft/route for 4X-ISR whenever it's airborne.
- **Watchlist.** [watchlist.json](watchlist.json) defines callsigns of interest. Matched flights are flagged. Flights matching the watchlist but currently outside the bounding box are still located via a global search by airline prefix.
- **Watch panel.** Bottom-left corner panel shows a mini-map and live data (route, altitude, speed, heading, ETA) for one watched flight at a time. If multiple watched flights are active, the panel rotates through them every 20 seconds.
- **ETA computation.** Estimated arrival is computed client-agnostically on the server using great-circle (haversine) distance from current position to the destination airport, divided by ground speed.
- **Debug endpoints.** `/isr-debug` and `/watchlist-debug` return raw JSON for troubleshooting tracking logic.

### Non-functional

- Single-user personal tool; no auth, no persistence, no rate limiting.
- Runs locally via Flask dev server.
- No build step — frontend is inline HTML/JS in a Python string, Leaflet loaded from CDN.

## Architecture

### Stack

- **Backend:** Python 3 + Flask + [FlightRadar24API](https://pypi.org/project/FlightRadarAPI/) (unofficial client).
- **Frontend:** Single HTML page, vanilla JS, Leaflet 1.9 over OpenStreetMap tiles. No framework, no bundler.
- **Data:** Watchlist in [watchlist.json](watchlist.json). Airport coordinates hard-coded in [app.py](app.py) for ETA.

### Components

#### `FlightTracker` class — [app.py:1166](app.py#L1166)
Thin wrapper around `FlightRadar24API`:
- `get_flights_in_area(top_left, bottom_right)` — queries FR24 with a bounds string, filters by polygon, normalizes each flight into a dict.
- `is_point_in_polygon(...)` — rectangular bounds check (despite the name).

#### Helpers
- `haversine_km(...)` / `calc_eta(...)` — [app.py:40](app.py#L40) great-circle distance and ETA string formatting.
- `load_watchlist()` — [app.py:58](app.py#L58) reads `watchlist.json` from disk on each call.
- `AIRPORT_COORDS` — [app.py:13](app.py#L13) IATA → (lat, lon) table used by ETA.

#### Flask routes
- `GET /` — [app.py:1291](app.py#L1291) renders the inline `TEMPLATE` with `refresh_seconds=5`.
- `GET /data` — [app.py:1297](app.py#L1297) main JSON endpoint. Workflow:
  1. Query flights inside `TOP_LEFT`/`BOTTOM_RIGHT` (currently `(32.5, 34.5)` → `(31.5, 35.5)`).
  2. Globally query `4X-ISR` by registration; tag with `is_isr_tracked`.
  3. For each watchlist entry already in the area, tag with `is_watched` + `watch_label`.
  4. For watchlist entries not found, query FR24 by airline prefix (first 3 chars of callsign) and filter for an exact callsign match.
  5. Append a few static reference points (`'here'`, `'.'`).
  6. Return `{"points": [...]}`.
- `GET /data1` — [app.py:1481](app.py#L1481) older/alternate variant of `/data` with a smaller bounding box. Not wired to the UI.
- `GET /isr-debug` — [app.py:1572](app.py#L1572) raw 4X-ISR lookup result.
- `GET /watchlist-debug` — [app.py:1596](app.py#L1596) per-entry watchlist lookup result.

#### Frontend (`TEMPLATE`, [app.py:71](app.py#L71))
Inline Jinja template. Key JS responsibilities:
- Initialize Leaflet map centered on Israel (zoom 7) with OSM tiles.
- Every `REFRESH_SECONDS` (5s): fetch `/data`, clear markers, re-render.
- For each point: pick an icon (`makePlaneDivIcon`, `makeIsrDivIcon`, or `makeStaticDivIcon`), rotate to `heading - 45°` (icon's base orientation), bind a permanent tooltip via `buildTooltipHtml`.
- Maintain `selectedKey` across refreshes so the user's selection survives the `clearLayers()` rebuild.
- `updateIsrIndicator()` — edge-arrow logic for the off-screen 4X-ISR badge.
- `updateIsrPanel()` — populates bottom-right panel.
- `showWatchedFlight(idx)` — populates bottom-left mini-map panel; `setInterval` rotates through `watchedFlights` every 20s.
- `AIRLINE_BY_PREFIX` — ICAO airline code → display name map.

### Data flow

```
Browser ──GET /──────────▶ Flask (TEMPLATE renders, REFRESH_SECONDS=5)
Browser ──GET /data?ts=──▶ Flask ──▶ FlightRadar24API.get_flights(bounds=...)
                                  ├─▶ get_flights(registration='4X-ISR')
                                  └─▶ get_flights(airline=<prefix>) per unmatched watchlist entry
        ◀──── JSON {points:[…]} ──┘
Browser: clearLayers → render markers + tooltips → update ISR/watch panels
```

### Configuration

- **Bounding box:** `TOP_LEFT`/`BOTTOM_RIGHT` constants inside `/data` ([app.py:1318](app.py#L1318)).
- **Refresh rate:** hard-coded `refresh_seconds=5` in the `/` route ([app.py:1294](app.py#L1294)).
- **Watchlist:** [watchlist.json](watchlist.json) — list of `{callsign, label}` objects under `flights`.
- **Airline names:** `AIRLINE_BY_PREFIX` dict in the JS template.
- **Tracked aircraft:** registration `4X-ISR` hard-coded in `/data` and `/isr-debug`.

### Known rough edges

- `TEMPLATE`, `OK_TEMPLATE`, `OK_WITH_ICON_TEMPLATE`, `ORIG_TEMPLATE` — only the first is used; the other three are dead code (~500 lines).
- Two `if __name__ == "__main__":` blocks at the bottom ([app.py:1629](app.py#L1629), [app.py:1632](app.py#L1632)).
- `FlightTracker()` is instantiated on every request rather than reused.
- Templates are inlined as Python strings; would be easier to maintain under `templates/`.
- `/data1` is an unused older route variant.
