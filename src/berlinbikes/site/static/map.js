// Interactive map: pick a station or Ortsteil and a weekday, see the typical
// availability curve as SVG plus a table. Data comes from data/profiles.json,
// written by the nightly site build. No build step, no framework.
(function () {
  "use strict";

  var SVG_NS = "http://www.w3.org/2000/svg";

  var state = { data: null, curve: null, title: "", markers: {}, selected: null };

  function $(id) { return document.getElementById(id); }

  var I18N = JSON.parse($("map-i18n").textContent);

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

  function fillSelect(select, options) {
    while (select.options.length > 1) select.remove(1);  // keep the "–" placeholder
    options.forEach(function (o) { select.appendChild(o); });
  }

  function showStatus(message) {
    var status = $("map-status");
    status.textContent = message;
    status.hidden = false;
  }

  // Round tick values (step 1/2/5 x 10^n) covering [lo, hi]; same rule as charts.nice_ticks.
  function niceTicks(lo, hi) {
    if (hi <= lo) hi = lo + 1;
    var raw = (hi - lo) / I18N.y_tick_target;
    var magnitude = Math.pow(10, Math.floor(Math.log(raw) / Math.LN10));
    var step = [1, 2, 5, 10].map(function (m) { return m * magnitude; }).filter(function (s) { return s >= raw; })[0];
    var first = Math.floor(lo / step + 1e-9), last = Math.ceil(hi / step - 1e-9), ticks = [];
    for (var i = first; i <= last; i++) ticks.push(Math.round(i * step * 1e10) / 1e10);
    return ticks;
  }

  function render() {
    if (state.data && state.data.stations) styleMarkers();
    var svg = $("profile-chart");
    if (!svg) return;
    var tbody = document.querySelector("#profile-table tbody");
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    while (tbody.firstChild) tbody.removeChild(tbody.firstChild);
    $("profile-title").textContent = state.title;
    if (!state.curve) return;

    var box = svg.viewBox.baseVal;
    var H = box.height, PAD_L = I18N.plot.left, PAD_T = I18N.plot.top, bottom = I18N.plot.bottom, right = I18N.plot.right;
    var weekday = Number($("pick-weekday").value);
    var hour = Number($("pick-hour").value);
    var values = state.curve[weekday];
    var present = values.filter(function (v) { return v !== null; });
    var yTicks = niceTicks(0, Math.max.apply(null, [1].concat(present)));
    var yMin = yTicks[0], yMax = yTicks[yTicks.length - 1];
    var x = function (h) { return PAD_L + (h / (values.length - 1)) * (right - PAD_L); };
    var y = function (v) { return bottom - ((v - yMin) / (yMax - yMin)) * (bottom - PAD_T); };

    var grid = el("g", { "class": "grid-lines" });
    var xAxis = el("g", { "class": "axis axis-x" });
    var yAxis = el("g", { "class": "axis axis-y" });
    yTicks.forEach(function (v) {
      grid.appendChild(el("line", { "class": "grid", x1: PAD_L, x2: right, y1: y(v), y2: y(v) }));
      yAxis.appendChild(el("text", { "class": "tick", x: PAD_L - 6, y: y(v) + 5, "text-anchor": "end" }, String(v)));
    });
    I18N.x_ticks.forEach(function (h) {
      grid.appendChild(el("line", { "class": "grid", x1: x(h), x2: x(h), y1: PAD_T, y2: bottom }));
      xAxis.appendChild(el("text", { "class": "tick", x: x(h), y: bottom + 20, "text-anchor": "middle" }, String(h)));
    });
    svg.append(grid, xAxis, yAxis);
    var yTitleX = Number(svg.getAttribute("font-size")), yTitleY = (PAD_T + bottom) / 2;
    svg.appendChild(el("text", { "class": "axis-title axis-title-x", x: (PAD_L + right) / 2, y: H - 6, "text-anchor": "middle" }, I18N.axis_x));
    svg.appendChild(el("text", { "class": "axis-title axis-title-y", x: yTitleX, y: yTitleY, "text-anchor": "middle",
      transform: "rotate(-90 " + yTitleX + " " + yTitleY + ")" }, I18N.axis_y));

    var points = [];
    values.forEach(function (v, h) { if (v !== null) points.push(x(h) + "," + y(v)); });
    svg.appendChild(el("polyline", { points: points.join(" "), fill: "none", stroke: "var(--accent)", "stroke-width": 2.5 }));
    var atHour = values[hour];
    if (atHour !== null) {
      var head = el("g", { "class": "headline" });
      var anchorStart = x(hour) < (PAD_L + right) / 2;
      head.appendChild(el("circle", { cx: x(hour), cy: y(atHour), r: 5 }));
      head.appendChild(el("text", { x: x(hour) + (anchorStart ? 10 : -10), y: Math.min(y(atHour) + 22, bottom - 4),
        "text-anchor": anchorStart ? "start" : "end" },
        I18N.headline.replace("{value}", Math.round(atHour)).replace("{hour}", hour)));
      svg.appendChild(head);
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

  // Index of the display bin for a mean (see charts.MAP_BINS), or -1 without a value.
  function binOf(value) {
    if (value === null || value === undefined) return -1;
    var bin = 0;
    I18N.bin_mins.forEach(function (lo, i) { if (value >= lo) bin = i; });
    return bin;
  }

  function markerRadius(bin) {
    return bin < 0 ? I18N.no_data_radius : I18N.bins[bin];
  }

  function binLabel(bin) {
    return bin < 0 ? I18N.bin_none : I18N.bin_labels[bin];
  }

  // Colour (class), size and accessible name of every marker for the picked weekday and hour.
  function styleMarkers() {
    var weekday = Number($("pick-weekday").value), hour = Number($("pick-hour").value);
    state.data.stations.forEach(function (s) {
      var marker = state.markers[s.id];
      if (!marker) return;
      var bin = binOf(s.curve[weekday][hour]);
      var selected = s.id === state.selected;
      marker.setStyle({ weight: selected ? 3 : 1 });
      marker.setRadius(markerRadius(bin) + (selected ? 3 : 0));
      if (selected) marker.bringToFront();
      var path = marker.getElement();
      if (!path) return;
      path.setAttribute("class", path.getAttribute("class").replace(/\s*\bavail-\S+/g, "") + " avail-" + (bin < 0 ? "none" : bin));
      path.setAttribute("role", "button");
      path.setAttribute("aria-label", I18N.marker_label.replace("{name}", function () { return stationLabel(s); })
        .replace("{bin}", function () { return binLabel(bin); }).replace("{hour}", hour));
    });
  }

  function highlight(id) {
    state.selected = id;  // styleMarkers (called by render) draws it larger and bolder
  }

  function stationById(id) {
    return state.data.stations.find(function (s) { return s.id === id; });
  }

  function stationLabel(station) {
    return station.name || station.id;
  }

  function showOrtsteilButton(station) {
    var button = $("show-ortsteil");
    button.hidden = !(station && station.ortsteil);
    if (!button.hidden) button.dataset.ortsteil = station.ortsteil;
  }

  function pickStation(id) {
    var station = stationById(id);
    if (!station) return false;
    $("pick-station").value = id;
    $("pick-ortsteil").value = "";
    $("pick-search").value = stationLabel(station);
    state.curve = station.curve;
    state.title = station.name + (station.ortsteil ? " (" + station.ortsteil + ")" : "");
    highlight(id);
    showOrtsteilButton(station);
    render();
    return true;
  }

  function pickOrtsteil(name) {
    var ortsteil = state.data.ortsteile.find(function (o) { return o.name === name; });
    if (!ortsteil) return false;
    $("pick-station").value = "";
    $("pick-ortsteil").value = name;
    $("pick-search").value = "";
    state.curve = ortsteil.curve;
    state.title = I18N.ortsteil_title.replace("{name}", function () { return name; });
    highlight(null);
    showOrtsteilButton(null);
    render();
    return true;
  }

  // The selection lives in the URL hash: #station=<id>|ortsteil=<name>&wd=<0-6>&h=<0-23>.
  function writeHash() {
    var parts = [];
    if ($("pick-station").value) parts.push("station=" + encodeURIComponent($("pick-station").value));
    else if ($("pick-ortsteil").value) parts.push("ortsteil=" + encodeURIComponent($("pick-ortsteil").value));
    parts.push("wd=" + $("pick-weekday").value, "h=" + $("pick-hour").value);
    history.replaceState(null, "", "#" + parts.join("&"));
  }

  function parseHash() {
    var params = {};
    location.hash.replace(/^#/, "").split("&").forEach(function (pair) {
      var i = pair.indexOf("=");
      if (i < 1) return;
      try { params[pair.slice(0, i)] = decodeURIComponent(pair.slice(i + 1)); } catch (e) { /* ignore bad escapes */ }
    });
    return params;
  }

  function inRange(text, max) {
    return /^\d+$/.test(text || "") && Number(text) <= max ? text : null;
  }

  // Apply the hash to the controls; anything missing or invalid falls back to the default.
  function applyHash() {
    var params = parseHash();
    var wd = inRange(params.wd, $("pick-weekday").options.length - 1);
    var h = inRange(params.h, $("pick-hour").options.length - 1);
    $("pick-weekday").value = wd === null ? state.defaults.weekday : wd;
    $("pick-hour").value = h === null ? state.defaults.hour : h;
    var ok = (params.station && pickStation(params.station)) || (params.ortsteil && pickOrtsteil(params.ortsteil));
    if (!ok) pickStation(state.defaults.station);
    else render();
  }

  function onSearch(e) {
    var typed = e.target.value.trim().toLowerCase();
    var match = state.data.stations.find(function (s) { return stationLabel(s).toLowerCase() === typed; });
    if (match && pickStation(match.id)) writeHash();
  }

  function initMap(stations) {
    if (typeof L === "undefined") return;  // CDN blocked: the selects still work
    var map = L.map("map").setView([52.515, 13.39], 11);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 18,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    }).addTo(map);
    stations.forEach(function (s) {
      var marker = L.circleMarker([s.lat, s.lon], { radius: 5, weight: 1, fillOpacity: 0.85 })
        .bindTooltip(s.name)
        .on("click", function () { if (pickStation(s.id)) writeHash(); })
        .addTo(map);
      state.markers[s.id] = marker;
    });
  }

  function init(data) {
    state.data = data;
    if (data.status !== "ok") {
      return;  // the server already rendered the not-enough-data state
    }
    $("profile-days").textContent = I18N.days.replace("{n}", data.full_days);
    // The server pre-fills these selects; rebuild them so no option appears twice.
    fillSelect($("pick-station"), data.stations.map(function (s) { return option(s.id, s.name || s.id); }));
    fillSelect($("pick-ortsteil"), data.ortsteile.map(function (o) { return option(o.name, o.name); }));
    var list = $("station-names");
    while (list.firstChild) list.removeChild(list.firstChild);
    data.stations.forEach(function (s) { list.appendChild(option(stationLabel(s), "")); });
    state.defaults = { weekday: $("pick-weekday").value, hour: $("pick-hour").value, station: data.stations.length ? data.stations[0].id : "" };
    $("show-ortsteil").textContent = I18N.ortsteil_button;
    $("pick-station").addEventListener("change", function (e) { if (pickStation(e.target.value)) writeHash(); });
    $("pick-ortsteil").addEventListener("change", function (e) { if (pickOrtsteil(e.target.value)) writeHash(); });
    $("pick-search").addEventListener("input", onSearch);
    $("show-ortsteil").addEventListener("click", function (e) {
      if (pickOrtsteil(e.currentTarget.dataset.ortsteil)) writeHash();
    });
    $("pick-weekday").addEventListener("change", function () { render(); writeHash(); });
    $("pick-hour").addEventListener("change", function () { render(); writeHash(); });
    window.addEventListener("hashchange", applyHash);
    initMap(data.stations);
    applyHash();
  }

  document.addEventListener("DOMContentLoaded", function () {
    fetch("data/profiles.json")
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(init)
      .catch(function () { showStatus(I18N.load_error); });
  });
})();
