(() => {
  const svg = document.getElementById('lightboxAnnotations');
  const toggle = document.getElementById('lightboxAnnotationsBtn');
  if (!svg || !toggle) return;

  const NS = 'http://www.w3.org/2000/svg';
  const editable = ['localhost', '127.0.0.1'].includes(location.hostname)
    && new URLSearchParams(location.search).has('annotate');
  const store = window.projectAnnotations || {};
  let currentItem = null;
  let visible = false;
  let tool = 'select';
  let pendingPoint = null;

  const el = (name, attrs = {}, text = '') => {
    const node = document.createElementNS(NS, name);
    Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, value));
    if (text) node.textContent = text;
    return node;
  };
  const id = () => `annotation-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  const lines = text => String(text || '').match(/.{1,28}(?:\s|$)|\S+/g) || [''];

  function currentAnnotations() {
    if (!currentItem) return [];
    if (!Array.isArray(store[currentItem.filename])) store[currentItem.filename] = currentItem.annotations || [];
    return store[currentItem.filename];
  }

  function appendText(group, x, y, text, className = 'annotation-label') {
    const label = el('text', { x, y, class: className });
    lines(text).forEach((line, index) => label.append(el('tspan', { x, dy: index ? 42 : 0 }, line)));
    group.append(label);
  }

  function render() {
    svg.replaceChildren();
    svg.setAttribute('viewBox', '0 0 1000 1000');
    svg.setAttribute('preserveAspectRatio', 'none');
    const annotations = currentAnnotations();
    const defs = el('defs');
    const marker = el('marker', { id: 'annotation-arrowhead', viewBox: '0 0 10 10', refX: '8', refY: '5', markerWidth: '8', markerHeight: '8', orient: 'auto' });
    marker.append(el('path', { d: 'M 0 0 L 10 5 L 0 10 z', fill: '#ff4d3d' }));
    defs.append(marker);
    svg.append(defs);

    annotations.forEach((annotation, index) => {
      const group = el('g', { 'data-id': annotation.id, class: 'annotation-hit' });
      if (annotation.type === 'highlight') {
        group.append(el('ellipse', { class: 'annotation-highlight', cx: annotation.x, cy: annotation.y, rx: annotation.rx, ry: annotation.ry }));
      } else if (annotation.type === 'callout') {
        const box = annotation.box || { x: 100, y: 100, w: 330, h: 150 };
        group.append(el('line', { class: 'annotation-arrow', x1: annotation.target.x, y1: annotation.target.y, x2: box.x + box.w / 2, y2: box.y + box.h, 'marker-end': 'url(#annotation-arrowhead)' }));
        group.append(el('rect', { class: 'annotation-callout', x: box.x, y: box.y, width: box.w, height: box.h, rx: 52 }));
        appendText(group, box.x + 34, box.y + 64, annotation.text);
      } else if (annotation.type === 'arrow') {
        group.append(el('line', { class: 'annotation-arrow', x1: annotation.from.x, y1: annotation.from.y, x2: annotation.target.x, y2: annotation.target.y, 'marker-end': 'url(#annotation-arrowhead)' }));
        appendText(group, annotation.from.x, annotation.from.y - 18, annotation.text);
      } else {
        const point = annotation.target || annotation;
        group.append(el('circle', { class: 'annotation-marker', cx: point.x, cy: point.y, r: 28 }));
        group.append(el('text', { class: 'annotation-marker-text', x: point.x, y: point.y }, index + 1));
        group.append(el('title', {}, annotation.text || 'Annotation'));
      }
      svg.append(group);
    });
    const hasAnnotations = annotations.length > 0;
    toggle.style.display = (hasAnnotations || editable) && currentItem?.type !== 'video' ? 'flex' : 'none';
    toggle.innerHTML = visible ? '◉' : '◌';
    toggle.setAttribute('aria-label', visible ? 'Hide annotations' : `Show ${annotations.length} annotations`);
    toggle.setAttribute('aria-pressed', String(visible));
    svg.hidden = !visible;
    svg.classList.toggle('is-visible', visible);
    svg.classList.toggle('is-editor', editable && visible);
    svg.setAttribute('aria-hidden', String(!visible));
  }

  function pointFromEvent(event) {
    const rect = svg.getBoundingClientRect();
    return {
      x: Math.max(0, Math.min(1000, Math.round((event.clientX - rect.left) * 1000 / rect.width))),
      y: Math.max(0, Math.min(1000, Math.round((event.clientY - rect.top) * 1000 / rect.height)))
    };
  }

  function addAt(point) {
    const annotations = currentAnnotations();
    if (tool === 'marker') {
      const text = prompt('Annotation text:', 'New annotation');
      if (text) annotations.push({ id: id(), type: 'marker', ...point, text });
    } else if (tool === 'arrow' || tool === 'callout' || tool === 'highlight') {
      if (!pendingPoint) { pendingPoint = point; return; }
      if (tool === 'arrow') {
        const text = prompt('Arrow label:', 'New annotation');
        if (text) annotations.push({ id: id(), type: 'arrow', from: pendingPoint, target: point, text });
      } else if (tool === 'callout') {
        const text = prompt('Callout text:', 'New annotation');
        if (text) annotations.push({ id: id(), type: 'callout', target: pendingPoint, box: { x: point.x, y: point.y, w: 330, h: 160 }, text });
      } else {
        annotations.push({ id: id(), type: 'highlight', x: (pendingPoint.x + point.x) / 2, y: (pendingPoint.y + point.y) / 2, rx: Math.max(24, Math.abs(pendingPoint.x - point.x) / 2), ry: Math.max(24, Math.abs(pendingPoint.y - point.y) / 2) });
      }
      pendingPoint = null;
    }
    render();
  }

  function exportJson() {
    const text = JSON.stringify({ version: 1, images: store }, null, 2) + '\n';
    navigator.clipboard?.writeText(text).catch(() => {});
    const link = document.createElement('a');
    link.href = URL.createObjectURL(new Blob([text], { type: 'application/json' }));
    link.download = 'annotations.json';
    link.click();
    URL.revokeObjectURL(link.href);
  }

  if (editable) {
    const toolbar = document.createElement('div');
    toolbar.className = 'annotation-editor-toolbar';
    toolbar.innerHTML = '<strong>Annotate</strong><button data-tool="select">Select</button><button data-tool="marker">Marker</button><button data-tool="arrow">Arrow</button><button data-tool="callout">Callout</button><button data-tool="highlight">Highlight</button><button data-export="true">Export JSON</button>';
    document.getElementById('lightbox').append(toolbar);
    toolbar.addEventListener('click', event => {
      const button = event.target.closest('button');
      if (!button) return;
      if (button.dataset.export) return exportJson();
      tool = button.dataset.tool;
      pendingPoint = null;
      toolbar.querySelectorAll('[data-tool]').forEach(item => item.classList.toggle('active', item.dataset.tool === tool));
    });
    svg.addEventListener('click', event => {
      if (!visible || !currentItem) return;
      event.stopPropagation();
      const existing = event.target.closest('[data-id]');
      if (tool === 'select' && existing) {
        const annotation = currentAnnotations().find(item => item.id === existing.dataset.id);
        if (annotation && 'text' in annotation) {
          const text = prompt('Annotation text:', annotation.text);
          if (text !== null) annotation.text = text;
          render();
        }
        return;
      }
      if (tool !== 'select') addAt(pointFromEvent(event));
    });
  }

  toggle.addEventListener('click', event => {
    event.stopPropagation();
    visible = !visible;
    render();
  });
  svg.addEventListener('click', event => {
    if (visible) event.stopPropagation();
  });
  window.updateLightboxAnnotations = item => {
    currentItem = item;
    pendingPoint = null;
    visible = item?.type !== 'video' && currentAnnotations().length > 0;
    render();
  };
})();
