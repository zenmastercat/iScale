/* Condition map: segments coloured by condition index, findings as dots. */
const maplibregl = window.maplibregl;

const SEV_COLOR = ["match", ["get", "severity"], "high", "#D94B4B", "medium", "#E99B37", "low", "#329B76", "#6a7fa0"];

export function webglAvailable() {
  try {
    const c = document.createElement("canvas");
    return !!(c.getContext("webgl2") || c.getContext("webgl"));
  } catch {
    return false;
  }
}

export function createMap(el, opts) {
  if (!maplibregl || !webglAvailable()) return createSvgMap(el, opts);
  try {
    return createGlMap(el, opts);
  } catch (e) {
    console.warn("WebGL map failed, using the SVG map", e);
    el.innerHTML = "";
    return createSvgMap(el, opts);
  }
}

function createGlMap(el, { onSelect, onSegment, onPin, onMapClick }) {
  const map = new maplibregl.Map({
    container: el,
    attributionControl: { compact: true },
    style: {
      version: 8,
      sources: {
        osm: {
          type: "raster",
          tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
          tileSize: 256,
          maxzoom: 19,
          attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
        },
      },
      layers: [
        { id: "bg", type: "background", paint: { "background-color": "#eef2f7" } },
        {
          id: "osm", type: "raster", source: "osm",
          paint: { "raster-saturation": -0.9, "raster-brightness-min": 0.08, "raster-contrast": -0.15, "raster-opacity": 0.75 },
        },
      ],
    },
    center: [100.5137, 13.8196],
    zoom: 16,
    maxZoom: 22,
  });
  map.addControl(new maplibregl.NavigationControl({ showCompass: true }), "bottom-right");
  map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-right");

  let ready = false;
  let pending = null;
  const visible = { defects: true, assets: true };
  const empty = { type: "FeatureCollection", features: [] };

  new ResizeObserver(() => map.resize()).observe(el);
  let fitted = false;
  map.on("load", () => {
    map.addSource("segments", { type: "geojson", data: empty });
    map.addSource("findings", { type: "geojson", data: empty });
    map.addSource("pins", { type: "geojson", data: empty });
    map.addSource("me", { type: "geojson", data: empty });
    map.addLayer({ id: "seg-hl", type: "line", source: "segments", filter: ["==", ["get", "hl"], true],
      layout: { "line-cap": "round", "line-join": "round" }, paint: { "line-color": "#102D50", "line-width": 16, "line-opacity": 0.25 } });
    map.addLayer({ id: "seg-case", type: "line", source: "segments",
      layout: { "line-cap": "round", "line-join": "round" }, paint: { "line-color": "#ffffff", "line-width": 9 } });
    map.addLayer({ id: "seg", type: "line", source: "segments",
      layout: { "line-cap": "round", "line-join": "round" }, paint: { "line-color": ["get", "color"], "line-width": 5.5 } });
    map.addLayer({ id: "f-hl", type: "circle", source: "findings", filter: ["==", ["get", "hl"], true],
      paint: { "circle-radius": 11, "circle-color": "rgba(0,0,0,0)", "circle-stroke-color": "#102D50", "circle-stroke-width": 2.2 } });
    map.addLayer({ id: "f", type: "circle", source: "findings",
      paint: {
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 14, ["case", ["==", ["get", "kind"], "asset"], 2.5, 3.5], 19, ["case", ["==", ["get", "kind"], "asset"], 6, 8]],
        "circle-color": SEV_COLOR,
        "circle-stroke-color": "#ffffff",
        "circle-stroke-width": 1.2,
        "circle-opacity": ["case", ["in", ["get", "status"], ["literal", ["verified", "dismissed", "fixed"]]], 0.35, 1],
      } });
    // shared pins: drawn on top, dark outline so they read differently from survey findings
    map.addLayer({ id: "pin", type: "circle", source: "pins",
      paint: {
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 12, 5, 19, 10],
        "circle-color": SEV_COLOR,
        "circle-stroke-color": "#102D50",
        "circle-stroke-width": ["case", ["get", "hl"], 3.5, 2],
        "circle-opacity": ["case", ["==", ["get", "status"], "open"], 1, 0.35],
      } });
    // "you are here": accuracy ring (a real-size circle polygon) and a blue dot, under nothing else
    map.addLayer({ id: "me-acc", type: "fill", source: "me", filter: ["==", ["get", "part"], "acc"],
      paint: { "fill-color": "#347BC3", "fill-opacity": 0.12, "fill-outline-color": "#347BC3" } });
    // the dot sits above pins so it is never hidden; the ring stays underneath
    map.addLayer({ id: "me-dot", type: "circle", source: "me", filter: ["==", ["get", "part"], "dot"],
      paint: { "circle-radius": 7, "circle-color": ["case", ["get", "stale"], "#8a96a3", "#347BC3"],
        "circle-stroke-color": "#ffffff", "circle-stroke-width": 2.5 } });
    map.on("click", "pin", (e) => {
      const f = e.features[0];
      if (f && !pinMode) { e.originalEvent.stopPropagation(); onPin && onPin(f.properties.id); }
    });
    map.on("click", (e) => {
      if (pinMode && onMapClick) onMapClick(e.lngLat.lat, e.lngLat.lng);
    });
    map.on("click", "f", (e) => {
      const f = e.features[0];
      if (f) onSelect(f.properties.id);
    });
    map.on("click", "seg", (e) => {
      const f = e.features[0];
      if (!f) return;
      const p = f.properties;
      new maplibregl.Popup({ closeButton: false })
        .setLngLat(e.lngLat)
        .setHTML(`<b>Segment ${p.id}</b><br>Condition ${p.condition == null || p.condition === "null" ? "not scored" : p.condition + " of 100, " + p.rating}<br>${p.defects} open defects`)
        .addTo(map);
      onSegment && onSegment(p.id);
    });
    for (const id of ["f", "seg", "pin"]) {
      map.on("mouseenter", id, () => (map.getCanvas().style.cursor = "pointer"));
      map.on("mouseleave", id, () => (map.getCanvas().style.cursor = ""));
    }
    ready = true;
    if (pending) api.setData(...pending);
    if (pinsPending) api.setPins(pinsPending);
    if (mePending !== undefined) api.setMe(mePending);
  });

  let lastData = null;
  let hl = new Set();
  let hlSeg = new Set();
  let pinMode = false;
  let pinsPending = null;
  let pins = [];
  let mePending;

  function circlePoly(lon, lat, r) {
    const k = Math.cos((lat * Math.PI) / 180), ring = [];
    for (let i = 0; i <= 48; i++) {
      const a = (i / 48) * 2 * Math.PI;
      ring.push([lon + ((r * Math.cos(a)) / (6378137 * k)) * 180 / Math.PI, lat + ((r * Math.sin(a)) / 6378137) * 180 / Math.PI]);
    }
    return { type: "Polygon", coordinates: [ring] };
  }

  function buildPins() {
    map.getSource("pins").setData({ type: "FeatureCollection", features: pins.map((p) => ({
      type: "Feature", geometry: { type: "Point", coordinates: [p.lon, p.lat] },
      properties: { id: p.id, severity: p.severity, status: p.status, hl: hl.has(p.id) } })) });
  }

  function build() {
    if (!lastData) return;
    const { analysis, catalog } = lastData;
    const segs = {
      type: "FeatureCollection",
      features: analysis.segments.filter((s) => s.coords).map((s) => ({
        type: "Feature",
        geometry: { type: "LineString", coordinates: s.coords },
        properties: { id: s.id, color: s.color, condition: s.condition, rating: s.rating, defects: s.defect_count, hl: hlSeg.has(s.id) },
      })),
    };
    const feats = {
      type: "FeatureCollection",
      features: analysis.findings
        .filter((f) => (catalog[f.type].kind === "asset" ? visible.assets : visible.defects))
        .map((f) => ({
          type: "Feature",
          geometry: { type: "Point", coordinates: [f.lon, f.lat] },
          properties: { id: f.id, kind: catalog[f.type].kind, severity: f.severity || "", status: f.status, hl: hl.has(f.id) },
        })),
    };
    map.getSource("segments").setData(segs);
    map.getSource("findings").setData(feats);
    buildPins();
  }

  const api = {
    map,
    setData(analysis, catalog, fit = true) {
      if (!ready) { pending = [analysis, catalog, fit]; return; }
      lastData = { analysis, catalog };
      build();
      if (fit || !fitted) { api.fit(); fitted = el.clientHeight > 50; }
    },
    clear() {
      lastData = null;
      if (ready) { map.getSource("segments").setData(empty); map.getSource("findings").setData(empty); }
    },
    fit(ids) {
      if (!lastData) return;
      map.resize();
      const pts = [];
      if (ids && ids.length) {
        for (const f of lastData.analysis.findings) if (ids.includes(f.id)) pts.push([f.lon, f.lat]);
      }
      if (!pts.length) for (const s of lastData.analysis.segments) if (s.coords) pts.push(...s.coords);
      if (!pts.length) return;
      const b = new maplibregl.LngLatBounds(pts[0], pts[0]);
      for (const p of pts) b.extend(p);
      map.fitBounds(b, { padding: { top: 70, bottom: 50, left: 50, right: 50 }, maxZoom: 19, duration: 0 });
    },
    highlight(ids = [], segIds = []) {
      hl = new Set(ids);
      hlSeg = new Set(segIds);
      build();
      if (ready) buildPins();
    },
    flyTo(f) {
      map.easeTo({ center: [f.lon, f.lat], zoom: Math.max(map.getZoom(), 18), duration: 350 });
    },
    setPins(list) {
      pins = list;
      if (!ready) { pinsPending = list; return; }
      buildPins();
      if (!lastData && !fitted && list.length) api.fitPoints(list.map((p) => [p.lon, p.lat]));
    },
    fitPoints(pts) {
      if (!pts.length) return;
      map.resize();
      const b = new maplibregl.LngLatBounds(pts[0], pts[0]);
      for (const p of pts) b.extend(p);
      map.fitBounds(b, { padding: 80, maxZoom: 17, duration: 0 });
      fitted = el.clientHeight > 50;
    },
    setPinMode(on) { pinMode = on; map.getCanvas().style.cursor = on ? "crosshair" : ""; },
    /** The person's own position ({lat, lon, acc, stale}) or null to hide it. Drawn only on this device. */
    setMe(fix) {
      if (!ready) { mePending = fix; return; }
      map.getSource("me").setData(!fix ? empty : { type: "FeatureCollection", features: [
        { type: "Feature", geometry: circlePoly(fix.lon, fix.lat, Math.max(1, fix.acc || 0)), properties: { part: "acc" } },
        { type: "Feature", geometry: { type: "Point", coordinates: [fix.lon, fix.lat] }, properties: { part: "dot", stale: !!fix.stale } }] });
    },
    ensureView() {},
    setVisible(kind, on) {
      visible[kind] = on;
      build();
    },
    resize() { map.resize(); },
  };
  return api;
}

