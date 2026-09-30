(() => {
  const statusEndpoint = "/__admin/comments/status";
  const saveEndpoint = "/__admin/comments";
  let enabled = false;
  let saveTimer;
  const savedCommentsByMedia = new Map();

  const hooks = () => window.galleryCommentAdmin;

  function commentsFrom(container) {
    return [...container.querySelectorAll(".lightbox-comment-text[data-comment-index]")]
      .map((c) => c.textContent.trim())
      .filter(Boolean);
  }

  function mediaKey(item) {
    return `${hooks()?.slug || ""}/${item.filename}`;
  }

  function rememberSavedComments(item) {
    const key = mediaKey(item);
    if (!savedCommentsByMedia.has(key)) savedCommentsByMedia.set(key, [...item.comments]);
    return key;
  }

  function setSaveStatus(container, message = "", isError = false) {
    const status = container?.querySelector(".lightbox-comment-save-status");
    if (!status) return;
    status.hidden = !message;
    status.textContent = message;
    status.classList.toggle("is-error", isError);
  }

  async function save(container, comments = commentsFrom(container)) {
    const galleryHooks = hooks();
    const item = galleryHooks?.currentItem();
    if (!item) return;

    const key = rememberSavedComments(item);
    item.comments = comments;
    setSaveStatus(container, "Saving comment…");
    try {
      const response = await fetch(saveEndpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ slug: galleryHooks.slug, filename: item.filename, comments }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Could not save comment.");
      item.comments = result.comments;
      savedCommentsByMedia.set(key, [...result.comments]);
      setSaveStatus(container, "Saved locally");
    } catch (error) {
      item.comments = [...(savedCommentsByMedia.get(key) || [])];
      galleryHooks.rerender();
      setSaveStatus(document.getElementById("lightbox-description"), error.message || "Could not save comment.", true);
    }
  }

  function scheduleSave(container) {
    window.clearTimeout(saveTimer);
    saveTimer = window.setTimeout(() => save(container), 450);
  }

  function addComposer(stack) {
    const composer = document.createElement("p");
    composer.className = "lightbox-comment-text lightbox-comment-composer";
    composer.contentEditable = "true";
    composer.dataset.placeholder = "Write a comment…";
    composer.setAttribute("aria-label", "New comment");
    const submit = () => {
      const comment = composer.textContent.trim();
      if (!comment) return;
      const item = hooks()?.currentItem();
      if (!item) return;
      item.comments = [...item.comments, comment];
      hooks().rerender();
      document.querySelector("#lightbox-description .lightbox-comment-composer")?.focus();
      save(document.getElementById("lightbox-description"), item.comments);
    };
    composer.addEventListener("input", () => {
      if (!composer.textContent.trim()) composer.replaceChildren();
    });
    composer.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        submit();
      }
    });
    stack.append(composer);
  }

  function decorate(container) {
    if (!enabled) return;
    const stack = container.querySelector(".lightbox-comment-stack");
    if (!stack) return;
    const item = hooks()?.currentItem();
    if (item) rememberSavedComments(item);

    stack.querySelectorAll(".lightbox-comment-text").forEach((text, index) => {
      text.dataset.commentIndex = String(index);
      text.contentEditable = "true";
      text.spellcheck = true;
      text.classList.add("is-editable");
      text.setAttribute("aria-label", `Comment ${index + 1}`);
      text.addEventListener("input", () => scheduleSave(container));
      text.addEventListener("blur", () => save(container));
      text.addEventListener("keydown", (event) => {
        if (event.key === "Enter" && !event.shiftKey) {
          event.preventDefault();
          text.blur();
        }
      });

      const row = document.createElement("div");
      row.className = "lightbox-comment-editor-row";
      const remove = document.createElement("button");
      remove.className = "lightbox-comment-delete";
      remove.type = "button";
      remove.setAttribute("aria-label", `Delete comment ${index + 1}`);
      remove.addEventListener("mousedown", (event) => event.preventDefault());
      remove.addEventListener("click", () => {
        const current = hooks()?.currentItem();
        if (!current) return;
        current.comments.splice(index, 1);
        hooks().rerender();
        document.querySelector("#lightbox-description .lightbox-comment-composer")?.focus();
        save(document.getElementById("lightbox-description"), current.comments);
      });
      text.before(row);
      row.append(text, remove);
    });

    addComposer(stack);

    const status = document.createElement("p");
    status.className = "lightbox-comment-save-status";
    status.setAttribute("role", "status");
    status.hidden = true;
    container.append(status);
  }

  window.localCommentAdmin = {
    isEnabled: () => enabled,
    decorate,
  };

  fetch(statusEndpoint)
    .then((res) => (res.ok ? res.json() : null))
    .then((status) => {
      if (!status?.enabled) return;
      enabled = true;
      hooks()?.rerender();
      if (!document.querySelector('script[src*="gallery-reorder.js"]')) {
        const s = document.createElement("script");
        s.src = "/js/gallery-reorder.js";
        document.body.append(s);
      }
    })
    .catch(() => {});
})();
