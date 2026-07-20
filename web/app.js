// Shared behaviour for the Crawlr site (index + docs).
(function () {
  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (window.AOS) {
    AOS.init({ duration: 650, easing: "ease-in-out", once: true, offset: 80, disable: reduce });
  }

  // Copy-to-clipboard on code blocks (button lives in the terminal chrome).
  document.querySelectorAll("pre").forEach(function (pre) {
    var host = pre.closest(".terminal") || pre;
    var text = pre.innerText;
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "copy";
    btn.textContent = "Copy";
    btn.addEventListener("click", function () {
      navigator.clipboard.writeText(text).then(function () {
        btn.textContent = "Copied";
        setTimeout(function () { btn.textContent = "Copy"; }, 1200);
      });
    });
    host.appendChild(btn);
  });

  // Click-to-copy chips (e.g. the hero install command).
  document.querySelectorAll(".copychip").forEach(function (chip) {
    chip.addEventListener("click", function () {
      navigator.clipboard.writeText(chip.getAttribute("data-copy")).then(function () {
        var icon = chip.querySelector(".copychip-icon");
        var original = icon ? icon.innerHTML : "";
        if (icon) icon.innerHTML = '<i class="fa-solid fa-check" aria-hidden="true"></i>';
        chip.classList.add("copied");
        setTimeout(function () {
          if (icon) icon.innerHTML = original;
          chip.classList.remove("copied");
        }, 1200);
      });
    });
  });

  // Docs: highlight the current section in the sidebar as you scroll.
  var tocLinks = document.querySelectorAll(".doc-side a");
  if (tocLinks.length) {
    var sections = [].map.call(tocLinks, function (a) {
      return document.getElementById(a.getAttribute("href").slice(1));
    });
    var onScroll = function () {
      var pos = window.scrollY + 120;
      var current = -1;
      sections.forEach(function (sec, i) { if (sec && sec.offsetTop <= pos) current = i; });
      tocLinks.forEach(function (a, i) { a.classList.toggle("active", i === current); });
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
  }
})();
