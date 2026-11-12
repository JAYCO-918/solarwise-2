// Presenting the deck in a browser: one slide at a time, scaled to the window.
//   arrows / space / PageUp / PageDown / click: move     Home / End: first / last slide
//   N: speaker notes     T: start or pause the 5-minute clock     R: reset the clock     F: full screen
// Shown inside a frame of another page (a preview pane), the keys work once the frame has been clicked, and full
// screen may be refused by the embedding page: the deck then says to open it in its own tab.
// With ?flat in the address every slide is laid out one under the other (used to print and to build the files).
(function () {
  var root = document.documentElement;
  var slides = Array.prototype.slice.call(document.querySelectorAll(".slide"));
  var params = new URLSearchParams(location.search);
  slides.forEach(function (slide, index) {
    var number = slide.querySelector(".pageno");
    if (number) number.textContent = String(index + 1);
  });
  if (params.has("flat")) {
    root.classList.add("flat");
    return;
  }
  root.classList.add("show");

  var TOTAL = 300; // seconds
  var main = slides.filter(function (s) { return !s.hasAttribute("data-backup"); }).length;
  var current = 0;
  var elapsed = 0;
  var running = false;
  var last = 0;

  var ui = document.createElement("div");
  ui.className = "ui";
  ui.innerHTML =
    '<div class="ui-progress"></div>' +
    '<div class="ui-hint"></div>' +
    '<div class="ui-notes"><div class="meta"><b class="where"></b><span class="budget"></span><span class="clock">0:00</span></div><div class="text"></div></div>';
  document.body.appendChild(ui);
  var progress = ui.querySelector(".ui-progress");
  var hint = ui.querySelector(".ui-hint");
  var notes = ui.querySelector(".ui-notes");
  var clock = ui.querySelector(".clock");

  // Only characters of the embedded font: no arrows, which some computers would draw as empty boxes.
  var HELP = "Arrow keys or click: move \u00b7 N: script \u00b7 T: clock \u00b7 F: full screen";
  var framed = window.top !== window.self;
  var hintTimer = 0;
  function say(html, ms) {
    hint.innerHTML = html;
    hint.classList.remove("gone");
    clearTimeout(hintTimer);
    hintTimer = setTimeout(function () { hint.classList.add("gone"); }, ms);
  }
  function noFullScreen() {
    if (framed) {
      say('Full screen is not available inside this pane. <a href="' + location.href.split("#")[0] + '" target="_blank" rel="noopener">Open the slides in their own tab</a>, then press F.', 12000);
    } else {
      say("Full screen is not available here: use the full-screen command of the browser (often F11).", 9000);
    }
  }
  function toggleFullScreen() {
    if (document.fullscreenElement) {
      document.exitFullscreen();
      return true;
    }
    if (!document.fullscreenEnabled || !root.requestFullscreen) {
      noFullScreen();
      return false;
    }
    root.requestFullscreen().catch(noFullScreen);
    return true;
  }

  function fit() {
    var scale = Math.min(window.innerWidth / 1280, window.innerHeight / 720);
    root.style.setProperty("--scale", String(scale));
  }
  function mmss(seconds) {
    var s = Math.max(0, Math.round(seconds));
    return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
  }
  function show(index) {
    current = Math.max(0, Math.min(slides.length - 1, index));
    slides.forEach(function (slide, i) { slide.classList.toggle("current", i === current); });
    progress.style.width = ((current + 1) / slides.length) * 100 + "%";
    var slide = slides[current];
    var source = slide.querySelector(".notes");
    var backup = slide.hasAttribute("data-backup");
    var start = 0;
    for (var i = 0; i < current; i += 1) start += Number(slides[i].getAttribute("data-seconds") || 0);
    var seconds = Number(slide.getAttribute("data-seconds") || 0);
    ui.querySelector(".where").textContent = backup ? "Backup slide" : "Slide " + (current + 1) + " of " + main;
    ui.querySelector(".budget").textContent = backup ? "for questions only" : seconds + " s \u00b7 from " + mmss(start) + " to " + mmss(start + seconds);
    ui.querySelector(".text").innerHTML = source ? source.innerHTML : "";
    if (history.replaceState) history.replaceState(null, "", "#" + (current + 1));
  }
  function tick(now) {
    if (running) {
      elapsed += (now - last) / 1000;
      last = now;
    }
    clock.textContent = mmss(elapsed) + " / " + mmss(TOTAL);
    clock.classList.toggle("over", elapsed > TOTAL);
    requestAnimationFrame(tick);
  }

  document.addEventListener("keydown", function (event) {
    if (event.metaKey || event.ctrlKey || event.altKey) return;
    var key = event.key;
    if (key === "ArrowRight" || key === "PageDown" || key === " " || key === "Enter") show(current + 1);
    else if (key === "ArrowLeft" || key === "PageUp" || key === "Backspace") show(current - 1);
    else if (key === "Home") show(0);
    else if (key === "End") show(slides.length - 1);
    else if (key === "n" || key === "N") notes.classList.toggle("open");
    else if (key === "t" || key === "T") { running = !running; last = performance.now(); }
    else if (key === "r" || key === "R") { elapsed = 0; running = false; }
    else if (key === "f" || key === "F") {
      event.preventDefault();
      if (toggleFullScreen()) hint.classList.add("gone");
      return;
    } else return;
    hint.classList.add("gone");
    event.preventDefault();
  });
  document.addEventListener("click", function (event) {
    if (event.target.closest(".ui-notes, .ui-hint")) return;
    show(event.clientX < window.innerWidth * 0.3 ? current - 1 : current + 1);
    hint.classList.add("gone");
  });
  window.addEventListener("resize", fit);
  window.addEventListener("hashchange", function () { show((parseInt(location.hash.slice(1), 10) || 1) - 1); });
  say(HELP, 7000);

  fit();
  show((parseInt(location.hash.slice(1), 10) || 1) - 1);
  requestAnimationFrame(tick);
})();