/* ---------------------------------------------------------------------------
   Fallback map without WebGL: segments and findings drawn as SVG over plain
   OpenStreetMap raster tiles (images need no WebGL). Same API as the WebGL map. */
const SEV_HEX = { high: "#D94B4B", medium: "#E99B37", low: "#329B76" };
const NS = "http://www.w3.org/2000/svg";

function createSvgMap(el, { onSelect, onSegment, onPin, onMapClick }) {
  el.classList.add("svgmap");
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("width", "100%");
  svg.setAttribute("height", "100%");
  el.appendChild(svg);
  const note = document.createElement("div");
  note.className = "svgmap-note";
  note.textContent = "Map data © OpenStreetMap contributors · basic map (this browser has WebGL turned off)";
  el.appendChild(note);
  let data = null, hl = new Set(), hlSeg = new Set(), pins = [], pinMode = false, me = null;
  const visible = { defects: true, assets: true };
  let view = null; // {cx, cy, s}: lon/lat centre and pixels per metre
  const R = 6378137;

  function proj(lon, lat) {
    const k = Math.cos((view.lat0 * Math.PI) / 180);
    const x = ((lon - view.cx) * Math.PI / 180) * R * k;
    const y = ((lat - view.cy) * Math.PI / 180) * R;
    return [el.clientWidth / 2 + x * view.s, el.clientHeight / 2 - y * view.s];
  }

  function fitPts(pts) {
    if (!pts.length) return;
    let a = Infinity, b = Infinity, c = -Infinity, d = -Infinity;
    for (const [lo, la] of pts) { a = Math.min(a, lo); c = Math.max(c, lo); b = Math.min(b, la); d = Math.max(d, la); }
    const lat0 = (b + d) / 2;
    const k = Math.cos((lat0 * Math.PI) / 180);
    const wm = Math.max(20, ((c - a) * Math.PI / 180) * R * k), hm = Math.max(20, ((d - b) * Math.PI / 180) * R);
    const s = Math.min((el.clientWidth - 120) / wm, (el.clientHeight - 140) / hm);
    view = { cx: (a + c) / 2, cy: lat0, lat0, s: Math.max(0.2, s) };
  }

  function unproj(px, py) {
    const k = Math.cos((view.lat0 * Math.PI) / 180);
    const x = (px - el.clientWidth / 2) / view.s, y = (el.clientHeight / 2 - py) / view.s;
    return [view.cy + (y / R) * 180 / Math.PI, view.cx + (x / (R * k)) * 180 / Math.PI];
  }

  function drawMe(g) {
    if (!me) return null;
    const [x, y] = proj(me.lon, me.lat);
    const ring = document.createElementNS(NS, "circle");
    ring.setAttribute("cx", x); ring.setAttribute("cy", y); ring.setAttribute("r", Math.max(8, (me.acc || 0) * view.s));
    ring.setAttribute("fill", "rgba(52,123,195,0.12)"); ring.setAttribute("stroke", "#347BC3"); ring.setAttribute("stroke-width", 1);
    const dot = document.createElementNS(NS, "circle");
    dot.setAttribute("cx", x); dot.setAttribute("cy", y); dot.setAttribute("r", 7);
    dot.setAttribute("fill", me.stale ? "#8a96a3" : "#347BC3"); dot.setAttribute("stroke", "#ffffff"); dot.setAttribute("stroke-width", 2.5);
    const t = document.createElementNS(NS, "title");
    t.textContent = `You are here (±${Math.round(me.acc || 0)} m)`;
    dot.appendChild(t);
    g.appendChild(ring);
    return dot;
  }

  function drawPins(g) {
    const dot = drawMe(g);
    for (const p of pins) {
      const [x, y] = proj(p.lon, p.lat);
      const c = document.createElementNS(NS, "circle");
      c.setAttribute("cx", x); c.setAttribute("cy", y); c.setAttribute("r", 7.5);
      c.setAttribute("fill", SEV_HEX[p.severity] || "#329B76");
      c.setAttribute("stroke", "#102D50"); c.setAttribute("stroke-width", hl.has(p.id) ? 3.5 : 2);
      if (p.status !== "open") c.setAttribute("opacity", 0.35);
      c.style.cursor = "pointer";
      c.addEventListener("click", (e) => { if (!pinMode) { e.stopPropagation(); onPin && onPin(p.id); } });
      const t = document.createElementNS(NS, "title");
      t.textContent = `Pinned ${p.label}, ${p.severity} severity`;
      c.appendChild(t);
      g.appendChild(c);
    }
    if (dot) g.appendChild(dot);
  }

  /* Street tiles under the drawing. Tiles are Web Mercator; each one is placed by projecting its
     corners, which is exact enough at street scale. Without internet the images just don't load. */
  function drawTiles() {
    const k = Math.cos((view.lat0 * Math.PI) / 180);
    const z = Math.max(0, Math.min(19, Math.round(Math.log2(156543.03392 * k * view.s))));
    const n = 2 ** z;
    const tx = (lon) => ((lon + 180) / 360) * n;
    const ty = (lat) => ((1 - Math.asinh(Math.tan((lat * Math.PI) / 180)) / Math.PI) / 2) * n;
    const lon = (x) => (x / n) * 360 - 180;
    const lat = (y) => (Math.atan(Math.sinh(Math.PI * (1 - (2 * y) / n))) * 180) / Math.PI;
    const [la0, lo0] = unproj(0, 0), [la1, lo1] = unproj(el.clientWidth, el.clientHeight);
    const x0 = Math.floor(tx(lo0)), x1 = Math.floor(tx(lo1)), y0 = Math.floor(ty(la0)), y1 = Math.floor(ty(la1));
    if ((x1 - x0 + 1) * (y1 - y0 + 1) > 120) return; // zoomed far out: skip rather than flood the tile server
    const g = document.createElementNS(NS, "g");
    g.setAttribute("class", "svgmap-tiles");
    for (let x = x0; x <= x1; x++) {
      for (let y = Math.max(0, y0); y <= Math.min(n - 1, y1); y++) {
        const [ax, ay] = proj(lon(x), lat(y)), [bx, by] = proj(lon(x + 1), lat(y + 1));
        const im = document.createElementNS(NS, "image");
        im.setAttribute("href", `https://tile.openstreetmap.org/${z}/${((x % n) + n) % n}/${y}.png`);
        im.setAttribute("x", ax.toFixed(1)); im.setAttribute("y", ay.toFixed(1));
        im.setAttribute("width", (bx - ax + 0.6).toFixed(1)); im.setAttribute("height", (by - ay + 0.6).toFixed(1));
        im.setAttribute("preserveAspectRatio", "none");
        g.appendChild(im);
      }
    }
    svg.appendChild(g);
  }

  function draw() {
    svg.innerHTML = "";
    if (!view) return;
    drawTiles();
    const g = document.createElementNS(NS, "g");
    svg.appendChild(g);
    if (!data) { drawPins(g); return; }
    const { analysis, catalog } = data;
    for (const s of analysis.segments) {
      if (!s.coords) continue;
      const d = s.coords.map((c, i) => `${i ? "L" : "M"}${proj(c[0], c[1]).map((v) => v.toFixed(1)).join(",")}`).join("");
      for (const [w, col, op] of hlSeg.has(s.id) ? [[18, "#102D50", 0.25]] : []) {
        const p = document.createElementNS(NS, "path");
        p.setAttribute("d", d); p.setAttribute("stroke", col); p.setAttribute("stroke-width", w); p.setAttribute("opacity", op);
        p.setAttribute("fill", "none"); p.setAttribute("stroke-linecap", "round"); g.appendChild(p);
      }
      for (const [w, col] of [[10, "#ffffff"], [6, s.color]]) {
        const p = document.createElementNS(NS, "path");
        p.setAttribute("d", d); p.setAttribute("stroke", col); p.setAttribute("stroke-width", w);
        p.setAttribute("fill", "none"); p.setAttribute("stroke-linecap", "round"); p.setAttribute("stroke-linejoin", "round");
        p.style.cursor = "pointer";
        p.addEventListener("click", () => onSegment && onSegment(s.id));
        const t = document.createElementNS(NS, "title");
        t.textContent = `Segment ${s.id}: condition ${s.condition ?? "not scored"}, ${s.rating}`;
        p.appendChild(t);
        g.appendChild(p);
      }
    }
    for (const f of analysis.findings) {
      const kind = catalog[f.type].kind;
      if (kind === "asset" ? !visible.assets : !visible.defects) continue;
      const [x, y] = proj(f.lon, f.lat);
      if (hl.has(f.id)) {
        const r = document.createElementNS(NS, "circle");
        r.setAttribute("cx", x); r.setAttribute("cy", y); r.setAttribute("r", 10);
        r.setAttribute("fill", "none"); r.setAttribute("stroke", "#102D50"); r.setAttribute("stroke-width", 2);
        g.appendChild(r);
      }
      const c = document.createElementNS(NS, "circle");
      c.setAttribute("cx", x); c.setAttribute("cy", y); c.setAttribute("r", kind === "asset" ? 4 : 5.5);
      c.setAttribute("fill", kind === "asset" ? "#6a7fa0" : SEV_HEX[f.severity] || "#329B76");
      c.setAttribute("stroke", "#ffffff"); c.setAttribute("stroke-width", 1.2);
      if (["verified", "dismissed", "fixed"].includes(f.status)) c.setAttribute("opacity", 0.35);
      c.style.cursor = "pointer";
      c.addEventListener("click", () => onSelect(f.id));
      const t = document.createElementNS(NS, "title");
      t.textContent = `${catalog[f.type].label} ${f.id}${f.severity ? ", " + f.severity + " severity" : ""}`;
      c.appendChild(t);
      g.appendChild(c);
    }
    drawPins(g);
  }

  // wheel zoom + drag pan
  el.addEventListener("wheel", (e) => {
    if (!view) return;
    e.preventDefault();
    view.s *= Math.exp(-e.deltaY * 0.0015);
    draw();
  }, { passive: false });
  let drag = null;
  let downAt = null;
  el.addEventListener("pointerdown", (e) => { if (e.target === svg) { drag = [e.clientX, e.clientY]; downAt = [e.clientX, e.clientY]; } });
  el.addEventListener("click", (e) => {
    if (!pinMode || !view || !onMapClick || !downAt || Math.hypot(e.clientX - downAt[0], e.clientY - downAt[1]) > 4) return;
    const r = el.getBoundingClientRect();
    const [lat, lon] = unproj(e.clientX - r.left, e.clientY - r.top);
    onMapClick(lat, lon);
  });
  window.addEventListener("pointerup", () => (drag = null));
  window.addEventListener("pointermove", (e) => {
    if (!drag || !view) return;
    const k = Math.cos((view.lat0 * Math.PI) / 180);
    view.cx -= ((e.clientX - drag[0]) / view.s / (R * k)) * 180 / Math.PI;
    view.cy += ((e.clientY - drag[1]) / view.s / R) * 180 / Math.PI;
    drag = [e.clientX, e.clientY];
    draw();
  });
  new ResizeObserver(() => draw()).observe(el);

  const api = {
    map: null,
    setData(analysis, catalog, fit = true) {
      data = { analysis, catalog };
      if (fit || !view) api.fit();
      draw();
    },
    clear() { data = null; draw(); },
    ensureView(lat, lon) { if (!view) { view = { cx: lon, cy: lat, lat0: lat, s: 2 }; draw(); } },
    fit(ids) {
      if (!data) return;
      let pts = [];
      if (ids && ids.length) pts = data.analysis.findings.filter((f) => ids.includes(f.id)).map((f) => [f.lon, f.lat]);
      if (!pts.length) for (const s of data.analysis.segments) if (s.coords) pts.push(...s.coords);
      fitPts(pts);
      draw();
    },
    highlight(ids = [], segIds = []) { hl = new Set(ids); hlSeg = new Set(segIds); draw(); },
    flyTo(f) {
      if (!view) view = { cx: f.lon, cy: f.lat, lat0: f.lat, s: 25 };
      view.cx = f.lon; view.cy = f.lat; view.s = Math.max(view.s, 25); draw();
    },
    setPins(list) {
      pins = list;
      if (!view && list.length) fitPts(list.map((p) => [p.lon, p.lat]));
      draw();
    },
    fitPoints(pts) { fitPts(pts); draw(); },
    setPinMode(on) { pinMode = on; el.style.cursor = on ? "crosshair" : ""; },
    setMe(fix) { me = fix; if (fix && !view) view = { cx: fix.lon, cy: fix.lat, lat0: fix.lat, s: 2 }; draw(); },
    setVisible(kind, on) { visible[kind] = on; draw(); },
    resize() { draw(); },
  };
  return api;
}
