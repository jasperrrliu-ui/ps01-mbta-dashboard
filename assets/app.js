const colors = { Red: "#d84a45", Blue: "#1778b5", Orange: "#e17d28", Green: "#3c8d54", Mattapan: "#694c99" };
const hourLabels = { 7: "7-8 AM", 8: "8-9 AM", 16: "4-5 PM", 17: "5-6 PM", all: "all 90 study days" };
let routeChart;

function parseCsv(text) {
  const [header, ...rows] = text.trim().split(/\r?\n/);
  const keys = header.split(",");
  return rows.map((row) => Object.fromEntries(row.split(",").map((value, index) => [keys[index], value])));
}
async function loadCsv(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`Could not load ${path}`);
  return parseCsv(await response.text());
}
async function loadJson(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`Could not load ${path}`);
  return response.json();
}
function percent(value) { return `${(Number(value) * 100).toFixed(1)}%`; }
function transferKey(station, firstLine, secondLine) { return `${station}|${[firstLine, secondLine].sort().join("|")}`; }

async function main() {
  const [transfers, transferHours, stations, stationHours, boardingWait, inVehicle, transferComponents, directedEdges, graph] = await Promise.all([
    loadCsv("data/processed/transfer_exposure.csv"), loadCsv("data/processed/transfer_hour_exposure.csv"), loadCsv("data/processed/station_delay_summary.csv"), loadCsv("data/processed/station_hour_performance.csv"), loadCsv("data/processed/boarding_wait_components.csv"), loadCsv("data/processed/in_vehicle_components.csv"), loadCsv("data/processed/transfer_connection_components.csv"), loadCsv("data/processed/directed_edges.csv"), loadJson("data/processed/network_graph.json")
  ]);
  const originSelect = document.getElementById("planner-origin");
  const destinationSelect = document.getElementById("planner-destination");
  const timeSelect = document.getElementById("time-select");
  const stationById = new Map(graph.stations.map((station) => [station.id, station]));
  const catalog = [...graph.stations].sort((a, b) => a.name.localeCompare(b.name));
  const options = catalog.map((station) => `<option value="${station.id}">${station.name}</option>`).join("");
  originSelect.innerHTML = options;
  destinationSelect.innerHTML = options;
  originSelect.value = catalog.find((station) => station.name === "Boston College")?.id || catalog[0].id;
  destinationSelect.value = catalog.find((station) => station.name === "Community College")?.id || catalog[1].id;
  let activeTransfers = [];
  let activePlan = { transferKeys: new Set(), transferSteps: [], rideLines: [], routeStops: [], routeLegs: [], originName: "", destinationName: "" };

  function transferWindow() {
    const selectedHour = timeSelect.value;
    return (selectedHour === "all" ? transfers : transferHours.filter((row) => Number(row.service_hour) === Number(selectedHour)))
      .sort((a, b) => Number(b.combined_late_exposure) - Number(a.combined_late_exposure));
  }

  function stationMetric(stationId, line) {
    const source = timeSelect.value === "all" ? stations : stationHours.filter((row) => Number(row.service_hour) === Number(timeSelect.value));
    const row = source.find((item) => item.parent_station === stationId && item.line === line);
    return {
      probability: Number(row?.share_late_over_5_minutes || 0),
      averageWhenLateMinutes: Number(row?.average_delay_when_late_seconds || 0) / 60,
      medianWhenLateMinutes: Number(row?.median_delay_when_late_seconds || 0) / 60,
    };
  }

  function stationRisk(stationId, line) { return stationMetric(stationId, line).probability; }

  function weightedComponent(rows, predicate, valueKey, countKey = "comparable_observations") {
    const matches = rows.filter(predicate);
    const total = matches.reduce((sum, row) => sum + Number(row[countKey] || 0), 0);
    return total ? matches.reduce((sum, row) => sum + Number(row[valueKey] || 0) * Number(row[countKey] || 0), 0) / total : 0;
  }

  function componentRows(rows, predicate) {
    return timeSelect.value === "all" ? rows.filter(predicate) : rows.filter((row) => predicate(row) && Number(row.service_hour) === Number(timeSelect.value));
  }

  function directionFor(line, fromStation, toStation) {
    return Number(directedEdges.find((edge) => edge.line === line && edge.from_station === fromStation && edge.to_station === toStation)?.direction_id);
  }

  function meanTransferWait(station, fromLine, toLine) {
    const rows = componentRows(transferComponents, (row) => row.parent_station === station && row.from_line === fromLine && row.to_line === toLine);
    return weightedComponent(rows, () => true, "mean_extra_transfer_wait_seconds", "comparable_connections") / 60;
  }

  function annotateDirections(steps) {
    steps.forEach((step) => {
      if (step.type !== "ride") return;
      step.direction = directionFor(step.line, step.fromStation, step.station);
    });
    steps.forEach((step, index) => {
      if (step.type !== "transfer") return;
      step.fromDirection = [...steps.slice(0, index)].reverse().find((item) => item.type === "ride")?.direction;
      step.toDirection = steps.slice(index + 1).find((item) => item.type === "ride")?.direction;
    });
  }

  function transferComponent(step) {
    const matches = componentRows(transferComponents, (row) => row.parent_station === step.station && row.from_line === step.fromLine && row.to_line === step.toLine && Number(row.from_direction) === step.fromDirection && Number(row.to_direction) === step.toDirection);
    const total = matches.reduce((sum, row) => sum + Number(row.comparable_connections || 0), 0);
    return {
      observations: total,
      extraWaitMinutes: total ? matches.reduce((sum, row) => sum + Number(row.mean_extra_transfer_wait_seconds) * Number(row.comparable_connections), 0) / total / 60 : 0,
      missedRate: total ? matches.reduce((sum, row) => sum + Number(row.missed_scheduled_connection_rate) * Number(row.comparable_connections), 0) / total : 0,
    };
  }

  function buildPassengerTime(steps) {
    const firstRide = steps.find((step) => step.type === "ride");
    const boardingMinutes = firstRide ? weightedComponent(componentRows(boardingWait, (row) => row.line === firstRide.line && row.parent_station === firstRide.fromStation), () => true, "mean_excess_wait_seconds") / 60 : 0;
    const inVehicleMinutes = steps.filter((step) => step.type === "ride").reduce((sum, step) => sum + weightedComponent(componentRows(inVehicle, (row) => row.line === step.line && row.to_station === step.station), () => true, "mean_excess_travel_seconds") / 60, 0);
    const transfers = steps.filter((step) => step.type === "transfer").map(transferComponent);
    const transferMinutes = transfers.reduce((sum, item) => sum + item.extraWaitMinutes, 0);
    return { boardingMinutes, inVehicleMinutes, transferMinutes, expectedMinutes: boardingMinutes + inVehicleMinutes + transferMinutes, transfers };
  }

  function planConnection(originId, destinationId, rows, preference = "reliable") {
    const adjacency = new Map();
    const add = (from, edge) => adjacency.set(from, [...(adjacency.get(from) || []), edge]);
    const node = (station, line) => `${station}::${line}`;
    graph.edges.forEach((edge) => {
      const forwardCost = 1 + (preference === "reliable" ? weightedComponent(componentRows(inVehicle, (row) => row.line === edge.line && row.to_station === edge.to), () => true, "mean_excess_travel_seconds") / 60 : 0);
      const reverseCost = 1 + (preference === "reliable" ? weightedComponent(componentRows(inVehicle, (row) => row.line === edge.line && row.to_station === edge.from), () => true, "mean_excess_travel_seconds") / 60 : 0);
      add(node(edge.from, edge.line), { to: node(edge.to, edge.line), type: "ride", line: edge.line, fromStation: edge.from, station: edge.to, cost: forwardCost });
      add(node(edge.to, edge.line), { to: node(edge.from, edge.line), type: "ride", line: edge.line, fromStation: edge.to, station: edge.from, cost: reverseCost });
    });
    const exposure = new Map(rows.map((row) => [transferKey(row.parent_station, row.from_line, row.to_line), row]));
    graph.stations.forEach((station) => station.lines.forEach((fromLine, index) => station.lines.slice(index + 1).forEach((toLine) => {
      const transfer = exposure.get(transferKey(station.id, fromLine, toLine));
      const extraWait = preference === "reliable" ? meanTransferWait(station.id, fromLine, toLine) : 0;
      const cost = 2.5 + extraWait;
      add(node(station.id, fromLine), { to: node(station.id, toLine), type: "transfer", station: station.id, fromLine, toLine, exposure: transfer?.combined_late_exposure, cost });
      add(node(station.id, toLine), { to: node(station.id, fromLine), type: "transfer", station: station.id, fromLine: toLine, toLine: fromLine, exposure: transfer?.combined_late_exposure, cost });
    })));
    const starts = stationById.get(originId)?.lines.map((line) => node(originId, line)) || [];
    const targets = new Set(stationById.get(destinationId)?.lines.map((line) => node(destinationId, line)) || []);
    const distance = new Map(starts.map((item) => [item, 0]));
    const previous = new Map();
    const visited = new Set();
    let current;
    while (true) {
      current = [...distance.entries()].filter(([item]) => !visited.has(item)).sort((a, b) => a[1] - b[1])[0]?.[0];
      if (!current || targets.has(current)) break;
      visited.add(current);
      (adjacency.get(current) || []).forEach((edge) => {
        const next = distance.get(current) + edge.cost;
        if (next < (distance.get(edge.to) ?? Infinity)) { distance.set(edge.to, next); previous.set(edge.to, { node: current, edge }); }
      });
    }
    if (!current || !targets.has(current)) return null;
    const steps = [];
    while (previous.has(current)) { const prior = previous.get(current); steps.unshift(prior.edge); current = prior.node; }
    return steps;
  }

  function routeLabel(steps) {
    return [...new Set(steps.filter((step) => step.type === "ride").map((step) => step.line))].join(" to ");
  }

  function routeSignature(steps) {
    return steps.map((step) => step.type === "ride" ? `${step.line}:${step.fromStation}:${step.station}` : `x:${step.station}:${step.fromLine}:${step.toLine}`).join("|");
  }

  function renderRouteOptions(originName, destinationName, fastest, reliable) {
    const panel = document.getElementById("route-options");
    if (!fastest || !reliable) { panel.innerHTML = ""; return; }
    annotateDirections(fastest);
    annotateDirections(reliable);
    const fastTime = buildPassengerTime(fastest);
    const reliableTime = buildPassengerTime(reliable);
    const rows = [
      { name: "Fewest stops", steps: fastest, time: fastTime },
      { name: "Lower expected delay", steps: reliable, time: reliableTime },
    ];
    if (routeSignature(fastest) === routeSignature(reliable)) {
      panel.innerHTML = `<p class="panel-kicker">Route options</p><h2>One clear rapid-transit path</h2><p>${originName} to ${destinationName} has the same fewest-stop and lowest expected-delay path in this network snapshot: ${routeLabel(reliable)}.</p>`;
      return;
    }
    panel.innerHTML = `<p class="panel-kicker">Route options</p><h2>Fewest stops or lower added time?</h2><p>Both paths use the selected hour. Compare transfers and historically expected added time.</p><table class="route-comparison"><thead><tr><th>Option</th><th>Lines</th><th>Transfers</th><th>Expected added time</th></tr></thead><tbody>${rows.map((route) => `<tr><td class="route-choice">${route.name}</td><td><b>${routeLabel(route.steps)}</b></td><td>${route.steps.filter((step) => step.type === "transfer").length}</td><td><b>+${route.time.expectedMinutes.toFixed(1)} min</b><small>${route.time.transfers.length ? `${percent(Math.max(...route.time.transfers.map((item) => item.missedRate)))} highest missed-connection rate` : "No transfer"}</small></td></tr>`).join("")}</tbody></table>`;
  }

  function renderFindings(passengerTime, originName, destinationName) {
    const panel = document.getElementById("trip-findings");
    if (!passengerTime.transfers.length) {
      panel.innerHTML = `<p class="panel-kicker">What this tells riders</p><h2>A direct trip avoids connection risk</h2><ul class="finding-list"><li>This ${originName} to ${destinationName} trip has no transfer; its historical added time comes from boarding and in-vehicle variation.</li><li>When timing matters, arrive early enough to cover the displayed extra boarding wait rather than budgeting for a transfer.</li></ul>`;
      return;
    }
    const transferShare = passengerTime.expectedMinutes ? passengerTime.transferMinutes / passengerTime.expectedMinutes : 0;
    const highestMissed = Math.max(...passengerTime.transfers.map((item) => item.missedRate));
    panel.innerHTML = `<p class="panel-kicker">What this tells riders</p><h2>The transfer is the fragile part</h2><ul class="finding-list"><li>${percent(transferShare)} of this route's historical added time comes after changing lines, rather than while riding.</li><li>For a time-critical arrival, treat the ${percent(highestMissed)} missed-connection rate as a reason to leave earlier or select a lower-risk hour from the reliability chart.</li></ul>`;
  }

  function renderJourney() {
    const origin = originSelect.value;
    const destination = destinationSelect.value;
    const originName = stationById.get(origin)?.name || "Start";
    const destinationName = stationById.get(destination)?.name || "Destination";
    const steps = origin === destination ? null : planConnection(origin, destination, activeTransfers);
    if (!steps) {
      activePlan = { transferKeys: new Set(), transferSteps: [], rideLines: [], routeStops: [], routeLegs: [], originName, destinationName };
      document.getElementById("journey-summary").innerHTML = "<p class=\"panel-kicker\">Trip summary</p><h2>Choose two different stations.</h2>";
      document.getElementById("trip-delay-budget").innerHTML = "";
      document.getElementById("route-options").innerHTML = "";
      document.getElementById("trip-findings").innerHTML = "";
      renderRouteRisk();
      return;
    }
    annotateDirections(steps);
    const actions = [];
    let ride;
    const flushRide = () => { if (ride) { actions.push(`<li class=\"ride-step\"><span style=\"background:${colors[ride.line]}\"></span><div><b>${ride.line} Line</b><small>${ride.from} to ${ride.to}</small></div></li>`); ride = null; } };
    steps.forEach((step) => {
      if (step.type === "ride") {
        const name = stationById.get(step.station)?.name || step.station;
        if (ride?.line === step.line) ride.to = name;
        else { flushRide(); ride = { line: step.line, from: stationById.get(step.fromStation)?.name || step.fromStation, to: name }; }
      } else {
        flushRide();
        const station = stationById.get(step.station)?.name || step.station;
        const component = transferComponent(step);
        const label = component.observations ? `${percent(component.missedRate)} missed` : "No match";
        actions.push(`<li class=\"transfer-step\"><span class=\"transfer-icon\">↔</span><div><b>Transfer at ${station}</b><small>${step.fromLine} to ${step.toLine}; scheduled connection missed</small></div><em>${label}</em></li>`);
      }
    });
    flushRide();
    const rideSteps = steps.filter((step) => step.type === "ride");
    const routeStops = [];
    rideSteps.forEach((step) => {
      if (!routeStops.some((stop) => stop.id === step.fromStation && stop.line === step.line)) routeStops.push({ id: step.fromStation, line: step.line });
      routeStops.push({ id: step.station, line: step.line });
    });
    activePlan = {
      transferKeys: new Set(steps.filter((step) => step.type === "transfer").map((step) => transferKey(step.station, step.fromLine, step.toLine))),
      transferSteps: steps.filter((step) => step.type === "transfer"),
      rideLines: [...new Set(rideSteps.map((step) => step.line))],
      routeStops,
      routeLegs: rideSteps.map((step) => ({ from: step.fromStation, to: step.station, line: step.line })),
      originName, destinationName
    };
    const transferCount = activePlan.transferSteps.length;
    document.getElementById("journey-summary").innerHTML = `<p class=\"panel-kicker\">Your route</p><h2>${originName} <span>to</span> ${destinationName}</h2><div class=\"trip-badges\"><span>${hourLabels[timeSelect.value]}</span><span>${transferCount ? `${transferCount} transfer${transferCount > 1 ? "s" : ""}` : "No transfers"}</span></div><ol class=\"journey-steps\">${actions.join("")}</ol>`;
    const passengerTime = buildPassengerTime(steps);
    const transferBreakdown = passengerTime.transfers.map((item) => `<li><span>Transfer wait</span><b>+${item.extraWaitMinutes.toFixed(1)} min</b><small>${item.observations ? `${percent(item.missedRate)} missed planned connection across ${item.observations.toLocaleString()} comparable transfers` : "No direction-specific match"}</small></li>`).join("");
    document.getElementById("trip-delay-budget").innerHTML = `<section class=\"delay-budget\"><p class=\"panel-kicker\">Average added trip time</p><h3>+${passengerTime.expectedMinutes.toFixed(1)} min expected</h3><p>For this historical ${hourLabels[timeSelect.value]} sample.</p><ul class=\"time-breakdown\"><li><span>Extra boarding wait</span><b>+${passengerTime.boardingMinutes.toFixed(1)} min</b><small>Observed headway above schedule; assumes a random rider arrival.</small></li><li><span>Extra in-vehicle time</span><b>+${passengerTime.inVehicleMinutes.toFixed(1)} min</b><small>Actual travel time above schedule along the selected route.</small></li>${transferBreakdown}</ul><small class=\"budget-note\">A transfer uses a three-minute walk assumption and asks whether the originally scheduled outgoing train had already departed. This is historical expected time, not a guaranteed buffer or a live prediction.</small></section>`;
    const fastest = planConnection(origin, destination, activeTransfers, "fastest");
    renderRouteOptions(originName, destinationName, fastest, steps);
    renderFindings(passengerTime, originName, destinationName);
    document.getElementById("map-title").textContent = `${originName} to ${destinationName}`;
    renderRouteRisk();
    refreshLiveAlerts(activePlan.rideLines);
  }

  function renderRouteRisk() {
    const panel = document.getElementById("connection-risk");
    if (!activePlan.transferSteps.length) {
      panel.innerHTML = "<p class=\"panel-kicker\">Time sensitivity</p><h3>No transfer to protect</h3><p class=\"muted\">This route stays on one line.</p>";
      if (routeChart) { routeChart.destroy(); routeChart = null; }
      return;
    }
    panel.innerHTML = "<p class=\"panel-kicker\">Transfer reliability</p><h3>When the scheduled connection is missed</h3><canvas id=\"connection-risk-chart\"></canvas>";
    const hours = [6, 7, 8, 9, 15, 16, 17, 18, 19];
    const datasets = activePlan.transferSteps.map((step) => ({
      label: `${stationById.get(step.station)?.name}: ${step.fromLine} to ${step.toLine}`,
      data: hours.map((hour) => Number(transferComponents.find((item) => Number(item.service_hour) === hour && item.parent_station === step.station && item.from_line === step.fromLine && item.to_line === step.toLine && Number(item.from_direction) === step.fromDirection && Number(item.to_direction) === step.toDirection)?.missed_scheduled_connection_rate || 0) * 100),
      borderColor: colors[step.fromLine], backgroundColor: colors[step.fromLine], borderWidth: 2.5, pointRadius: 2.5, tension: 0.3
    }));
    if (routeChart) routeChart.destroy();
    routeChart = new Chart(document.getElementById("connection-risk-chart"), {
      type: "line", data: { labels: hours.map((hour) => `${hour}:00`), datasets },
      options: { maintainAspectRatio: false, plugins: { legend: { display: datasets.length > 1, position: "bottom", labels: { boxWidth: 9, padding: 8 } }, tooltip: { callbacks: { label: (item) => `${item.formattedValue}% missed scheduled connection` } } }, scales: { x: { grid: { display: false }, ticks: { maxRotation: 0, font: { size: 10 } } }, y: { beginAtZero: true, ticks: { callback: (value) => `${value}%`, font: { size: 10 } }, grid: { color: "#e2e7e1" } } } }
    });
  }

  async function refreshLiveAlerts(lines) {
    const panel = document.getElementById("live-alerts");
    panel.innerHTML = "<p class=\"panel-kicker\">Live right now</p><h3>Checking service notices</h3>";
    try {
      const response = await fetch("https://api-v3.mbta.com/alerts?page[limit]=100");
      if (!response.ok) throw new Error();
      const matches = (await response.json()).data.filter((alert) => (alert.attributes.informed_entity || []).some((entity) => lines.some((line) => entity.route === line || (line === "Green" && entity.route?.startsWith("Green-"))))).slice(0, 2);
      if (!matches.length) { panel.innerHTML = "<p class=\"panel-kicker\">Live right now</p><h3>No returned notices</h3><p class=\"muted\">No current MBTA alerts matched the lines in this trip.</p>"; return; }
      panel.innerHTML = `<p class=\"panel-kicker\">Live right now</p><h3>${matches.length} notice${matches.length > 1 ? "s" : ""} on this route</h3><ul class=\"notice-list\">${matches.map((alert) => {
        const routes = [...new Set((alert.attributes.informed_entity || []).map((entity) => entity.route || "").filter(Boolean))].join(", ") || "MBTA";
        const effect = String(alert.attributes.effect || "notice").replaceAll("_", " ");
        return `<li><b>${routes}</b><span>${effect}</span></li>`;
      }).join("")}</ul>`;
    } catch { panel.innerHTML = "<p class=\"panel-kicker\">Live right now</p><h3>Not available</h3><p class=\"muted\">The historical route risk remains available.</p>"; }
  }

  function renderMap() {
   const positions = {
      "Boston College": { point: [10.2, 43.2] }, "South Street": { point: [11.7, 41.5] }, "Chestnut Hill Avenue": { point: [13, 40.1] }, "Chiswick Road": { point: [14.2, 38.9] }, "Sutherland Road": { point: [15.5, 37.7] }, "Washington Street": { point: [16.8, 36.4] }, "Warren Street": { point: [18.1, 35.1] }, "Allston Street": { point: [19.4, 33.8] }, "Griggs Street": { point: [20.8, 32.5] }, "Harvard Avenue": { point: [22, 31.2] }, "Packards Corner": { point: [23.4, 29.9] }, "Babcock Street": { point: [24.7, 28.6] }, "Amory Street": { point: [26, 27.4] }, "Boston University Central": { point: [27.3, 26.1] }, "Boston University East": { point: [28.7, 24.9] }, "Blandford Street": { point: [30, 23.8] }, "Kenmore": { point: [32.5, 24.2] }, "Hynes Convention Center": { point: [34.4, 25.1] }, "Copley": { point: [36.3, 26.1] }, "Arlington": { point: [38.7, 27.4] }, "Boylston": { point: [41, 28.8] }, "Park Street": { point: [43.8, 30.8] }, "Government Center": { point: [48.3, 33] }, "Haymarket": { point: [64.8, 29.8] }, "North Station": { point: [64.8, 27.4] }, "Community College": { point: [64.8, 20.8] },
      "Andrew": { point: [70.6, 58.3] }, "Broadway": { point: [70.6, 54.5] }, "South Station": { point: [65.2, 44.4] }, "Downtown Crossing": { point: [63.7, 41.5] }, "State": { point: [64.9, 36.5] }, "Alewife": { point: [34.7, 14.2] }, "Airport": { point: [81.4, 28.3] }, "Ashmont": { point: [66.5, 80.2] }
   };
    const positionFor = (stationId) => {
      const station = stationById.get(stationId);
      if (positions[station?.name]) return positions[station.name].point;
      return null;
    };
    const top = [];
    const onTrip = activeTransfers.filter((row) => positionFor(row.parent_station) && activePlan.transferKeys.has(transferKey(row.parent_station, row.from_line, row.to_line)));
    const visible = [...top, ...onTrip];
    const tripPoints = activePlan.routeStops.map((stop) => positionFor(stop.id)).filter(Boolean);
    const routePoints = tripPoints.map(([x, y]) => `${x},${y}`).join(" ");
    const routeSegments = activePlan.routeLegs.map((leg) => {
      const from = positionFor(leg.from);
      const to = positionFor(leg.to);
      return from && to ? `<line class=\"route-segment\" x1=\"${from[0]}\" y1=\"${from[1]}\" x2=\"${to[0]}\" y2=\"${to[1]}\" stroke=\"${colors[leg.line]}\"/>` : "";
    }).join("");
    const routeLine = tripPoints.length > 1 ? `<defs><marker id=\"route-arrow\" markerWidth=\"4\" markerHeight=\"4\" refX=\"3.1\" refY=\"2\" orient=\"auto\"><path d=\"M0,0 L4,2 L0,4 Z\" fill=\"#f4bd51\"/></marker></defs><polyline class=\"route-halo\" points=\"${routePoints}\"/><polyline class=\"route-underlay\" points=\"${routePoints}\"/>${routeSegments}<polyline class=\"route-direction\" points=\"${routePoints}\" marker-end=\"url(#route-arrow)\"/>` : "";
    const routeMarkers = activePlan.routeStops.map((stop) => {
      const station = stationById.get(stop.id);
      const p = positionFor(stop.id);
      if (!p) return "";
      const isOrigin = stop.id === originSelect.value;
      const isDestination = stop.id === destinationSelect.value;
      const isTransfer = activePlan.transferSteps.some((step) => step.station === stop.id);
      const risk = stationRisk(stop.id, stop.line);
      const highRisk = isOrigin || isDestination || isTransfer ? "" : risk >= .3 ? "is-high-risk" : risk >= .18 ? "is-moderate-risk" : "";
      return `<button class=\"route-stop ${isOrigin ? "is-origin" : ""} ${isDestination ? "is-destination" : ""} ${isTransfer ? "is-transfer" : ""} ${highRisk}\" data-station=\"${stop.id}\" data-line=\"${stop.line}\" style=\"left:${p[0]}%;top:${p[1]}%;background:${colors[stop.line]}\" aria-label=\"${station.name}, ${stop.line} Line\"></button>`;
    }).join("");
    const leaders = "";
    const markers = visible.map((row, index) => { const p = positionFor(row.parent_station); const isTrip = activePlan.transferKeys.has(transferKey(row.parent_station, row.from_line, row.to_line)); const step = activePlan.transferSteps.find((item) => transferKey(item.station, item.fromLine, item.toLine) === transferKey(row.parent_station, row.from_line, row.to_line)); const component = step ? transferComponent(step) : null; const label = component?.observations ? `${percent(component.missedRate)} missed scheduled connection` : "transfer"; return `<button class=\"transfer-marker ${isTrip ? "is-on-trip" : ""}\" type=\"button\" data-key=\"${transferKey(row.parent_station, row.from_line, row.to_line)}\" style=\"left:${p[0]}%;top:${p[1]}%\" aria-label=\"${row.station_name}, ${label}\"><span>${isTrip ? "↔" : index + 1}</span></button>`; }).join("");
    document.getElementById("line-map").innerHTML = `<div class=\"map-controls\"><button type=\"button\" id=\"zoom-in\" aria-label=\"Zoom in\">+</button><button type=\"button\" id=\"zoom-out\" aria-label=\"Zoom out\">-</button><button type=\"button\" id=\"zoom-fit\">Fit</button></div><div id=\"map-viewport\" class=\"map-viewport\"><div id=\"schematic-map\" class=\"schematic-map\"><img src=\"assets/mbta-official-subway-map.jpg\" alt=\"Official MBTA Rapid Transit and Frequent Bus Routes map, April 2025\"><svg class=\"journey-route\" viewBox=\"0 0 100 100\" preserveAspectRatio=\"none\" aria-hidden=\"true\">${routeLine}</svg><svg class=\"map-leaders\" viewBox=\"0 0 100 100\" preserveAspectRatio=\"none\">${leaders}</svg>${routeMarkers}${markers}<div id=\"map-popup\" class=\"map-popup\" hidden></div></div></div>`;
    const popup = document.getElementById("map-popup");
    document.querySelectorAll(".transfer-marker").forEach((marker) => marker.addEventListener("click", () => {
      const row = visible.find((item) => transferKey(item.parent_station, item.from_line, item.to_line) === marker.dataset.key);
      const step = activePlan.transferSteps.find((item) => transferKey(item.station, item.fromLine, item.toLine) === marker.dataset.key);
      const component = step ? transferComponent(step) : null;
      const p = positionFor(row.parent_station);
      popup.hidden = false;
      popup.style.left = `${Math.min(p[0] + 4, 71)}%`;
      popup.style.top = `${Math.min(p[1] + 2, 74)}%`;
      popup.innerHTML = `<button class=\"popup-close\" aria-label=\"Close\">x</button><p>${hourLabels[timeSelect.value]}</p><strong>${row.station_name}</strong><b>${component?.observations ? percent(component.missedRate) : "--"}</b><small>missed scheduled connection</small><div><span><i style=\"background:${colors[step?.fromLine]}\"></i>${step?.fromLine || row.from_line} to ${step?.toLine || row.to_line}<em>+${component?.extraWaitMinutes.toFixed(1) || "--"} min</em></span></div>`;
      popup.querySelector(".popup-close").onclick = () => { popup.hidden = true; };
    }));
    document.querySelectorAll(".route-stop").forEach((marker) => marker.addEventListener("click", () => {
      const station = stationById.get(marker.dataset.station);
      const p = positionFor(marker.dataset.station);
      const metric = stationMetric(marker.dataset.station, marker.dataset.line);
      popup.hidden = false;
      popup.style.left = `${Math.min(p[0] + 3, 71)}%`;
      popup.style.top = `${Math.min(p[1] + 2, 74)}%`;
      const duration = metric.averageWhenLateMinutes ? `~${metric.averageWhenLateMinutes.toFixed(1)} min` : "No duration estimate";
      popup.innerHTML = `<button class=\"popup-close\" aria-label=\"Close\">x</button><p>${hourLabels[timeSelect.value]}</p><strong>${station?.name}</strong><b>${percent(metric.probability)} chance</b><small>of a ${marker.dataset.line} Line stop event more than five minutes late</small><div><span>Typical delay <em>${duration}</em></span></div>`;
      popup.querySelector(".popup-close").onclick = () => { popup.hidden = true; };
    }));
    let zoom = 1;
    const setZoom = () => { document.getElementById("schematic-map").style.width = `${zoom * 100}%`; };
    document.getElementById("zoom-in").onclick = () => { zoom = Math.min(1.7, zoom + 0.2); setZoom(); };
    document.getElementById("zoom-out").onclick = () => { zoom = Math.max(1, zoom - 0.2); setZoom(); };
    document.getElementById("zoom-fit").onclick = () => { zoom = 1; setZoom(); document.getElementById("map-viewport").scrollTo({ left: 0, top: 0, behavior: "smooth" }); };
  }

  function render() {
    activeTransfers = transferWindow();
    renderJourney();
    renderMap();
  }
  document.getElementById("trip-form").addEventListener("submit", (event) => { event.preventDefault(); render(); });
  originSelect.addEventListener("change", render);
  destinationSelect.addEventListener("change", render);
  timeSelect.addEventListener("change", render);
  render();
}
main().catch((error) => { document.querySelector("main").innerHTML = `<p>Data could not be loaded: ${error.message}</p>`; });
