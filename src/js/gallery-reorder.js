(() => {
  const statusEndpoint = "/__admin/gallery/status";
  const saveEndpoint = "/__admin/gallery-order";
  const deleteEndpoint = "/__admin/gallery/delete";
  const uploadEndpoint = "/__admin/gallery/upload";
  const trashSvg = (s) =>
    `<svg width="${s}" height="${s}" viewBox="0 0 24 24"><path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M10 11v6M14 11v6"/></svg>`;
  let enabled = false;

  function showStatus(msg, isError = false) {
    let s = document.getElementById("galleryReorderStatus");
    if (!s) {
      s = document.createElement("span");
      s.id = "galleryReorderStatus";
      s.className = "gallery-reorder-status";
      document.querySelector(".gallery-header")?.append(s);
    }
    if (s) {
      s.textContent = msg;
      s.hidden = !msg;
      s.classList.toggle("is-error", isError);
    }
  }

  async function postJson(url, data) {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    const result = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(result.error || `Server error (${res.status})`);
    return result;
  }

  async function saveOrder(slug, order, prev, grid) {
    showStatus("Saving gallery order…");
    try {
      await postJson(saveEndpoint, { slug, order });
      showStatus("Saved locally");
      setTimeout(() => showStatus(""), 2500);
      return true;
    } catch (err) {
      showStatus(err.message || "Could not save gallery order", true);
      if (prev && grid) {
        const map = new Map([...grid.querySelectorAll(".photo-card")].map((c) => [c.dataset.filename, c]));
        prev.forEach((fn) => {
          const c = map.get(fn);
          if (c) grid.appendChild(c);
        });
        window.updateGalleryOrder?.(prev);
      }
      return false;
    }
  }

  async function deletePhoto(filename) {
    const slug = window.buildPageConfig?.slug;
    if (!filename || !slug || !window.confirm(`Permanently delete "${filename}" from this build project?`)) return false;

    showStatus(`Deleting ${filename}…`);
    try {
      await postJson(deleteEndpoint, { slug, filename });
      window.galleryCommentAdmin?.removePhoto?.(filename);
      document.querySelector(`.photo-grid .photo-card[data-filename="${CSS.escape(filename)}"]`)?.remove();
      showStatus("Photo deleted locally");
      setTimeout(() => showStatus(""), 2500);
      return true;
    } catch (err) {
      showStatus(err.message || "Could not delete photo", true);
      return false;
    }
  }

  function setupUpload() {
    const header = document.querySelector(".gallery-header");
    if (!header || document.getElementById("galleryUploadBtn")) return;

    const label = document.createElement("label");
    label.id = "galleryUploadBtn";
    label.className = "gallery-upload-btn";
    label.title = "Upload photo or video to gallery";
    label.innerHTML = '<svg width="15" height="15" viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12"/></svg><span>Upload</span><input type="file" id="galleryFileInput" accept="image/*,video/*" multiple hidden>';

    const input = label.querySelector("input");
    input.addEventListener("change", async (e) => {
      const files = [...(e.target.files || [])];
      const slug = window.buildPageConfig?.slug;
      if (!files.length || !slug) return;
      input.value = "";

      let count = 0;
      for (let i = 0; i < files.length; i++) {
        const file = files[i];
        showStatus(`Uploading ${i + 1} of ${files.length}: ${file.name}…`);
        try {
          const res = await fetch(uploadEndpoint, {
            method: "POST",
            headers: {
              "Content-Type": file.type || "application/octet-stream",
              "X-Build-Slug": slug,
              "X-File-Name": file.name,
            },
            body: file,
          });
          const result = await res.json().catch(() => ({}));
          if (!res.ok) throw new Error(result.error || `Upload failed for ${file.name}`);
          count++;
        } catch (err) {
          showStatus(err.message || `Failed to upload ${file.name}`, true);
          return;
        }
      }
      showStatus(`Uploaded ${count} item(s). Updating gallery…`);
      window.location.reload();
    });

    header.appendChild(label);
  }

  function setupLightboxDelete() {
    const lightbox = document.getElementById("lightbox");
    if (!lightbox || document.getElementById("lightboxDeleteBtn")) return;

    const btn = document.createElement("button");
    btn.id = "lightboxDeleteBtn";
    btn.className = "lightbox-btn lightbox-delete";
    btn.type = "button";
    btn.setAttribute("aria-label", "Delete photo");
    btn.dataset.tooltip = "Delete photo";
    btn.innerHTML = trashSvg(20);

    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      const currentItem = window.galleryCommentAdmin?.currentItem();
      if (!currentItem) return;
      btn.disabled = true;
      try {
        await deletePhoto(currentItem.filename);
      } finally {
        btn.disabled = false;
      }
    });

    const closeBtn = document.getElementById("lightboxCloseBtn");
    if (closeBtn) closeBtn.before(btn);
    else lightbox.appendChild(btn);
  }

  function setupCardDelete(card) {
    if (card.querySelector(".photo-card-delete")) return;

    const btn = document.createElement("span");
    btn.className = "photo-card-delete";
    btn.setAttribute("role", "button");
    btn.setAttribute("tabindex", "0");
    btn.setAttribute("aria-label", "Delete photo");
    btn.title = "Delete photo";
    btn.innerHTML = trashSvg(14);

    const trigger = (e) => {
      e.preventDefault();
      e.stopPropagation();
      deletePhoto(card.dataset.filename);
    };

    btn.addEventListener("click", trigger);
    btn.addEventListener("keydown", (e) => (e.key === "Enter" || e.key === " ") && trigger(e));
    btn.addEventListener("mousedown", (e) => e.stopPropagation());

    card.appendChild(btn);
  }

  function setupReordering() {
    const grid = document.querySelector(".photo-grid");
    const slug = window.buildPageConfig?.slug;
    if (!grid || !slug) return;

    setupUpload();
    setupLightboxDelete();

    grid.classList.add("is-reorderable");
    let draggedCard = null;
    let initialOrder = [...grid.querySelectorAll(".photo-card")].map((c) => c.dataset.filename);

    grid.querySelectorAll(".photo-card").forEach((card) => {
      setupCardDelete(card);
      card.setAttribute("draggable", "true");
      card.addEventListener("dragstart", (e) => {
        draggedCard = card;
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/plain", card.dataset.filename || "");
        setTimeout(() => {
          if (draggedCard === card) card.classList.add("is-dragging");
        }, 0);
      });

      card.addEventListener("dragend", async () => {
        card.classList.remove("is-dragging");
        draggedCard = null;

        const currentCards = [...grid.querySelectorAll(".photo-card")];
        const newOrder = currentCards.map((c) => c.dataset.filename);
        const changed = newOrder.length === initialOrder.length && newOrder.some((fn, i) => fn !== initialOrder[i]);

        if (changed) {
          const previousOrder = [...initialOrder];
          initialOrder = [...newOrder];

          if (typeof window.updateGalleryOrder === "function") {
            window.updateGalleryOrder(newOrder);
          } else if (Array.isArray(window.gallery)) {
            const map = new Map(window.gallery.map((it) => [it.filename, it]));
            const updated = newOrder.map((fn) => map.get(fn)).filter(Boolean);
            window.gallery.splice(0, window.gallery.length, ...updated);
          }

          currentCards.forEach((c) => {
            c.setAttribute("onclick", `openLightbox('${c.dataset.filename}')`);
          });

          const ok = await saveOrder(slug, newOrder, previousOrder, grid);
          if (!ok) initialOrder = previousOrder;
        }
      });
    });

    grid.addEventListener("dragover", (e) => {
      if (!draggedCard) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";

      const target = e.target.closest(".photo-card");
      if (target && target !== draggedCard && grid.contains(target)) {
        const rect = target.getBoundingClientRect();
        if (e.clientX < rect.left + rect.width / 2) {
          grid.insertBefore(draggedCard, target);
        } else {
          grid.insertBefore(draggedCard, target.nextSibling);
        }
      }
    });

    grid.addEventListener("drop", (e) => e.preventDefault());
  }

  window.localGalleryReorder = {
    isEnabled: () => enabled,
    init: setupReordering,
  };

  if (window.localCommentAdmin?.isEnabled()) {
    enabled = true;
    setupReordering();
  } else {
    fetch(statusEndpoint)
      .then((res) => (res.ok ? res.json() : null))
      .then((status) => {
        if (!status?.enabled) return;
        enabled = true;
        setupReordering();
      })
      .catch(() => {});
  }
})();
