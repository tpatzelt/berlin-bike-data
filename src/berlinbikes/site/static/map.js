// Interactive map: pick a station or Ortsteil and a weekday, see the typical
// availability curve as SVG plus a table. Data comes from data/profiles.json,
// written by the nightly site build. No build step, no framework.
(function () {
  "use strict";

  var SVG_NS = "http://www.w3.org/2000/svg";
  var W = 480, H = 200, PAD_L = 32, PAD_R = 8, PAD_T = 8, PAD_B = 24;

  var state = { data: null, curve: null, title: "", markers: {}, selected: null };

  function $(id) { return document.getElementById(id); }

  function cssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  function el(tag, attrs, text) {
    var node = document.createElementNS(SVG_NS, tag);
    Object.keys(attrs).forEach(function (k) { node.setAttribute(k, attrs[k]); });
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function option(value, label) {
    var o = document.createElement("option");
    o.value = value;
    o.textContent = label;
    return o;
  }

  function showStatus(message) {
    var status = $("map-status");
    status.textContent = message;
    status.hidden = false;
  }

  function render() {
    var svg = $("profile-chart");
    var tbody = document.querySelector("#profile-table tbody");
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    while (tbody.firstChild) tbody.removeChild(tbody.firstChild);
    $("profile-title").textContent = state.title;
    if (!state.curve) return;

    var weekday = Number($("pick-weekday").value);
    var values = state.curve[weekday];
    var max = Math.max(1, Math.max.apply(null, values.map(function (v) { return v || 0; })));
    var x = function (h) { return PAD_L + (h / 23) * (W - PAD_L - PAD_R); };
    var y = function (v) { return PAD_T + (1 - v / max) * (H - PAD_T - PAD_B); };

    svg.appendChild(el("line", { x1: PAD_L, y1: y(0), x2: W - PAD_R, y2: y(0), stroke: cssVar("--muted") }));
    [0, 6, 12, 18, 23].forEach(function (h) {
      svg.appendChild(el("text", { x: x(h), y: H - 6, "text-anchor": "middle", "font-size": 11, fill: cssVar("--fg") }, String(h)));
    });
    svg.appendChild(el("text", { x: PAD_L - 4, y: y(max) + 4, "text-anchor": "end", "font-size": 11, fill: cssVar("--fg") }, String(Math.round(max))));
    svg.appendChild(el("text", { x: PAD_L - 4, y: y(0), "text-anchor": "end", "font-size": 11, fill: cssVar("--fg") }, "0"));

    var points = [];
    values.forEach(function (v, h) { if (v !== null) points.push(x(h) + "," + y(v)); });
    svg.appendChild(el("polyline", { points: points.join(" "), fill: "none", stroke: cssVar("--accent"), "stroke-width": 2.5 }));
    var at8 = values[8];
    if (at8 !== null) {
      svg.appendChild(el("circle", { cx: x(8), cy: y(at8), r: 4, fill: cssVar("--accent") }));
    }
    svg.setAttribute("aria-label", state.title + ": " + values.map(function (v, h) {
      return h + ":00 " + (v === null ? "–" : v);
    }).join(", "));

    values.forEach(function (v, h) {
      var tr = document.createElement("tr");
      var th = document.createElement("th");
      th.scope = "row";
      th.textContent = h + ":00";
      var td = document.createElement("td");
      td.textContent = v === null ? "–" : String(v);
      tr.appendChild(th);
      tr.appendChild(td);
      tbody.appendChild(tr);
    });
  }

  function highlight(id) {
    if (state.selected && state.markers[state.selected]) {
      state.markers[state.selected].setStyle({ radius: 5, weight: 1 });
    }
    state.selected = id;
    if (id && state.markers[id]) state.markers[id].setStyle({ radius: 9, weight: 3 }).bringToFront();
  }

  function pickStation(id) {
    var station = state.data.stations.find(function (s) { return s.id === id; });
    if (!station) return;
    $("pick-station").value = id;
    $("pick-ortsteil").value = "";
    state.curve = station.curve;
    state.title = station.name + (station.ortsteil ? " (" + station.ortsteil + ")" : "");
    highlight(id);
    render();
  }

  function pickOrtsteil(name) {
    var ortsteil = state.data.ortsteile.find(function (o) { return o.name === name; });
    if (!ortsteil) return;
    $("pick-station").value = "";
    $("pick-ortsteil").value = name;
    state.curve = ortsteil.curve;
    state.title = "Ortsteil " + name;
    highlight(null);
    render();
  }

  function initMap(stations) {
    if (typeof L === "undefined") return;  // CDN blocked: the selects still work
    var map = L.map("map").setView([52.515, 13.39], 11);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 18,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    }).addTo(map);
    var colour = cssVar("--accent");
    stations.forEach(function (s) {
      var marker = L.circleMarker([s.lat, s.lon], { radius: 5, weight: 1, color: colour, fillOpacity: 0.6 })
        .bindTooltip(s.name)
        .on("click", function () { pickStation(s.id); })
        .addTo(map);
      state.markers[s.id] = marker;
    });
  }

  function init(data) {
    state.data = data;
    if (data.status !== "ok") {
      showStatus((data.message || "not enough data yet / noch nicht genug Daten") +
        " (" + data.full_days + " / 14)");
      return;
    }
    $("profile-days").textContent = "(" + data.full_days + " days / Tage)";
    data.stations.forEach(function (s) { $("pick-station").appendChild(option(s.id, s.name)); });
    data.ortsteile.forEach(function (o) { $("pick-ortsteil").appendChild(option(o.name, o.name)); });
    $("pick-station").addEventListener("change", function (e) { pickStation(e.target.value); });
    $("pick-ortsteil").addEventListener("change", function (e) { pickOrtsteil(e.target.value); });
    $("pick-weekday").addEventListener("change", render);
    initMap(data.stations);
    if (data.stations.length) pickStation(data.stations[0].id);
  }

  document.addEventListener("DOMContentLoaded", function () {
    fetch("data/profiles.json")
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(init)
      .catch(function () { showStatus("Daten konnten nicht geladen werden / Could not load data."); });
  });
})();
