'use strict';

// Source page numbers are stable edit identities. Every visible page position,
// range and destination is expressed in the current output order instead.
window.pdfOrganizer = (() => {
  const entries = new Map(), outputs = new Map();
  const readers = {preview: new Set(), thumbnail: new Set(), navigation: new Set()};
  const PAGE_GROUP = 24;
  let mode = 'read', epoch = 0, previewSequence = 0, thumbnailSequence = 0,
    navigationSequence = 0, outputView = null, previewWidth = 595, dragging = null;

  function abortReads(kind) {
    for (const group of kind ? [readers[kind]] : Object.values(readers)) {
      for (const controller of group) controller.abort();
      group.clear();
    }
  }
  async function readApi(kind, route, payload) {
    const controller = new AbortController(); readers[kind].add(controller);
    try { return await api(route, payload, {signal: controller.signal}); }
    finally { readers[kind].delete(controller); }
  }

  function entryFor(id = state.current) {
    if (!id) return null;
    if (!entries.has(id)) entries.set(id, {id, draft: null, selected: new Set(), anchor: null,
      activeSource: null, shown: PAGE_GROUP, pending: 0, queue: Promise.resolve(),
      opening: false, invalid: false, unknown: null, message: '', messageError: false,
      outputId: null, lastJob: null, syncedJob: null, savePending: false});
    return entries.get(id);
  }
  const currentEntry = () => entryFor();
  const isCurrent = entry => entry && entry.id === state.current;
  const isEditable = entry => !!entry?.draft && !entry.invalid && entry.draft.eligibility === 'ELIGIBLE';
  const isSaving = entry => entry?.savePending || entry?.draft?.saving ||
    (entry?.lastJob && running(entry.lastJob) && entry.lastJob.id === entry.draft?.save_job_id);
  const isBusy = entry => !entry || entry.opening || entry.pending > 0 || entry.savePending ||
    entry.unknown || entry.draft?.saving || (entry.lastJob && running(entry.lastJob) &&
      entry.lastJob.id === entry.draft?.save_job_id);
  const count = () => mode === 'saved' ? (outputView?.count || 0) : (currentEntry()?.draft?.order.length || 0);
  function position() {
    return mode === 'saved' ? (outputView?.page || 1)
      : Math.max(1, (currentEntry()?.draft?.order.indexOf(currentEntry()?.activeSource) ?? 0) + 1);
  }
  function message(entry, text, error = false) {
    if (entry) { entry.message = text; entry.messageError = error; }
    if (!entry || isCurrent(entry)) {
      $('organizer-message').textContent = text;
      $('organizer-message').classList.toggle('error', error);
      $('organizer-message').hidden = !text;
    }
  }
  function blockedText(entry) {
    return (entry?.draft?.blockers || []).map(code => blockers[code] || code).join('；');
  }
  function retrySave(entry) {
    return entry?.lastJob && entry.lastJob.revision === entry.draft?.revision &&
      ['ERROR', 'CANCELLED', 'COMPLETED_WITH_ERRORS'].includes(entry.lastJob.status) &&
      !(entry.lastJob.results || []).some(row => row.status === 'VERIFIED_COPY');
  }
  function restoreIdentity() {
    if (mode === 'saved' && outputView?.sha && !outputView.invalid) $('identity').textContent = '已保存副本 SHA-256：' + outputView.sha;
    else if (mode === 'edit' && currentEntry()?.draft && !currentEntry().invalid)
      $('identity').textContent = '草稿基于原件 SHA-256：' + currentEntry().draft.source_sha256;
  }
  function refreshControls() {
    const entry = currentEntry(), draft = entry?.draft, ready = isEditable(entry) && !isBusy(entry),
      editing = mode === 'edit', selected = entry?.selected.size || 0;
    $('mode-organize').disabled = !state.current;
    $('mode-saved').disabled = !entry?.outputId;
    for (const [name, value] of [['read', 'read'], ['organize', 'edit'], ['saved', 'saved']]) {
      $('mode-' + name).classList.toggle('active', mode === value);
      $('mode-' + name).setAttribute('aria-pressed', String(mode === value));
    }
    const retained = !!draft && (entry.invalid || draft.has_changes || draft.can_undo || draft.can_redo);
    $('document-draft-badge').hidden = !retained;
    $('document-draft-badge').textContent = entry?.invalid ? '草稿已失效'
      : draft?.dirty && draft?.has_changes ? '有未保存草稿' : '草稿已保留';
    $('organizer-edit-tools').hidden = !editing;
    document.querySelector('.organizer-history-actions').hidden = !editing;
    $('organizer-save').hidden = !editing;
    $('organizer-undo').disabled = !ready || !draft?.can_undo;
    $('organizer-redo').disabled = !ready || !draft?.can_redo;
    $('organizer-reset').disabled = !ready || !draft?.has_changes;
    for (const id of ['range', 'select-range', 'select-all', 'clear-selection', 'move-position'])
      $('organizer-' + id).disabled = !ready;
    for (const id of ['move-prev', 'move-next', 'move-to', 'rotate-cw', 'rotate-ccw'])
      $('organizer-' + id).disabled = !ready || !selected;
    if (draft) {
      const order = draft.order;
      $('organizer-move-prev').disabled ||= !order.some((page, index) =>
        index > 0 && entry.selected.has(page) && !entry.selected.has(order[index - 1]));
      $('organizer-move-next').disabled ||= !order.some((page, index) =>
        index < order.length - 1 && entry.selected.has(page) && !entry.selected.has(order[index + 1]));
      $('organizer-move-position').max = Math.max(1, order.length - selected + 1);
    }
    $('organizer-selection-count').textContent = '已选 ' + selected + ' 页';
    $('organizer-save').disabled = !ready || state.polling || !draft?.has_changes || (!draft?.dirty && !retrySave(entry));
    $('organizer-save').textContent = isSaving(entry) ? '正在保存…'
      : retrySave(entry) ? '重新保存副本' : '保存副本';
    $('organizer-recovery').hidden = !entry?.unknown || mode !== 'edit';
    const total = count(), page = position(), readable = total > 0 && !(mode === 'edit' && entry?.invalid) &&
      !(mode === 'saved' && outputView?.invalid);
    $('organizer-prev').disabled = !readable || page <= 1;
    $('organizer-next').disabled = !readable || page >= total;
    $('organizer-page-number').disabled = !readable;
    $('organizer-page-number').max = total || 1;
    $('organizer-preview-count').textContent = '/ ' + (total || '—');
    $('organizer-page-total').textContent = total ? total + ' 页' : '';
    for (const card of $('organizer-pages').children) card.draggable = editing && ready;
  }
  function clearPreview(text = '正在读取实际 PDF 页面…') {
    previewSequence++;
    abortReads('preview');
    $('organizer-canvas').hidden = true;
    $('organizer-canvas').removeAttribute('data-revision');
    $('organizer-page-text').value = '';
    $('organizer-preview-empty').textContent = text;
    $('organizer-preview-empty').hidden = false;
    $('organizer-preview-caption').textContent = '';
  }
  function setMode(next) {
    mode = next; epoch++; thumbnailSequence++; navigationSequence++; dragging = null;
    abortReads();
    $('source-reader-panel').hidden = next !== 'read';
    $('organizer-panel').hidden = next === 'read';
    $('reader-status').hidden = next !== 'read';
    document.body.classList.toggle('organizer-active', next !== 'read');
    document.body.classList.toggle('organizer-saved', next === 'saved');
    $('scan-all').textContent = next === 'read' ? '扫描全部' : '扫描全部原件';
    $('scan-selected').textContent = next === 'read' ? '扫描所选' : '扫描所选原件';
    $('plan').title = next === 'read' ? '' : '处理左侧勾选的原件；当前页面草稿不参与此计划';
    clearPreview(); refreshControls();
  }
  function documentChanged() {
    setMode('read');
  }
  function applyDraft(entry, data) {
    const draft = data.draft || data;
    if (!draft.draft_id || !Array.isArray(draft.order)) throw new Error('服务器未返回有效页面草稿。');
    if (entry.draft && draft.revision < entry.draft.revision) return;
    const first = !entry.draft;
    entry.draft = draft; entry.opening = false;
    const available = new Set(draft.order);
    entry.selected = new Set([...entry.selected].filter(page => available.has(page)));
    if (first && draft.order.length) entry.selected.add(draft.order[0]);
    if (!available.has(entry.activeSource)) entry.activeSource = draft.order[0];
    if (!available.has(entry.anchor)) entry.anchor = entry.activeSource;
    if (isCurrent(entry)) refreshControls();
  }
  function sourceFailed(error, ident) {
    const entry = entryFor(ident);
    if (!entry) return;
    entry.invalid = true; entry.unknown = null; entry.opening = false;
    entry.message = '源文件已变化，草稿不能继续编辑。请重新打开工作区确认新版本；已保存的副本仍可查看。';
    entry.messageError = true;
    if (isCurrent(entry) && mode === 'edit') {
      epoch++; thumbnailSequence++; navigationSequence++;
      abortReads();
      $('organizer-pages').replaceChildren(); $('organizer-bookmarks').replaceChildren();
      clearPreview('源文件身份已失效，已清除旧预览。'); paintStatus(entry); refreshControls();
      $('identity').textContent = '源文件身份已失效';
    }
  }
  function isSourceError(error) {
    return error.code === 'SOURCE_CHANGED' || /SOURCE_CHANGED|Source changed|Input changed|identity mismatch/i.test(error.message);
  }
  function isOutputError(error) {
    return error.code === 'OUTPUT_CHANGED' || /OUTPUT_CHANGED/.test(error.message);
  }
  function outputFailed(view) {
    view.invalid = true;
    if (mode !== 'saved' || view !== outputView) return;
    epoch++; thumbnailSequence++; navigationSequence++;
    abortReads();
    $('organizer-pages').replaceChildren(); $('organizer-bookmarks').replaceChildren();
    clearPreview('已保存副本已变化，当前预览与复验证据不再对应。');
    paintStatus(currentEntry()); $('identity').textContent = '已保存副本身份已失效';
  }
  function paintStatus(entry) {
    const draft = entry?.draft;
    let label = '正在打开页面草稿…';
    if (mode === 'saved') label = outputView?.invalid ? '副本已变化 · 预览失效' : '已保存副本 · 正在查看实际文件';
    else if (entry?.invalid) label = '源文件已变化 · 草稿失效';
    else if (entry?.unknown) label = '操作结果待确认';
    else if (entry?.opening) label = '正在打开页面草稿…';
    else if (!draft) label = '未能建立页面草稿';
    else if (!isEditable(entry)) label = '当前文件不能进行页面重写';
    else if (isSaving(entry)) label = '正在保存与复验副本';
    else if (entry.pending) label = '正在更新页面草稿…';
    else if (!draft.has_changes) label = '原件页序与方向 · 尚无修改';
    else if (draft.dirty) label = '页面草稿 · 有未保存修改';
    else label = '当前草稿已保存';
    $('organizer-status').textContent = label;
    $('organizer-state-dot').className = mode === 'saved' ? (outputView?.invalid ? 'error' : 'saved')
      : entry?.invalid ? 'error' : (draft?.has_changes && !draft?.dirty) ? 'saved' : draft?.has_changes ? 'dirty' : '';
    $('organizer-session-note').textContent = mode === 'saved'
      ? (outputView?.name || '已复验副本') : '切换文件保留草稿 · 原件保持不变';
    $('organizer-panel').dataset.revision = mode === 'saved' ? String(outputView?.revision ?? '') : String(draft?.revision ?? '');
    $('organizer-panel').dataset.documentId = entry?.id || '';
    $('organizer-panel').dataset.mode = mode;
    $('organizer-list-title').textContent = mode === 'saved' ? '副本页序' : '页面顺序';
    $('organizer-selection-help').textContent = mode === 'saved'
      ? '点击页面检查保存后的内容与方向' : 'Ctrl / ⌘ 多选 · Shift 连选 · 拖动调整页序';
    if (mode === 'saved') message(null, outputView?.invalid ? '已保存文件的字节身份已改变，已清除旧预览。请查阅任务记录，确认输出文件版本。' : '', !!outputView?.invalid);
    else if (draft && !isEditable(entry) && !entry.invalid) message(entry, '暂不能保存此文件：' + (blockedText(entry) || '未满足页面编辑条件。'), true);
    else message(entry, entry?.message || '', entry?.messageError || false);
    refreshControls(); restoreIdentity();
  }
  async function openEditor() {
    if (!state.current) return;
    const entry = currentEntry();
    setMode('edit'); const openEpoch = epoch;
    state.sequence++; queryChanged();
    $('organizer-pages').replaceChildren(); $('organizer-bookmarks').replaceChildren();
    if (entry.invalid) { paintStatus(entry); clearPreview('源文件已变化，不能继续使用旧草稿。'); return; }
    if (entry.unknown && entry.draft) { paintStatus(entry); clearPreview('请先重新连接草稿，确认上次操作的结果。'); return; }
    entry.opening = true; paintStatus(entry);
    try {
      if (entry.pending) await entry.queue;
      const data = entry.draft ? await api('editor/state', {draft_id: entry.draft.draft_id})
        : await api('editor/open', {id: entry.id});
      applyDraft(entry, data); entry.message = ''; entry.unknown = null;
      if (entry.draft.save_job_id) {
        const job = await api('job', {id: entry.draft.save_job_id, include_results: true});
        await jobUpdated(job);
        if (running(job)) await connectJob(job.id);
      }
      if (openEpoch === epoch && isCurrent(entry) && mode === 'edit') renderEditor(entry);
    } catch (error) {
      entry.opening = false;
      if (isSourceError(error)) sourceFailed(error, entry.id);
      else { entry.unknown = {kind: 'open'}; message(entry, error.message, true); }
      if (openEpoch === epoch && isCurrent(entry)) { paintStatus(entry); clearPreview(error.message); }
    } finally { entry.opening = false; if (isCurrent(entry)) refreshControls(); }
  }
  async function openSource() {
    if (mode === 'read') return;
    setMode('read');
    await Promise.allSettled([loadPage(state.page), loadDetails()]);
  }
  function renderEditor(entry) {
    if (!isCurrent(entry) || mode !== 'edit') return;
    paintStatus(entry);
    if (!entry.draft || entry.invalid || entry.unknown) return;
    if (!isEditable(entry)) {
      $('organizer-pages').replaceChildren(el('p', '当前文件不能建立可保存的页面编辑草稿。', 'empty-note'));
      $('organizer-pages-more').hidden = true;
      clearPreview('请切换“阅读原件”查看此文件。');
      $('organizer-bookmarks').replaceChildren(el('p', '请在“阅读原件”中查看导航。', 'muted'));
      $('organizer-bookmark-count').textContent = ''; return;
    }
    renderPages(); void loadPreview(); void loadNavigation();
  }
  function selectedClasses() {
    const entry = currentEntry();
    for (const card of $('organizer-pages').children) {
      const source = Number(card.dataset.sourcePage), page = Number(card.dataset.outputPage),
        selected = mode === 'edit' && entry?.selected.has(source),
        current = mode === 'saved' ? page === outputView?.page : source === entry?.activeSource;
      card.classList.toggle('selected', !!selected); card.classList.toggle('current', current);
      card.setAttribute('aria-pressed', String(mode === 'saved' ? current : !!selected));
    }
    refreshControls();
  }
  function selectSource(source, event = {}) {
    const entry = currentEntry(); if (!entry?.draft || entry.invalid || isBusy(entry)) return;
    const order = entry.draft.order;
    if (event.shiftKey && entry.anchor !== null) {
      const a = order.indexOf(entry.anchor), b = order.indexOf(source);
      if (!event.ctrlKey && !event.metaKey) entry.selected.clear();
      for (const page of order.slice(Math.min(a, b), Math.max(a, b) + 1)) entry.selected.add(page);
    } else if (event.ctrlKey || event.metaKey || event.toggle) {
      if (entry.selected.has(source)) entry.selected.delete(source); else entry.selected.add(source);
      entry.anchor = source;
    } else { entry.selected = new Set([source]); entry.anchor = source; }
    entry.activeSource = source;
    selectedClasses(); void loadPreview();
  }
  function renderPages() {
    const entry = currentEntry(), saved = mode === 'saved', order = saved
      ? Array.from({length: count()}, (_, index) => index + 1) : entry?.draft?.order || [];
    const shown = Math.min(order.length, saved ? outputView.shown : entry.shown),
      capturedEpoch = epoch, capturedMode = mode;
    const metadata = new Map((entry?.draft?.pages || []).map(page => [page.source_page, page]));
    $('organizer-pages').replaceChildren();
    if (saved && outputView?.invalid) { $('organizer-pages-more').hidden = true; return; }
    for (let index = 0; index < shown; index++) {
      const source = order[index], page = index + 1, meta = metadata.get(source), card = el('button', undefined, 'organizer-page');
      card.type = 'button'; card.dataset.outputPage = String(page);
      if (!saved) card.dataset.sourcePage = String(source);
      card.setAttribute('aria-label', saved ? '查看副本第 ' + page + ' 页'
        : '输出页位 ' + page + '，原件第 ' + source + ' 页');
      card.draggable = !saved && isEditable(entry) && !isBusy(entry);
      const imageBox = el('span', undefined, 'organizer-page-image');
      imageBox.append(el('span', '正在读取…', 'organizer-thumbnail-empty'));
      const caption = el('span', undefined, 'organizer-page-caption');
      caption.append(el('strong', '第 ' + page + ' 页'));
      if (!saved) {
        const rotation = entry.draft.rotations[source - 1] || 0;
        caption.append(el('small', '原页 ' + source + (meta?.page_label ? ' · ' + meta.page_label : '')));
        if (rotation) caption.append(el('small', '已旋转 ' + rotation + '°', 'organizer-page-change'));
        const check = el('span', '✓', 'organizer-page-check'); check.setAttribute('aria-hidden', 'true');
        card.append(check);
      }
      card.append(imageBox, caption);
      card.addEventListener('click', event => {
        if (capturedEpoch !== epoch || capturedMode !== mode) return;
        if (saved) void goPage(page);
        else if (event.target.closest('.organizer-page-check')) selectSource(source, {
          toggle: true, shiftKey: event.shiftKey, ctrlKey: event.ctrlKey, metaKey: event.metaKey});
        else selectSource(source, event);
      });
      card.addEventListener('keydown', event => {
        if (saved || capturedEpoch !== epoch) return;
        if (event.key === ' ' && !event.shiftKey) {
          event.preventDefault(); selectSource(source, {toggle: true}); return;
        }
        const cards = [...$('organizer-pages').children], at = cards.indexOf(card);
        const columns = Math.max(1, Math.floor($('organizer-pages').clientWidth / card.getBoundingClientRect().width));
        const target = {ArrowLeft: at - 1, ArrowRight: at + 1, ArrowUp: at - columns,
          ArrowDown: at + columns, Home: 0, End: cards.length - 1}[event.key];
        if (target !== undefined && cards[target]) {
          event.preventDefault(); cards[target].focus();
          selectSource(Number(cards[target].dataset.sourcePage), event);
        }
      });
      card.addEventListener('dragstart', event => {
        if (saved || !isEditable(entry) || isBusy(entry)) { event.preventDefault(); return; }
        if (!entry.selected.has(source)) { entry.selected = new Set([source]); entry.activeSource = source; selectedClasses(); }
        dragging = {draftId: entry.draft.draft_id, revision: entry.draft.revision};
        event.dataTransfer.setData('text/plain', 'ezctd-pages:' + dragging.draftId);
        event.dataTransfer.effectAllowed = 'move';
      });
      card.addEventListener('dragover', event => {
        if (!dragging || dragging.draftId !== entry?.draft?.draft_id || saved) return;
        event.preventDefault(); event.dataTransfer.dropEffect = 'move'; card.classList.add('drop-before');
      });
      card.addEventListener('dragleave', () => card.classList.remove('drop-before'));
      card.addEventListener('drop', event => {
        event.preventDefault(); card.classList.remove('drop-before');
        if (!dragging || saved || dragging.draftId !== entry?.draft?.draft_id ||
            dragging.revision !== entry.draft.revision || entry.selected.has(source)) return;
        const chosen = new Set(entry.selected);
        const remainder = entry.draft.order.filter(item => !chosen.has(item));
        const insert = remainder.indexOf(source), moving = entry.draft.order.filter(item => chosen.has(item));
        remainder.splice(insert, 0, ...moving); dragging = null;
        void mutate(entry, 'edit', {type: 'reorder', order: remainder});
      });
      card.addEventListener('dragend', () => {
        dragging = null; for (const button of $('organizer-pages').children) button.classList.remove('drop-before');
      });
      $('organizer-pages').append(card);
    }
    if (!order.length) $('organizer-pages').append(el('p', '没有可显示的页面。', 'empty-note'));
    $('organizer-pages-more').hidden = shown >= order.length;
    $('organizer-pages-more').textContent = '继续显示 · ' + shown + ' / ' + order.length + ' 页';
    selectedClasses(); void loadThumbnails();
  }
  async function loadThumbnails() {
    const sequence = ++thumbnailSequence, capturedEpoch = epoch, capturedMode = mode,
      entry = currentEntry(), revision = entry?.draft?.revision, view = outputView;
    abortReads('thumbnail');
    const cards = [...$('organizer-pages').querySelectorAll('.organizer-page')]; let cursor = 0;
    const current = () => sequence === thumbnailSequence && capturedEpoch === epoch && capturedMode === mode &&
      (mode === 'saved' ? view === outputView && !view.invalid : isCurrent(entry) && entry.draft?.revision === revision && !entry.invalid);
    const run = async () => {
      while (cursor < cards.length && current()) {
        const card = cards[cursor++], page = Number(card.dataset.outputPage);
        try {
          const data = mode === 'saved' ? await readApi('thumbnail', 'editor/output-page', {job_id: view.jobId, page, dpi: 36, thumbnail: true})
            : await readApi('thumbnail', 'editor/page', {draft_id: entry.draft.draft_id, revision, page, dpi: 36, thumbnail: true});
          if (!current()) return;
          const image = el('img'); image.src = 'data:image/png;base64,' + data.png_base64;
          image.alt = (capturedMode === 'saved' ? '已保存副本' : '编辑草稿') + '第 ' + page + ' 页实际预览';
          card.querySelector('.organizer-page-image').replaceChildren(image);
        } catch (error) {
          if (!current()) return;
          if (isOutputError(error) && capturedMode === 'saved') { outputFailed(view); return; }
          if (isSourceError(error) && capturedMode === 'edit') { sourceFailed(error, entry.id); return; }
          card.querySelector('.organizer-page-image').replaceChildren(el('small', '预览未完成'));
          card.title = error.message;
        }
      }
    };
    await Promise.allSettled([run(), run()]);
  }
  function applyZoom() {
    const value = $('organizer-zoom').value, canvas = $('organizer-canvas');
    canvas.style.width = value === 'fit' ? '100%' : (previewWidth * 96 / 72 * Number(value) / 100) + 'px';
    canvas.style.maxWidth = value === 'fit' ? '100%' : 'none';
  }
  async function loadPreview() {
    if (mode === 'read' || !count() || (mode === 'saved' && outputView?.invalid)) return;
    const entry = currentEntry(); if (mode === 'edit' && (entry.invalid || entry.unknown || !entry.draft)) return;
    clearPreview(); const sequence = previewSequence, capturedEpoch = epoch, capturedMode = mode,
      revision = entry?.draft?.revision, page = position(), view = outputView;
    $('organizer-page-number').value = page; selectedClasses();
    const current = () => sequence === previewSequence && capturedEpoch === epoch && capturedMode === mode &&
      (mode === 'saved' ? view === outputView && !view.invalid : isCurrent(entry) && entry.draft?.revision === revision && !entry.invalid);
    try {
      const data = capturedMode === 'saved' ? await readApi('preview', 'editor/output-page', {
        job_id: view.jobId, page, dpi: Number($('organizer-dpi').value)}) : await readApi('preview', 'editor/page', {
        draft_id: entry.draft.draft_id, revision, page, dpi: Number($('organizer-dpi').value)});
      if (!current()) return;
      const image = new Image(); image.src = 'data:image/png;base64,' + data.png_base64; await image.decode();
      if (!current()) return;
      const canvas = $('organizer-canvas'); canvas.width = data.width_px; canvas.height = data.height_px;
      canvas.getContext('2d').drawImage(image, 0, 0);
      canvas.dataset.revision = String(capturedMode === 'saved' ? view.revision : revision);
      canvas.dataset.page = String(page); canvas.dataset.mode = capturedMode;
      canvas.hidden = false; $('organizer-preview-empty').hidden = true;
      $('organizer-page-text').value = data.text || ''; previewWidth = data.size?.[0] || 595; applyZoom();
      $('organizer-preview-caption').textContent = (capturedMode === 'saved' ? '已保存文件 · 第 ' + page + ' 页'
        : '草稿 · 输出第 ' + page + ' 页 ← 原件第 ' + entry.draft.order[page - 1] + ' 页') +
        ' · ' + data.rotation_degrees + '° · ' + data.width_px + ' × ' + data.height_px;
      if (capturedMode === 'saved') {
        view.sha = data.output_sha256 || data.input_sha256 || view.sha;
        canvas.setAttribute('aria-label', '已保存副本第 ' + page + ' 页实际 PDF 预览');
      } else canvas.setAttribute('aria-label', '页面草稿输出第 ' + page + ' 页实际 PDF 预览');
      restoreIdentity();
    } catch (error) {
      if (!current()) return;
      if (isOutputError(error) && capturedMode === 'saved') outputFailed(view);
      else if (isSourceError(error) && capturedMode === 'edit') sourceFailed(error, entry.id);
      else { clearPreview(error.message); message(entry, '当前页面未能完成预览：' + error.message, true); }
    }
  }
  async function loadNavigation() {
    const sequence = ++navigationSequence, capturedEpoch = epoch, capturedMode = mode,
      entry = currentEntry(), revision = entry?.draft?.revision, view = outputView;
    abortReads('navigation');
    if (mode === 'read' || (mode === 'saved' && outputView?.invalid) || (mode === 'edit' && (!entry?.draft || entry.invalid))) return;
    $('organizer-bookmarks').replaceChildren(el('p', '正在读取当前文档书签…', 'muted'));
    $('organizer-bookmark-count').textContent = '';
    const current = () => sequence === navigationSequence && capturedEpoch === epoch && capturedMode === mode &&
      (mode === 'saved' ? view === outputView && !view.invalid : entry.draft?.revision === revision && !entry.invalid);
    try {
      const data = capturedMode === 'saved' ? await readApi('navigation', 'editor/output-navigation', {job_id: view.jobId})
        : await readApi('navigation', 'editor/navigation', {draft_id: entry.draft.draft_id, revision});
      if (!current()) return;
      if (capturedMode === 'saved') { view.navigation = data; view.count = data.page_count; }
      const items = data.bookmarks || [];
      $('organizer-bookmarks').replaceChildren(); $('organizer-bookmark-count').textContent = items.length + ' 项';
      for (const item of items) {
        const page = item.physical_page, button = el('button', item.title + (page ? ' · 第 ' + page + ' 页' : ' · 目标未解析'), 'organizer-bookmark');
        button.disabled = !Number.isInteger(page) || page < 1 || page > data.page_count;
        button.dataset.page = String(page || '');
        button.style.paddingLeft = (8 + Math.min(item.level || 0, 7) * 11) + 'px';
        button.addEventListener('click', () => { if (current()) void goPage(page); });
        $('organizer-bookmarks').append(button);
      }
      if (!items.length) $('organizer-bookmarks').append(el('p', '当前文档没有可列出的书签。', 'muted'));
      if (data.truncated) $('organizer-bookmarks').append(el('p', '导航读取达到处理上限，当前列表不代表完整结构检查。', 'muted'));
      refreshControls();
    } catch (error) {
      if (!current()) return;
      if (isOutputError(error) && capturedMode === 'saved') outputFailed(view);
      else if (isSourceError(error) && capturedMode === 'edit') sourceFailed(error, entry.id);
      else $('organizer-bookmarks').replaceChildren(el('p', error.message, 'muted'));
    }
  }
  async function goPage(page) {
    if (!Number.isInteger(page) || page < 1 || page > count()) {
      $('organizer-page-number').value = position(); message(currentEntry(), '请输入有效的输出页位。', true); return;
    }
    if (mode === 'saved') outputView.page = page;
    else if (mode === 'edit') currentEntry().activeSource = currentEntry().draft.order[page - 1];
    await loadPreview();
  }
  async function mutate(entry, route, command) {
    if (!isEditable(entry) || isBusy(entry)) return;
    if (command?.type === 'reorder' && command.order.every((page, index) => page === entry.draft.order[index])) return;
    entry.pending++; thumbnailSequence++; navigationSequence++; abortReads();
    clearPreview('正在更新实际 PDF 草稿…'); paintStatus(entry);
    entry.queue = entry.queue.then(async () => {
      const revision = entry.draft.revision;
      try {
        const payload = {draft_id: entry.draft.draft_id, revision};
        if (command) payload.command = command;
        applyDraft(entry, await api('editor/' + route, payload));
        message(entry, '');
      } catch (error) {
        if (isSourceError(error)) sourceFailed(error, entry.id);
        else {
          // A reply can be lost after a successful mutation. Re-read the draft;
          // never replay a rotate/undo command on the assumption it failed.
          entry.unknown = {kind: 'edit', revision};
          try {
            applyDraft(entry, await api('editor/state', {draft_id: entry.draft.draft_id}));
            entry.unknown = null;
            message(entry, error.code === 'STALE_DRAFT' ? '草稿已在其他操作中更新，已读取最新状态；请核对页序和方向。'
              : '已重新读取草稿，未重复发送修改。请核对当前页序和方向。', true);
          } catch (recoveryError) {
            if (isSourceError(recoveryError)) sourceFailed(recoveryError, entry.id);
            else message(entry, error.message + '；修改结果待确认，请重新连接草稿。', true);
          }
        }
      } finally {
        entry.pending--;
        if (isCurrent(entry) && mode === 'edit') {
          if (entry.unknown || entry.invalid) { paintStatus(entry); clearPreview(entry.invalid ? '源文件身份已失效。' : '等待重新连接，已清除旧预览。'); }
          else renderEditor(entry);
        }
      }
    });
    await entry.queue;
  }
  function selectRange() {
    const entry = currentEntry(); if (!isEditable(entry) || isBusy(entry)) return;
    const raw = $('organizer-range').value.trim().replace(/[，、;；]/g, ',').replace(/[–—]/g, '-');
    const positions = new Set();
    try {
      if (!raw) throw new Error('请填写当前输出页位，例如 2-4,6。');
      for (const part of raw.split(',')) {
        const match = /^\s*(\d+)\s*(?:-\s*(\d+)\s*)?$/.exec(part);
        if (!match) throw new Error('页位格式不正确，请使用 2-4,6 这样的写法。');
        const first = Number(match[1]), last = match[2] ? Number(match[2]) : first;
        if (!Number.isSafeInteger(first) || !Number.isSafeInteger(last) || first < 1 || last < first || last > entry.draft.order.length)
          throw new Error('选择范围必须在第 1 至 ' + entry.draft.order.length + ' 个输出页位内。');
        for (let page = first; page <= last; page++) positions.add(page);
      }
      const sorted = [...positions].sort((a, b) => a - b);
      entry.selected = new Set(sorted.map(page => entry.draft.order[page - 1]));
      entry.activeSource = entry.draft.order[sorted[0] - 1]; entry.anchor = entry.activeSource;
      message(entry, ''); selectedClasses(); void loadPreview();
    } catch (error) { message(entry, error.message, true); }
  }
  function moveRelative(delta) {
    const entry = currentEntry(); if (!isEditable(entry) || isBusy(entry) || !entry.selected.size) return;
    const order = [...entry.draft.order];
    for (let index = delta < 0 ? 1 : order.length - 2;
      delta < 0 ? index < order.length : index >= 0; index -= delta) {
      const adjacent = index + delta;
      if (entry.selected.has(order[index]) && !entry.selected.has(order[adjacent]))
        [order[index], order[adjacent]] = [order[adjacent], order[index]];
    }
    void mutate(entry, 'edit', {type: 'reorder', order});
  }
  function moveTo() {
    const entry = currentEntry(); if (!isEditable(entry) || isBusy(entry) || !entry.selected.size) return;
    const destination = Number($('organizer-move-position').value), remaining = entry.draft.order.filter(page => !entry.selected.has(page)),
      moving = entry.draft.order.filter(page => entry.selected.has(page));
    if (!Number.isInteger(destination) || destination < 1 || destination > remaining.length + 1) {
      message(entry, '所选 ' + moving.length + ' 页可从第 1 至 ' + (remaining.length + 1) + ' 个输出页位开始。', true); return;
    }
    remaining.splice(destination - 1, 0, ...moving); void mutate(entry, 'edit', {type: 'reorder', order: remaining});
  }
  async function jobUpdated(job) {
    if (job.kind !== 'organize') return;
    const known = [...entries.values()].find(item => item.draft?.draft_id === job.draft_id || item.draft?.save_job_id === job.id),
      id = known?.id || job.results?.[0]?.id || job.requested_ids?.[0];
    if (!id) return;
    const entry = entryFor(id); entry.lastJob = job;
    if (entry.unknown?.kind === 'save' && entry.unknown.revision === job.revision) entry.unknown = null;
    if (running(job)) { if (isCurrent(entry) && mode === 'edit') paintStatus(entry); return; }
    const result = (job.results || []).find(row => row.status === 'VERIFIED_COPY');
    if (result) {
      const previous = outputs.get(job.id);
      outputs.set(job.id, previous || {jobId: job.id, documentId: id, revision: result.saved_revision ?? job.revision,
        count: result.page_count || result.proof?.page_count || 0, page: 1, shown: PAGE_GROUP,
        name: result.output_basename || result.output_relative, sha: result.proof?.output_sha256, job});
      entry.outputId = job.id;
    }
    if (entry.draft && entry.syncedJob !== job.id + ':' + job.status) {
      entry.syncedJob = job.id + ':' + job.status;
      try { applyDraft(entry, await api('editor/state', {draft_id: entry.draft.draft_id})); }
      catch (error) {
        if (isSourceError(error)) sourceFailed(error, entry.id);
        else if (!result) message(entry, '任务已结束，草稿状态尚未读取：' + error.message, true);
      }
    }
    if (!result && ['ERROR', 'CANCELLED', 'COMPLETED_WITH_ERRORS'].includes(job.status))
      message(entry, job.status === 'CANCELLED' ? '保存已取消，草稿保留。可重新保存副本。'
        : '副本未能完成保存与复验。草稿保留，可查看任务结果后重新保存。', true);
    if (result && !entry.invalid) message(entry, '副本已保存并完成页面组织复验，可打开实际文件检查。');
    if (isCurrent(entry)) { refreshControls(); if (mode === 'edit') paintStatus(entry); }
  }
  async function recover(entry) {
    if (entry.unknown?.kind === 'open' || !entry.draft) {
      entry.unknown = null; return openEditor();
    }
    const unknown = entry.unknown;
    try {
      applyDraft(entry, await api('editor/state', {draft_id: entry.draft.draft_id}));
      if (entry.draft.save_job_id && (!unknown || unknown.kind !== 'save' || entry.draft.save_revision === unknown.revision)) {
        const job = await api('job', {id: entry.draft.save_job_id, include_results: true});
        await jobUpdated(job); entry.unknown = null;
        if (unknown?.kind === 'save' || running(job)) await connectJob(job.id);
      } else if (unknown?.kind === 'save') {
        // A successful state/history read proves that this revision has no
        // accepted save. Only then can the save control be offered again.
        reconcileHistory(await api('history')); entry.unknown = null;
        message(entry, '服务器未登记本次草稿的保存任务，可以重新保存。');
      } else entry.unknown = null;
      if (isCurrent(entry) && mode === 'edit') renderEditor(entry);
    } catch (error) {
      if (isSourceError(error)) {
        sourceFailed(error, entry.id);
        if (unknown?.kind === 'save') {
          // Source identity can change after a valid output was published.
          // Recover only this exact draft/revision from the registered task
          // history; reading that saved output does not depend on the source.
          try {
            const history = await api('history'); reconcileHistory(history);
            const registered = history.jobs.find(job => job.kind === 'organize' &&
              job.draft_id === entry.draft.draft_id && job.revision === unknown.revision);
            if (registered) {
              const job = await api('job', {id: registered.id, include_results: true});
              await jobUpdated(job);
              if (running(job)) await connectJob(job.id); else showJob(job);
            }
          } catch (historyError) {
            entry.unknown = unknown;
            message(entry, '源文件已变化，草稿已停止编辑；上次保存任务仍待确认，请重新连接。' + historyError.message, true);
          }
        }
      }
      else { entry.unknown = unknown || {kind: 'edit'}; message(entry, error.message + '；操作状态仍待确认。', true); }
      if (isCurrent(entry)) paintStatus(entry);
    }
  }
  async function save() {
    const entry = currentEntry();
    if (!isEditable(entry) || isBusy(entry) || state.polling || !entry.draft.has_changes ||
      (!entry.draft.dirty && !retrySave(entry))) return;
    const revision = entry.draft.revision, retry = !!retrySave(entry);
    entry.savePending = true; state.polling = true; updateSelection(); paintStatus(entry);
    try {
      const payload = {draft_id: entry.draft.draft_id, revision, confirmed: true};
      if (retry) payload.retry = true;
      const answer = await api('editor/save', payload);
      entry.draft.save_job_id = answer.job_id; entry.draft.save_revision = revision;
      await connectJob(answer.job_id);
    } catch (error) {
      if (isSourceError(error)) {
        sourceFailed(error, entry.id);
        try { reconcileHistory(await api('history')); } catch (_) { /* retain uncertainty in the task strip */ }
      } else {
        entry.unknown = {kind: 'save', revision};
        message(entry, '保存响应未收到，正在核对已登记任务。', true);
        await recover(entry);
      }
    } finally {
      entry.savePending = false;
      if (isCurrent(entry) && mode === 'edit') paintStatus(entry);
      updateSelection();
    }
  }
  async function openOutputJob(job) {
    if (job.kind !== 'organize') return;
    await jobUpdated(job);
    const view = outputs.get(job.id);
    if (!view) throw new Error('此任务没有可打开的已复验副本。');
    if (state.current !== view.documentId) await openDocument(view.documentId);
    currentEntry().outputId = job.id; outputView = view;
    setMode('saved'); paintStatus(currentEntry());
    renderPages(); void loadPreview(); void loadNavigation();
  }

  $('mode-read').addEventListener('click', safe(openSource));
  $('mode-organize').addEventListener('click', safe(() => { if (mode !== 'edit') return openEditor(); }));
  $('mode-saved').addEventListener('click', safe(async () => {
    const ident = currentEntry()?.outputId;
    if (ident) await openOutputJob(await api('job', {id: ident, include_results: true}));
  }));
  $('organizer-select-range').addEventListener('click', selectRange);
  $('organizer-range').addEventListener('keydown', event => { if (event.key === 'Enter') selectRange(); });
  $('organizer-select-all').addEventListener('click', () => {
    const entry = currentEntry(); if (!isEditable(entry) || isBusy(entry)) return;
    entry.selected = new Set(entry.draft.order); selectedClasses();
  });
  $('organizer-clear-selection').addEventListener('click', () => {
    const entry = currentEntry(); if (!entry || isBusy(entry)) return;
    entry.selected.clear(); selectedClasses();
  });
  $('organizer-move-prev').addEventListener('click', () => moveRelative(-1));
  $('organizer-move-next').addEventListener('click', () => moveRelative(1));
  $('organizer-move-to').addEventListener('click', moveTo);
  $('organizer-move-position').addEventListener('keydown', event => { if (event.key === 'Enter') moveTo(); });
  for (const [name, degrees] of [['cw', 90], ['ccw', -90]]) $('organizer-rotate-' + name).addEventListener('click', () => {
    const entry = currentEntry(); if (entry?.selected.size) void mutate(entry, 'edit', {type: 'rotate', pages: [...entry.selected], degrees});
  });
  for (const route of ['undo', 'redo']) $('organizer-' + route).addEventListener('click', () => { void mutate(currentEntry(), route); });
  $('organizer-reset').addEventListener('click', () => { void mutate(currentEntry(), 'edit', {type: 'reset'}); });
  $('organizer-save').addEventListener('click', safe(save));
  $('organizer-reconnect').addEventListener('click', safe(() => recover(currentEntry())));
  $('organizer-prev').addEventListener('click', () => { void goPage(position() - 1); });
  $('organizer-next').addEventListener('click', () => { void goPage(position() + 1); });
  $('organizer-page-number').addEventListener('change', () => { void goPage(Number($('organizer-page-number').value)); });
  $('organizer-dpi').addEventListener('change', () => { void loadPreview(); });
  $('organizer-zoom').addEventListener('change', applyZoom);
  $('organizer-pages-more').addEventListener('click', () => {
    if (mode === 'saved') outputView.shown += PAGE_GROUP; else currentEntry().shown += PAGE_GROUP;
    renderPages();
  });
  document.addEventListener('keydown', event => {
    if (mode === 'read' || document.querySelector('dialog[open]')) return;
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(event.target.tagName), modifier = event.ctrlKey || event.metaKey;
    if (modifier && !typing && mode === 'edit' && event.key.toLowerCase() === 'z') {
      event.preventDefault(); const entry = currentEntry(), route = event.shiftKey ? 'redo' : 'undo';
      if (entry?.draft?.['can_' + route]) void mutate(entry, route);
    } else if (modifier && !typing && mode === 'edit' && event.key.toLowerCase() === 'y') {
      event.preventDefault(); const entry = currentEntry(); if (entry?.draft?.can_redo) void mutate(entry, 'redo');
    } else if (modifier && !typing && mode === 'edit' && event.key.toLowerCase() === 'a' && event.target.closest('#organizer-pages')) {
      event.preventDefault(); $('organizer-select-all').click();
    } else if (event.altKey && !modifier && !typing && ['ArrowLeft', 'ArrowRight'].includes(event.key)) {
      event.preventDefault(); void goPage(position() + (event.key === 'ArrowRight' ? 1 : -1));
    }
  });
  window.addEventListener('beforeunload', event => {
    if ([...entries.values()].some(entry => entry.unknown || entry.savePending ||
      (entry.draft?.has_changes && entry.draft?.dirty))) { event.preventDefault(); event.returnValue = ''; }
  });
  refreshControls();
  return {active: () => mode !== 'read', documentChanged, sourceFailed, refreshControls,
    restoreIdentity, jobUpdated, openOutputJob};
})();
