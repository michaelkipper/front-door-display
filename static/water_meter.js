/**
 * Water Meter module — reading display and 30-minute usage graph.
 *
 * Shows the current cubic-metre reading in the lower-right corner.
 * Tap to open an overlay graph of usage over the last 30 minutes.
 */
(function () {
  "use strict";

  // --- DOM ---
  const readingEl = document.getElementById("water-reading");
  const overlay = document.getElementById("water-overlay");
  const canvas = document.getElementById("water-graph");
  const closeBtn = document.getElementById("water-close");

  if (!readingEl || !overlay || !canvas || !closeBtn) return;

  const ctx = canvas.getContext("2d");
  const POLL_MS = 5000;

  // --- Reading display ---
  async function refreshReading() {
    try {
      const resp = await fetch("/api/water");
      if (!resp.ok) return;
      const data = await resp.json();
      if (data.cubic_metres != null) {
        readingEl.textContent = data.cubic_metres.toFixed(4) + " m³";
      } else {
        readingEl.textContent = "-- m³";
      }
    } catch (_) {
      // keep last display
    }
  }

  // --- Graph ---
  function drawGraph(history) {
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const w = rect.width;
    const h = rect.height;
    const pad = { top: 30, right: 20, bottom: 40, left: 60 };

    ctx.clearRect(0, 0, w, h);

    if (!history || history.length < 2) {
      ctx.fillStyle = "#aaa";
      ctx.font = "16px Inter, sans-serif";
      ctx.textAlign = "center";
      ctx.fillText("Collecting data…", w / 2, h / 2);
      return;
    }

    // Compute per-interval usage (deltas)
    const points = [];
    for (let i = 1; i < history.length; i++) {
      const dt = history[i].t - history[i - 1].t;
      const dv = history[i].value - history[i - 1].value;
      // litres used in this interval
      const litres = dv * 1000;
      points.push({ t: history[i].t, litres: litres, dt: dt });
    }

    if (points.length < 1) {
      ctx.fillStyle = "#aaa";
      ctx.font = "16px Inter, sans-serif";
      ctx.textAlign = "center";
      ctx.fillText("Collecting data…", w / 2, h / 2);
      return;
    }

    const now = points[points.length - 1].t;
    const tMin = now - 30 * 60;
    const maxLitres = Math.max(0.5, ...points.map((p) => p.litres));

    const plotW = w - pad.left - pad.right;
    const plotH = h - pad.top - pad.bottom;

    function xPos(t) {
      return pad.left + ((t - tMin) / (now - tMin)) * plotW;
    }
    function yPos(v) {
      return pad.top + plotH - (v / maxLitres) * plotH;
    }

    // Axes
    ctx.strokeStyle = "rgba(255,255,255,0.2)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(pad.left, pad.top);
    ctx.lineTo(pad.left, pad.top + plotH);
    ctx.lineTo(pad.left + plotW, pad.top + plotH);
    ctx.stroke();

    // Y-axis labels
    ctx.fillStyle = "rgba(255,255,255,0.6)";
    ctx.font = "12px Inter, sans-serif";
    ctx.textAlign = "right";
    const ySteps = 4;
    for (let i = 0; i <= ySteps; i++) {
      const val = (maxLitres / ySteps) * i;
      const y = yPos(val);
      ctx.fillText(val.toFixed(1) + " L", pad.left - 6, y + 4);
      if (i > 0) {
        ctx.strokeStyle = "rgba(255,255,255,0.07)";
        ctx.beginPath();
        ctx.moveTo(pad.left, y);
        ctx.lineTo(pad.left + plotW, y);
        ctx.stroke();
      }
    }

    // X-axis labels (every 5 min)
    ctx.textAlign = "center";
    for (let m = 0; m <= 30; m += 5) {
      const t = tMin + m * 60;
      const x = xPos(t);
      const label = m === 30 ? "now" : "-" + (30 - m) + "m";
      ctx.fillStyle = "rgba(255,255,255,0.6)";
      ctx.fillText(label, x, pad.top + plotH + 20);
    }

    // Bar chart of usage per interval
    ctx.fillStyle = "rgba(59, 130, 246, 0.7)";
    const barWidth = Math.max(2, plotW / points.length - 1);
    for (const p of points) {
      if (p.t < tMin) continue;
      const x = xPos(p.t) - barWidth / 2;
      const barH = (p.litres / maxLitres) * plotH;
      ctx.fillRect(x, pad.top + plotH - barH, barWidth, barH);
    }

    // Title
    const totalLitres = points.reduce((s, p) => s + (p.t >= tMin ? p.litres : 0), 0);
    ctx.fillStyle = "rgba(255,255,255,0.8)";
    ctx.font = "bold 14px Inter, sans-serif";
    ctx.textAlign = "left";
    ctx.fillText(
      "Water usage — last 30 min: " + totalLitres.toFixed(1) + " L",
      pad.left,
      pad.top - 10
    );
  }

  async function showGraph() {
    overlay.classList.add("visible");
    try {
      const resp = await fetch("/api/water/history");
      if (!resp.ok) return;
      const history = await resp.json();
      drawGraph(history);
    } catch (_) {
      // graph stays as-is
    }
  }

  // --- Events ---
  readingEl.addEventListener("click", function () {
    showGraph();
  });
  closeBtn.addEventListener("click", function () {
    overlay.classList.remove("visible");
  });
  overlay.addEventListener("click", function (e) {
    if (e.target === overlay) overlay.classList.remove("visible");
  });

  // --- Init ---
  refreshReading();
  setInterval(refreshReading, POLL_MS);
})();
