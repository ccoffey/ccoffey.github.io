(() => {
  const statusEndpoint = "/__admin/comments/status";
  const saveEndpoint = "/__admin/comments";
  let enabled = false;
  let saveTimer;
  const savedCommentsByMedia = new Map();

  const hooks = () => window.galleryCommentAdmin;

  let pickerPromise = null;
  let pickerInstance = null;
  let activeTextTarget = null;

  async function getPicker() {
    if (!pickerPromise) {
      pickerPromise = import("/__admin/emoji-button.js").then(({ EmojiButton }) => {
        pickerInstance = new EmojiButton({
          showSearch: false,
          showRecents: false,
          theme: "dark",
          style: "native",
          showPreview: false,
          position: "top-end",
          zIndex: 1040,
        });
        pickerInstance.on("emoji", (selection) => {
          if (activeTextTarget) {
            insertEmoji(activeTextTarget, selection.emoji);
          }
        });
        return pickerInstance;
      });
    }
    return pickerPromise;
  }

  document.addEventListener(
    "keydown",
    (event) => {
      if (pickerInstance && pickerInstance.isPickerVisible()) {
        if (event.key === "Escape") {
          event.preventDefault();
          event.stopPropagation();
          event.stopImmediatePropagation();
          pickerInstance.hidePicker();
          activeTextTarget?.focus();
          return;
        }
        if ((event.altKey || event.ctrlKey) && (event.key === "e" || event.key === "E")) {
          event.preventDefault();
          event.stopPropagation();
          event.stopImmediatePropagation();
          pickerInstance.hidePicker();
          activeTextTarget?.focus();
          return;
        }
        const pickerEl = document.querySelector(".emoji-picker");
        if (pickerEl && (pickerEl.contains(event.target) || event.target.closest?.(".emoji-picker"))) {
          if (["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "z", "Z", "f", "F"].includes(event.key)) {
            event.stopPropagation();
            event.stopImmediatePropagation();
          }
        }
      }
    },
    true
  );

  document.addEventListener(
    "click",
    (event) => {
      if (pickerInstance && pickerInstance.isPickerVisible()) {
        const pickerEl = document.querySelector(".emoji-picker");
        if (pickerEl && !pickerEl.contains(event.target) && !event.target.closest?.(".lightbox-comment-emoji-btn")) {
          if (event.target.classList.contains("lightbox-backdrop") || event.target.id === "lightbox") {
            event.preventDefault();
            event.stopPropagation();
            event.stopImmediatePropagation();
            pickerInstance.hidePicker();
          }
        }
      }
    },
    true
  );

  function insertEmoji(targetText, emoji) {
    targetText.focus();
    const sel = window.getSelection();
    let inserted = false;
    if (sel && sel.rangeCount > 0) {
      const range = sel.getRangeAt(0);
      if (targetText.contains(range.commonAncestorContainer)) {
        range.deleteContents();
        const node = document.createTextNode(emoji);
        range.insertNode(node);
        range.setStartAfter(node);
        range.setEndAfter(node);
        sel.removeAllRanges();
        sel.addRange(range);
        inserted = true;
      }
    }
    if (!inserted) {
      const node = document.createTextNode(emoji);
      targetText.append(node);
      const range = document.createRange();
      range.setStartAfter(node);
      range.setEndAfter(node);
      sel?.removeAllRanges();
      sel?.addRange(range);
    }
    targetText.dataset.commentSource = targetText.textContent;
    targetText.dispatchEvent(new Event("input", { bubbles: true }));
  }

  function createEmojiButton(row, targetText, label) {
    const btn = document.createElement("button");
    btn.className = "lightbox-comment-emoji-btn";
    btn.type = "button";
    btn.setAttribute("aria-label", label);
    btn.dataset.tooltip = "Add emoji";
    btn.innerHTML =
      '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"></circle><path d="M8 14s1.5 2 4 2 4-2 4-2"></path><line x1="9" y1="9" x2="9.01" y2="9"></line><line x1="15" y1="9" x2="15.01" y2="9"></line></svg>';
    btn.addEventListener("mousedown", (event) => event.preventDefault());
    btn.addEventListener("click", async (event) => {
      event.stopPropagation();
      activeTextTarget = targetText;
      const picker = await getPicker();
      picker.togglePicker(btn);
    });
    return btn;
  }

  function commentsFrom(container) {
    return [...container.querySelectorAll(".lightbox-comment-text[data-comment-index]")]
      .map((c) => (c.dataset.commentSource ?? c.textContent).trim())
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
    const row = document.createElement("div");
    row.className = "lightbox-comment-editor-row lightbox-comment-composer-row";

    const composer = document.createElement("p");
    composer.className = "lightbox-comment-text lightbox-comment-composer";
    composer.contentEditable = "true";
    composer.dataset.placeholder = "Write a comment…";
    composer.setAttribute("aria-label", "New comment");

    const emojiBtn = createEmojiButton(row, composer, "Add emoji");

    const submit = () => {
      const comment = composer.textContent.trim();
      if (!comment) return;
      const item = hooks()?.currentItem();
      if (!item) return;
      pickerPromise?.then((p) => p.hidePicker());
      item.comments = [...item.comments, comment];
      hooks().rerender();
      document.querySelector("#lightbox-description .lightbox-comment-composer")?.focus();
      save(document.getElementById("lightbox-description"), item.comments);
    };

    composer.addEventListener("input", () => {
      if (!composer.textContent.trim()) composer.replaceChildren();
    });

    composer.addEventListener("keydown", async (event) => {
      if ((event.altKey || event.ctrlKey) && (event.key === "e" || event.key === "E")) {
        event.preventDefault();
        activeTextTarget = composer;
        const picker = await getPicker();
        picker.togglePicker(emojiBtn);
        return;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        pickerPromise?.then((p) => p.hidePicker());
        composer.blur();
        return;
      }
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        pickerPromise?.then((p) => p.hidePicker());
        submit();
      }
    });

    row.append(composer, emojiBtn);
    stack.append(row);
  }

  function decorate(container) {
    if (!enabled) return;
    pickerPromise?.then((p) => p.hidePicker());
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

      const row = document.createElement("div");
      row.className = "lightbox-comment-editor-row";

      const remove = document.createElement("button");
      remove.className = "lightbox-comment-delete";
      remove.type = "button";
      remove.setAttribute("aria-label", `Delete comment ${index + 1}`);
      remove.addEventListener("mousedown", (event) => event.preventDefault());
      remove.addEventListener("click", () => {
        pickerPromise?.then((p) => p.hidePicker());
        const current = hooks()?.currentItem();
        if (!current) return;
        current.comments.splice(index, 1);
        hooks().rerender();
        document.querySelector("#lightbox-description .lightbox-comment-composer")?.focus();
        save(document.getElementById("lightbox-description"), current.comments);
      });

      const emojiBtn = createEmojiButton(row, text, "Add emoji");

      text.addEventListener("focus", () => {
        if (text.querySelector("a")) text.textContent = text.dataset.commentSource;
      });
      text.addEventListener("input", () => {
        text.dataset.commentSource = text.textContent;
        scheduleSave(container);
      });
      text.addEventListener("blur", () => {
        if (pickerInstance && pickerInstance.isPickerVisible() && activeTextTarget === text) {
          return;
        }
        text.dataset.commentSource = text.textContent;
        save(container);
        hooks()?.renderText(text, text.dataset.commentSource);
      });
      text.addEventListener("keydown", async (event) => {
        if ((event.altKey || event.ctrlKey) && (event.key === "e" || event.key === "E")) {
          event.preventDefault();
          activeTextTarget = text;
          const picker = await getPicker();
          picker.togglePicker(emojiBtn);
          return;
        }
        if (event.key === "Escape") {
          event.preventDefault();
          pickerPromise?.then((p) => p.hidePicker());
          text.blur();
          return;
        }
        if (event.key === "Enter" && !event.shiftKey) {
          event.preventDefault();
          pickerPromise?.then((p) => p.hidePicker());
          text.blur();
        }
      });

      text.before(row);
      row.append(text, remove, emojiBtn);
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
