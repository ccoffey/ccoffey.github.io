(() => {
  const config = window.buildPageConfig;
  if (!config || config.type !== "major") return;

  window.toggleNarrative = () => {
    const container = document.getElementById("narrativeCollapsible");
    const text = document.getElementById("narrativeToggleText");
    const icon = document.getElementById("narrativeToggleIcon");
    if (!container) return;

    const isExpanding = !container.classList.contains("expanded");
    if (text) text.textContent = isExpanding ? "Collapse story" : "Read full story";
    if (icon) icon.style.transform = isExpanding ? "rotate(180deg)" : "rotate(0deg)";

    if (isExpanding) {
      if (typeof gtag === "function") {
        gtag("event", "read_story", {
          project_title: config.title,
          project_slug: config.slug,
        });
      }

      const startHeight = container.offsetHeight;
      const endHeight = container.scrollHeight;
      container.style.maxHeight = startHeight + "px";
      container.classList.add("expanded");
      container.offsetHeight; // force reflow
      container.style.maxHeight = endHeight + "px";

      const onEnd = (e) => {
        if (e && (e.target !== container || e.propertyName !== "max-height")) return;
        container.removeEventListener("transitionend", onEnd);
        if (container.classList.contains("expanded")) {
          container.style.maxHeight = "none";
        }
      };
      container.addEventListener("transitionend", onEnd);
      setTimeout(onEnd, 450);
    } else {
      const startHeight = container.offsetHeight;
      container.style.maxHeight = startHeight + "px";
      container.classList.remove("expanded");
      container.offsetHeight; // force reflow
      container.style.maxHeight = "";

      const box = container.closest(".narrative-box");
      if (box && box.getBoundingClientRect().top < 80) {
        box.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    }
  };

  const container = document.getElementById("narrativeCollapsible");
  const content = document.getElementById("narrativeContent");
  const toggleWrap = document.getElementById("narrativeToggleWrap");
  const fade = document.getElementById("narrativeFade");
  if (content && container) {
    const isDesktopSplit = container.closest(".hero-split-container") && window.innerWidth > 860;
    const threshold = isDesktopSplit ? 530 : 180;
    if (content.scrollHeight <= threshold + 25) {
      container.classList.add("expanded");
      if (fade) fade.style.display = "none";
      if (toggleWrap) toggleWrap.style.display = "none";
    }
  }

  const heroVideo = document.querySelector(".hero-portrait-player, .video-actual-player");
  heroVideo?.addEventListener("play", () => {
    if (typeof gtag !== "function") return;
    gtag("event", "play_hero_video", {
      project_title: config.title,
      project_slug: config.slug,
      video_url: heroVideo.currentSrc || "",
    });
  });
})();
