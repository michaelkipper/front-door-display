/**
 * Hourglass countdown module.
 *
 * Shows a canvas-based sand hourglass animation on the right side of the
 * screen when there are <= 15 minutes until the next calendar event
 * (candle lighting or havdalah).
 */
(function () {
  "use strict";

  var container = document.getElementById("hourglass-container");
  var canvas = document.getElementById("hourglass-canvas");
  var countdownEl = document.getElementById("hourglass-countdown");
  if (!container || !canvas || !countdownEl) return;

  var ctx = canvas.getContext("2d");
  var COUNTDOWN_MINUTES = 15;
  var nextEventEpoch = null;
  var animId = null;

  // Sand grain pool
  var grains = [];
  var MAX_GRAINS = 60;
  var SAND_COLOR_TOP = "#e2b866";
  var SAND_COLOR_FALL = "#d4a84b";
  var SAND_COLOR_BOTTOM = "#c99a3a";
  var GLASS_COLOR = "rgba(255,255,255,0.25)";
  var GLASS_STROKE = "rgba(255,255,255,0.5)";
  var FRAME_COLOR = "rgba(200,180,140,0.9)";

  function getGeometry(w, h) {
    var cx = w / 2;
    var padX = w * 0.12;
    var padY = h * 0.06;
    var frameH = h * 0.04;
    var glassTop = padY + frameH;
    var glassBot = h - padY - frameH;
    var mid = h / 2;
    var neckR = w * 0.04;
    return {
      cx: cx, padX: padX, padY: padY, frameH: frameH,
      glassTop: glassTop, glassBot: glassBot, mid: mid,
      neckR: neckR,
      left: padX, right: w - padX,
      w: w, h: h
    };
  }

  function roundRect(x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + w - r, y);
    ctx.quadraticCurveTo(x + w, y, x + w, y + r);
    ctx.lineTo(x + w, y + h - r);
    ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    ctx.lineTo(x + r, y + h);
    ctx.quadraticCurveTo(x, y + h, x, y + h - r);
    ctx.lineTo(x, y + r);
    ctx.quadraticCurveTo(x, y, x + r, y);
    ctx.closePath();
  }

  function drawGlass(g) {
    var cx = g.cx, left = g.left, right = g.right;
    var gt = g.glassTop, gb = g.glassBot, mid = g.mid, nr = g.neckR;

    // Top frame bar
    ctx.fillStyle = FRAME_COLOR;
    roundRect(left - 4, g.padY, right - left + 8, g.frameH, 3);
    ctx.fill();
    // Bottom frame bar
    roundRect(left - 4, gb, right - left + 8, g.frameH, 3);
    ctx.fill();

    // Glass outline — upper bulb
    ctx.beginPath();
    ctx.moveTo(left, gt);
    ctx.bezierCurveTo(left, mid - nr * 2, cx - nr, mid, cx - nr, mid);
    ctx.lineTo(cx + nr, mid);
    ctx.bezierCurveTo(cx + nr, mid, right, mid - nr * 2, right, gt);
    // Lower bulb
    ctx.moveTo(right, gb);
    ctx.bezierCurveTo(right, mid + nr * 2, cx + nr, mid, cx + nr, mid);
    ctx.lineTo(cx - nr, mid);
    ctx.bezierCurveTo(cx - nr, mid, left, mid + nr * 2, left, gb);

    ctx.strokeStyle = GLASS_STROKE;
    ctx.lineWidth = 1.5;
    ctx.stroke();
    ctx.fillStyle = GLASS_COLOR;
    ctx.fill("evenodd");
  }

  function drawSand(g, fraction) {
    var cx = g.cx, left = g.left, right = g.right;
    var gt = g.glassTop, gb = g.glassBot, mid = g.mid, nr = g.neckR;
    var topH = (mid - gt) * 0.7;
    var botH = (gb - mid) * 0.7;

    // Top sand (decreasing)
    var topLevel = topH * (1 - fraction);
    if (topLevel > 1) {
      ctx.fillStyle = SAND_COLOR_TOP;
      ctx.beginPath();
      var surfY = gt + (topH - topLevel) + 2;
      var spread = (1 - fraction) * 0.85;
      var sl = cx - (right - left) / 2 * spread;
      var sr = cx + (right - left) / 2 * spread;
      ctx.moveTo(sl, surfY);
      ctx.lineTo(sr, surfY);
      ctx.lineTo(cx + nr * 0.5, mid - 2);
      ctx.lineTo(cx - nr * 0.5, mid - 2);
      ctx.closePath();
      ctx.fill();
    }

    // Bottom sand (increasing) — pile shape
    var botLevel = botH * fraction;
    if (botLevel > 1) {
      ctx.fillStyle = SAND_COLOR_BOTTOM;
      ctx.beginPath();
      var baseY = gb - 2;
      var pileSpread = Math.min(fraction * 1.2, 1.0);
      var bl = cx - (right - left) / 2 * pileSpread;
      var br = cx + (right - left) / 2 * pileSpread;
      ctx.moveTo(bl, baseY);
      ctx.quadraticCurveTo(cx, baseY - botLevel * 1.4, br, baseY);
      ctx.closePath();
      ctx.fill();
    }

    // Falling stream through neck
    if (fraction < 0.98) {
      ctx.strokeStyle = SAND_COLOR_FALL;
      ctx.lineWidth = nr * 0.6;
      ctx.beginPath();
      ctx.moveTo(cx, mid - 2);
      var streamEnd = mid + (gb - mid) * (0.3 + fraction * 0.65);
      ctx.lineTo(cx, streamEnd);
      ctx.stroke();
    }
  }

  function drawFallingGrains(g, fraction) {
    if (fraction >= 0.98) return;
    var cx = g.cx, mid = g.mid, gb = g.glassBot, nr = g.neckR;

    // Spawn new grains
    if (grains.length < MAX_GRAINS && Math.random() < 0.4) {
      grains.push({
        x: cx + (Math.random() - 0.5) * nr * 0.6,
        y: mid + nr,
        vy: 0.5 + Math.random() * 1.5,
        vx: (Math.random() - 0.5) * 0.5,
        r: 0.8 + Math.random() * 0.8,
        life: 1.0
      });
    }

    var landY = gb - (gb - mid) * fraction * 0.7;
    ctx.fillStyle = SAND_COLOR_FALL;
    var alive = [];
    for (var i = 0; i < grains.length; i++) {
      var p = grains[i];
      p.y += p.vy;
      p.x += p.vx;
      p.vy += 0.1;
      p.life -= 0.015;
      if (p.y < landY && p.life > 0) {
        ctx.globalAlpha = p.life;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
        ctx.fill();
        alive.push(p);
      }
    }
    ctx.globalAlpha = 1;
    grains = alive;
  }

  // --- Animation loop ---
  function render() {
    var dpr = window.devicePixelRatio || 1;
    var rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    var w = rect.width;
    var h = rect.height;
    ctx.clearRect(0, 0, w, h);

    var now = Date.now() / 1000;
    var secsLeft = nextEventEpoch ? Math.max(0, nextEventEpoch - now) : 0;
    var totalSecs = COUNTDOWN_MINUTES * 60;
    var fraction = Math.min(1, 1 - secsLeft / totalSecs);

    var g = getGeometry(w, h);
    drawGlass(g);
    drawSand(g, fraction);
    drawFallingGrains(g, fraction);

    // Countdown text
    var mins = Math.floor(secsLeft / 60);
    var secs = Math.floor(secsLeft % 60);
    countdownEl.textContent = mins + ":" + (secs < 10 ? "0" : "") + secs;

    if (secsLeft <= 0) {
      countdownEl.textContent = "0:00";
      setTimeout(function () { hide(); }, 3000);
      return;
    }

    animId = requestAnimationFrame(render);
  }

  function show() {
    if (!container.classList.contains("visible")) {
      grains = [];
      container.classList.add("visible");
    }
    if (!animId) {
      animId = requestAnimationFrame(render);
    }
  }

  function hide() {
    container.classList.remove("visible");
    if (animId) {
      cancelAnimationFrame(animId);
      animId = null;
    }
    grains = [];
  }

  // Called from global scope when /api/state updates
  window.hourglassUpdate = function (epoch) {
    nextEventEpoch = epoch;
    if (!epoch) { hide(); return; }
    var now = Date.now() / 1000;
    var secsLeft = epoch - now;
    if (secsLeft > 0 && secsLeft <= COUNTDOWN_MINUTES * 60) {
      show();
    } else {
      hide();
    }
  };
})();
