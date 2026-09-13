(() => {
  const config = window.buildPageConfig;
  if (!config || config.type !== "major") return;

  window.toggleNarrative = () => {
    const container = document.getElementById("narrativeCollapsible");
    const text = document.getElementById("narrativeToggleText");
    const icon = document.getElementById("narrativeToggleIcon");
    if (!container) return;

    const isExpanded = container.classList.toggle("expanded");
    if (text) text.textContent = isExpanded ? "Collapse story" : "Read full story";
    if (icon) icon.style.transform = isExpanded ? "rotate(180deg)" : "rotate(0deg)";

    if (isExpanded && typeof gtag === "function") {
      gtag("event", "read_story", {
        project_title: config.title,
        project_slug: config.slug,
      });
    }

    if (!isExpanded) {
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
