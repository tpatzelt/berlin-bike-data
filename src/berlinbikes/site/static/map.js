// Interactive map: pick a station or Ortsteil and a weekday, see the typical
// availability curve as SVG plus a table. Data comes from data/profiles.json,
// written by the nightly site build. No build step, no framework.
(function () {
  "use strict";

  var SVG_NS = "http://www.w3.org/2000/svg";

  var state = { data: null, curve: null, title: "", markers: {}, selected: null };

  function $(id) { return document.getElementById(id); }

  var I18N = JSON.parse($("map-i18n").textContent);

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

  function fillSelect(select, options) {
    while (select.options.length > 1) select.remove(1);  // keep the "–" placeholder
    options.forEach(function (o) { select.appendChild(o); });
  }

  function showStatus(message) {
    var status = $("map-status");
    status.textContent = message;
    status.hidden = false;
  }

  function render() {
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
    var values = state.curve[weekday];
    var max = Math.max(1, Math.ceil(Math.max.apply(null, values.map(function (v) { return v || 0; }))));
    var x = function (h) { return PAD_L + (h / 23) * (right - PAD_L); };
    var y = function (v) { return bottom - (v / max) * (bottom - PAD_T); };

    var grid = el("g", { "class": "grid-lines" });
    var xAxis = el("g", { "class": "axis axis-x" });
    var yAxis = el("g", { "class": "axis axis-y" });
    [0, max / 2, max].forEach(function (v) {
      grid.appendChild(el("line", { "class": "grid", x1: PAD_L, x2: right, y1: y(v), y2: y(v) }));
      yAxis.appendChild(el("text", { "class": "tick", x: PAD_L - 6, y: y(v) + 5, "text-anchor": "end" }, String(Math.round(v * 10) / 10)));
    });
    [0, 4, 8, 12, 16, 20, 23].forEach(function (h) {
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
    var atHour = values[I18N.hour];
    if (atHour !== null) {
      var head = el("g", { "class": "headline" });
      var anchorStart = x(I18N.hour) < (PAD_L + right) / 2;
      head.appendChild(el("circle", { cx: x(I18N.hour), cy: y(atHour), r: 5 }));
      head.appendChild(el("text", { x: x(I18N.hour) + (anchorStart ? 10 : -10), y: Math.min(y(atHour) + 22, bottom - 4),
        "text-anchor": anchorStart ? "start" : "end" },
        I18N.headline.replace("{value}", Math.round(atHour)).replace("{hour}", I18N.hour)));
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
    state.title = I18N.ortsteil_title.replace("{name}", function () { return name; });
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
      return;  // the server already rendered the not-enough-data state
    }
    $("profile-days").textContent = I18N.days.replace("{n}", data.full_days);
    // The server pre-fills these selects; rebuild them so no option appears twice.
    fillSelect($("pick-station"), data.stations.map(function (s) { return option(s.id, s.name || s.id); }));
    fillSelect($("pick-ortsteil"), data.ortsteile.map(function (o) { return option(o.name, o.name); }));
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
      .catch(function () { showStatus(I18N.load_error); });
  });
})();
