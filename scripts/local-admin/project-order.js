(() => {
  document.querySelectorAll('[data-project-type]').forEach(grid => {
    let previous = [];
    let dragged = null;
    let saving = false;
    const cards = () => [...grid.querySelectorAll('[data-project-slug]')];
    const sequence = () => cards().map(card => card.dataset.projectSlug);
    const restore = order => {
      const bySlug = new Map(cards().map(card => [card.dataset.projectSlug, card]));
      order.forEach(slug => grid.append(bySlug.get(slug)));
    };
    const tools = document.createElement('p');
    tools.className = 'project-order-tools';
    tools.textContent = 'Drag cards to reorder, or focus a card and use Alt + arrow keys.';
    const status = document.createElement('span');
    status.className = 'project-order-status';
    status.setAttribute('role', 'status');
    status.setAttribute('aria-live', 'polite');
    tools.append(status);
    grid.before(tools);
    grid.classList.add('projects-reorderable');

    async function save(before) {
      const order = sequence();
      if (JSON.stringify(order) === JSON.stringify(before)) return;
      saving = true;
      grid.setAttribute('aria-busy', 'true');
      status.classList.remove('is-error');
      status.textContent = 'Saving…';
      try {
        const response = await fetch('/__admin/project-order', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ build_type: grid.dataset.projectType, order }),
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || 'Could not save project order.');
        status.textContent = 'Saved locally';
        // Keep this page’s dropdown menu in sync without a reload.
        const menuLinks = [...document.querySelectorAll('.nav-dropdown-item')]
          .filter(link => link.getAttribute('href')?.startsWith(`/${grid.dataset.projectType}/`));
        const parent = menuLinks[0]?.parentElement;
        if (parent) {
          const links = new Map(menuLinks.map(link => [link.getAttribute('href').split('/')[2], link]));
          order.forEach(slug => { if (links.has(slug)) parent.append(links.get(slug)); });
        }
      } catch (error) {
        restore(before);
        status.classList.add('is-error');
        status.textContent = error.message || 'Could not save project order.';
      } finally {
        saving = false;
        grid.removeAttribute('aria-busy');
      }
    }

    cards().forEach(card => {
      card.draggable = true;
      card.querySelectorAll('img').forEach(img => { img.draggable = false; });
      card.addEventListener('dragstart', event => {
        if (saving) { event.preventDefault(); return; }
        previous = sequence();
        dragged = card;
        event.dataTransfer.effectAllowed = 'move';
        event.dataTransfer.setData('text/plain', card.dataset.projectSlug);
        card.classList.add('project-dragging');
      });
      card.addEventListener('dragend', () => {
        if (dragged) restore(previous); // Cancelled or dropped outside this section.
        dragged = null;
        card.classList.remove('project-dragging');
      });
      card.addEventListener('keydown', event => {
        if (!event.altKey || !['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(event.key)) return;
        event.preventDefault();
        if (saving) return;
        const before = sequence();
        const backwards = ['ArrowUp', 'ArrowLeft'].includes(event.key);
        const neighbor = backwards ? card.previousElementSibling : card.nextElementSibling;
        if (!neighbor) return;
        if (backwards) grid.insertBefore(card, neighbor);
        else grid.insertBefore(neighbor, card);
        card.focus();
        void save(before);
      });
    });
    grid.addEventListener('dragover', event => {
      if (!dragged || saving) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = 'move';
      const target = event.target.closest('[data-project-slug]');
      if (!target || target === dragged || target.parentElement !== grid) return;
      const box = target.getBoundingClientRect();
      const draggedBox = dragged.getBoundingClientRect();
      const sameRow = Math.abs(box.top - draggedBox.top) < 10;
      const after = sameRow ? event.clientX >= box.left + box.width / 2
        : event.clientY >= box.top + box.height / 2;
      grid.insertBefore(dragged, after ? target.nextElementSibling : target);
    });
    grid.addEventListener('drop', event => {
      if (!dragged || saving) return;
      event.preventDefault();
      const before = previous;
      dragged.classList.remove('project-dragging');
      dragged = null;
      void save(before);
    });
  });
})();
