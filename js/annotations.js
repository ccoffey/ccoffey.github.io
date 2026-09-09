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
  let drag = null;
  let suppressClickUntil = 0;
  let selectedIndex = null;

  const el = (name, attrs = {}, text = '') => {
    const node = document.createElementNS(NS, name);
    Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, value));
    if (text) node.textContent = text;
    return node;
  };
  function wrapText(text, maxChars) {
    const words = String(text || '').trim().split(/\s+/).filter(Boolean);
    const result = [];
    let line = '';
    words.forEach(word => {
      const next = line ? `${line} ${word}` : word;
      if (line && next.length > maxChars) {
        result.push(line);
        line = word;
      } else {
        line = next;
      }
    });
    if (line) result.push(line);
    return result.length ? result : [''];
  }

  function currentAnnotations() {
    if (!currentItem) return [];
    if (!Array.isArray(store[currentItem.filename])) store[currentItem.filename] = currentItem.annotations || [];
    return store[currentItem.filename];
  }

  function appendText(group, x, y, text, { className = 'annotation-label', fontSize = 26, lineHeight = 32, maxChars = 24 } = {}) {
    const label = el('text', { x, y, class: className, 'font-size': fontSize });
    const lines = wrapText(text, maxChars);
    lines.forEach((line, index) => label.append(el('tspan', { x, dy: index ? lineHeight : 0 }, line)));
    group.append(label);
    return lines.length;
  }

  function addHandle(group, x, y, handle) {
    group.append(el('circle', {
      class: 'annotation-handle', cx: x, cy: y, r: 14,
      'data-handle': handle
    }));
  }

  function clampBox(box, x, y) {
    return {
      x: Math.max(0, Math.min(1000 - box.w, x)),
      y: Math.max(0, Math.min(1000 - box.h, y))
    };
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
      const selected = editable && index === selectedIndex;
      const group = el('g', { 'data-index': index, class: `annotation-hit${selected ? ' is-selected' : ''}${annotation.type === 'text' ? ' annotation-text' : ''}` });
      if (annotation.type === 'callout') {
        const box = annotation.box || { x: 100, y: 100, w: 330, h: 150 };
        const fontSize = 24;
        const lineHeight = 31;
        const maxChars = Math.max(12, Math.floor((box.w - 56) / (fontSize * 0.58)));
        const lineCount = wrapText(annotation.text, maxChars).length;
        const height = Math.max(box.h, 58 + lineCount * lineHeight);
        group.append(el('line', { class: 'annotation-arrow', x1: annotation.target.x, y1: annotation.target.y, x2: box.x + box.w / 2, y2: box.y + height, 'marker-end': 'url(#annotation-arrowhead)' }));
        group.append(el('rect', { class: 'annotation-callout', x: box.x, y: box.y, width: box.w, height, rx: 42 }));
        appendText(group, box.x + 28, box.y + 39, annotation.text, { fontSize, lineHeight, maxChars });
        if (selected) {
          addHandle(group, annotation.target.x, annotation.target.y, 'callout-target');
          addHandle(group, box.x + box.w / 2, box.y + height / 2, 'callout-box');
        }
      } else if (annotation.type === 'arrow') {
        group.append(el('line', { class: 'annotation-arrow', x1: annotation.from.x, y1: annotation.from.y, x2: annotation.target.x, y2: annotation.target.y, 'marker-end': 'url(#annotation-arrowhead)' }));
        if (selected) {
          addHandle(group, annotation.from.x, annotation.from.y, 'arrow-start');
          addHandle(group, annotation.target.x, annotation.target.y, 'arrow-end');
        }
      } else if (annotation.type === 'text') {
        appendText(group, annotation.x, annotation.y, annotation.text, { fontSize: 24, lineHeight: 30, maxChars: 26 });
      } else {
        const point = annotation.target || annotation;
        group.append(el('circle', { class: 'annotation-marker', cx: point.x, cy: point.y, r: 28 }));
        group.append(el('text', { class: 'annotation-marker-text', x: point.x, y: point.y }, index + 1));
        group.append(el('title', {}, annotation.text || 'Annotation'));
        if (selected) addHandle(group, point.x, point.y, 'marker-position');
      }
      svg.append(group);
    });
    const hasAnnotations = annotations.length > 0;
    toggle.style.display = (hasAnnotations || editable) && currentItem?.type !== 'video' ? 'flex' : 'none';
    toggle.innerHTML = visible ? '◉' : '◌';
    toggle.setAttribute('aria-label', visible ? 'Hide annotations' : `Show ${annotations.length} annotations`);
    toggle.setAttribute('aria-pressed', String(visible));
    // SVG elements do not reliably reflect the HTML `hidden` property.
    // Toggle the attribute directly so a visible overlay is not left with
    // CSS `display: none` after rendering.
    svg.toggleAttribute('hidden', !visible);
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
    const countBefore = annotations.length;
    if (tool === 'marker') {
      const text = prompt('Annotation text:', 'New annotation');
      if (text) annotations.push({ type: 'marker', ...point, text });
    } else if (tool === 'text') {
      const text = prompt('Text:', 'New annotation');
      if (text) annotations.push({ type: 'text', ...point, text });
    } else if (tool === 'arrow' || tool === 'callout') {
      if (!pendingPoint) { pendingPoint = point; return; }
      if (tool === 'arrow') {
        annotations.push({ type: 'arrow', from: pendingPoint, target: point });
      } else if (tool === 'callout') {
        const text = prompt('Callout text:', 'New annotation');
        if (text) annotations.push({ type: 'callout', target: pendingPoint, box: { x: point.x, y: point.y, w: 360, h: 160 }, text });
      }
      pendingPoint = null;
    }
    if (annotations.length > countBefore) selectedIndex = annotations.length - 1;
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
    toolbar.innerHTML = '<strong>Annotate</strong><button data-tool="select">Select</button><button data-tool="text">Text</button><button data-tool="marker">Marker</button><button data-tool="arrow">Arrow</button><button data-tool="callout">Callout</button><button data-export="true">Export JSON</button>';
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
      if (Date.now() < suppressClickUntil) return;
      const existing = event.target.closest('[data-index]');
      if (tool === 'select' && existing) {
        selectedIndex = Number(existing.dataset.index);
        render();
        return;
      }
      if (tool !== 'select') addAt(pointFromEvent(event));
    });

    svg.addEventListener('pointerdown', event => {
      if (!currentItem || tool !== 'select') return;
      const handle = event.target.closest('[data-handle]');
      const group = event.target.closest('[data-index]');
      if (!group) return;
      const annotation = currentAnnotations()[Number(group.dataset.index)];
      if (!annotation) return;
      if (annotation.type === 'text' && !handle) {
        selectedIndex = Number(group.dataset.index);
        drag = { annotation, kind: 'text-position', pointerId: event.pointerId };
      } else if (handle) {
        drag = { annotation, kind: handle.dataset.handle, pointerId: event.pointerId };
      } else {
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      svg.setPointerCapture(event.pointerId);
    });

    svg.addEventListener('pointermove', event => {
      if (!drag || event.pointerId !== drag.pointerId) return;
      const point = pointFromEvent(event);
      if (drag.kind === 'arrow-start') drag.annotation.from = point;
      if (drag.kind === 'arrow-end') drag.annotation.target = point;
      if (drag.kind === 'text-position') Object.assign(drag.annotation, point);
      if (drag.kind === 'callout-target') drag.annotation.target = point;
      if (drag.kind === 'callout-box') {
        const box = drag.annotation.box;
        Object.assign(box, clampBox(box, point.x - box.w / 2, point.y - box.h / 2));
      }
      if (drag.kind === 'marker-position') {
        if (drag.annotation.target) drag.annotation.target = point;
        else Object.assign(drag.annotation, point);
      }
      suppressClickUntil = Date.now() + 250;
      render();
    });

    const stopDragging = event => {
      if (!drag || event.pointerId !== drag.pointerId) return;
      if (svg.hasPointerCapture(event.pointerId)) svg.releasePointerCapture(event.pointerId);
      drag = null;
    };
    svg.addEventListener('pointerup', stopDragging);
    svg.addEventListener('pointercancel', stopDragging);

    svg.addEventListener('dblclick', event => {
      const group = event.target.closest('[data-index]');
      if (!group) return;
      const annotation = currentAnnotations()[Number(group.dataset.index)];
      if (!annotation || !('text' in annotation)) return;
      event.preventDefault();
      event.stopPropagation();
      const text = prompt('Annotation text:', annotation.text);
      if (text !== null) annotation.text = text;
      selectedIndex = Number(group.dataset.index);
      render();
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
    selectedIndex = null;
    visible = item?.type !== 'video' && currentAnnotations().length > 0;
    render();
  };
})();
