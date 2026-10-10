'use strict';
const $ = id => document.getElementById(id);
const token = new URLSearchParams(location.hash.slice(1)).get('key');
history.replaceState(null, '', '/');
const state = {
  files: [], selected: new Set(), current: null, page: 1, count: 0,
  sequence: 0, documentEpoch: 0, detailsEpoch: 0, searchEpoch: 0, queryEpoch: 0, pollEpoch: 0,
  lastJob: null, dialogJob: null, plan: null, session: null, polling: false,
  navigation: null, details: null, thumbnailsLoaded: 0, thumbnailBusy: false,
  search: null, searchBusy: false, pageImage: null, submissionUnknown: false, connectionNotice: null
};
const jobNames = {scan: '批量检查', plan: '副本处理计划', apply: '生成与复验副本'};
const jobStates = {QUEUED: '等待开始', RUNNING: '处理中', FINALIZING: '保存任务记录',
  COMPLETED: '任务完成', COMPLETED_WITH_ERRORS: '部分未完成', CANCELLED: '已取消', ERROR: '任务失败'};
const running = job => ['QUEUED', 'RUNNING', 'FINALIZING'].includes(job.status);
const statusLabels = {PASS: '本地条件满足', FAIL: '发现问题', NOT_APPLICABLE: '不适用',
  INDETERMINATE: '无法判定', NOT_RUN: '未运行'};
const blockers = {SIGNATURE_OR_PRIOR_REVISION_BYTE_SIGNAL: '发现签名或历史修订字节信号', SIGNATURE_SIGNAL: '发现数字签名信号', DOCUMENT_PERMISSIONS_SIGNAL: '存在文档权限信号',
  ENCRYPTED_OR_PERMISSION_RESTRICTED: '加密或权限限制', PASSWORD_REQUIRED: '需要密码',
  INTERACTIVE_FORM_OR_PORTFOLIO_NOT_SUPPORTED: '表单或文档组合不在本次处理范围',
  ACTIVE_CONTENT_NOT_SUPPORTED: '动态内容需单独复核', ATTACHMENTS_NOT_SUPPORTED_FOR_REWRITE: '含附件，暂不重写',
  SOURCE_SYNTAX_WARNINGS: '源文件结构警告', PAGE_LIMIT_OR_EMPTY_DOCUMENT: '页数超限或空文档'};

const reasonLabels = {
  'Exhaustive rule coverage has not been demonstrated': '当前检查尚未覆盖本条规则的全部情况。',
  'Candidate finding requires semantic or technical review': '发现待复核项，需确认其技术含义和适用性。',
  'Bounded local property check completed': '已完成本地有限属性检查。',
  'Explicit local condition observed; official calibration not established': '已发现明确本地问题；尚未完成官方等价校准。'
};
const findingLabels = {
  'PDF is not linearized for Fast Web View.': 'PDF 尚未启用快速 Web 查看。',
  'Bookmark destination does not use Inherit Zoom.': '书签目标未使用承前缩放，需复核。',
  'PDF initial view is inconsistent with the current experimental interpretation of bookmark visibility/default magnification/layout.': '初始视图与当前实验性解释不一致：涉及书签显示、默认缩放或布局，需复核。',
  'Unembedded font names need review against the CDE list; aliases are not automatically equivalent.': '未嵌入字体需对照 CDE 名单复核；字体别名不能自动视为等价。'
};


function el(tag, text, cls) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (cls) node.className = cls;
  return node;
}
function notice(text, error = false) {
  $('notice').textContent = text;
  $('notice').className = 'notice' + (error ? ' error' : '');
  $('notice').hidden = !text;
}
function connectionIssue(message) {
  state.connectionNotice = message; notice(message, true);
}
function clearConnectionIssue() {
  // Recovery must clear its own stale warning, while retaining an unrelated
  // reader/source warning that may have appeared in the meantime.
  if (state.connectionNotice && $('notice').textContent === state.connectionNotice) notice('');
  state.connectionNotice = null;
}
async function api(route, payload = {}) {
  if (!token) throw new Error('本地会话凭证缺失。请从启动器给出的完整地址重新打开。');
  const response = await fetch('/api/' + route, {
    method: 'POST', cache: 'no-store', credentials: 'omit',
    headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + token},
    body: JSON.stringify(payload)
  });
  const body = await response.json();
  if (!response.ok) {
    const error = new Error(body.error || '操作失败');
    error.code = body.error_code;
    throw error;
  }
  return body;
}
function safe(action) {
  return async (...args) => {
    try { await action(...args); }
    catch (error) { notice(error.message, true); }
  };
}
function tab(name) {
  for (const button of document.querySelectorAll('[data-tab]')) {
    const active = button.dataset.tab === name;
    button.classList.toggle('active', active);
    button.setAttribute('aria-selected', String(active));
    button.tabIndex = active ? 0 : -1;
    $('tab-' + button.dataset.tab).hidden = !active;
  }
}
function sizeText(size) {
  return size >= 1024 * 1024 ? (size / 1024 / 1024).toFixed(1) + ' MB'
    : Math.max(1, Math.round(size / 1024)) + ' KB';
}
function fileState(file) {
  const s = file.scan_summary;
  if (!s) return {key: 'unscanned', label: '待扫描', cls: ''};
  if (s.FAIL) return {key: 'issues', label: s.FAIL + ' 项问题', cls: 'fail'};
  if (s.INDETERMINATE || s.NOT_RUN) return {key: 'pending', label: '存在未判定项', cls: 'pending'};
  return {key: 'checked', label: '本地检查已完成', cls: 'pass'};
}
async function refresh() {
  const data = await api('session');
  state.session = data; state.files = data.files;
  $('root-name').textContent = data.root_name;
  const scanned = data.files.filter(f => f.scanned).length;
  const issues = data.files.filter(f => (f.scan_summary || {}).FAIL).length;
  $('summary').textContent = data.files.length + ' 份 PDF · ' + scanned + ' 份已有本地检查' +
    (issues ? ' · ' + issues + ' 份发现问题' : '') + ' · 部分临床资料';
  $('file-count').textContent = String(data.files.length);
  $('history-count').textContent = String((data.jobs || []).length);
  $('output-path').textContent = '工作目录：' + data.output_root;
  renderFiles();
}
function filteredFiles() {
  const q = $('file-filter').value.trim().toLocaleLowerCase();
  const status = $('file-status').value;
  return state.files.filter(file => file.relative_path.toLocaleLowerCase().includes(q)
    && (status === 'all' || (status === 'pending'
      ? (file.scan_summary || {}).INDETERMINATE || (file.scan_summary || {}).NOT_RUN
      : fileState(file).key === status)));
}
function renderFiles() {
  const list = $('files'); list.replaceChildren();
  const visible = filteredFiles();
  for (const file of visible) {
    const row = el('div', undefined, 'file-row' + (file.id === state.current ? ' selected' : ''));
    const check = el('input'); check.type = 'checkbox';
    check.checked = state.selected.has(file.id);
    check.setAttribute('aria-label', '勾选 ' + file.relative_path);
    check.addEventListener('change', () => {
      if (check.checked) state.selected.add(file.id); else state.selected.delete(file.id);
      updateSelection();
    });
    const button = el('button', undefined, 'file-open');
    button.title = file.relative_path;
    button.setAttribute('aria-pressed', String(file.id === state.current));
    const parts = file.relative_path.split('/');
    button.append(el('strong', parts.at(-1)), el('small', parts.slice(0, -1).join('/') || '输入根目录'));
    const status = fileState(file), meta = el('div', undefined, 'file-meta');
    meta.append(el('small', sizeText(file.size)), el('span', status.label, 'file-status ' + status.cls));
    button.append(meta);
    if (file.report_count) button.append(el('small', file.report_count + ' 条原报告观察（路径候选）', 'tag'));
    button.addEventListener('click', safe(() => openDocument(file.id)));
    row.append(check, button); list.append(row);
  }
  if (!visible.length) list.append(el('p', state.files.length ? '没有符合筛选条件的文件。' : '所选目录中没有 PDF。', 'empty-note'));
  $('file-count').textContent = visible.length + ' / ' + state.files.length;
  updateSelection();
}
function updateSelection() {
  $('selected-count').textContent = String(state.selected.size);
  $('plan').disabled = !state.selected.size || state.polling;
  $('scan-selected').disabled = !state.selected.size || state.polling;
  $('scan-all').disabled = state.polling || !state.files.length;
  const visible = filteredFiles(), selectedVisible = visible.filter(f => state.selected.has(f.id)).length;
  $('select-all').checked = !!visible.length && selectedVisible === visible.length;
  $('select-all').indeterminate = selectedVisible > 0 && selectedVisible < visible.length;
  const hidden = state.selected.size - selectedVisible;
  $('selection-note').textContent = state.selected.size ? '已选 ' + state.selected.size + ' 份' +
    (hidden ? '，其中 ' + hidden + ' 份在筛选结果外' : '') : '尚未选择文件';
}
function invalidateSearch() {
  state.searchEpoch++; state.search = null; state.searchBusy = false;
  $('doc-search-results').replaceChildren(); $('doc-search-heading').hidden = true;
  $('search-results-summary').textContent = ''; $('search-more').hidden = true;
  $('search-doc').disabled = false; $('search-more').disabled = false;
}
function queryChanged() {
  state.queryEpoch++; invalidateSearch();
  $('search-count').textContent = '';
  // Keep the page while removing the previous query's overlay immediately.
  const canvas = $('page-canvas');
  if (state.pageImage && !canvas.hidden) {
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height); ctx.drawImage(state.pageImage, 0, 0);
  }
}
function sourceFailure(error) {
  if (error.code !== 'SOURCE_CHANGED' && !/SOURCE_CHANGED|identity mismatch|Source changed|Input changed/i.test(error.message)) return;
  state.documentEpoch++; state.detailsEpoch++; state.sequence++;
  state.navigation = null; state.details = null; state.pageImage = null;
  queryChanged();
  $('bookmarks').replaceChildren(el('p', '源文件已变化。请关闭并重新打开工作区，确认新版本。', 'muted'));
  $('thumbnails').replaceChildren(); $('page-text').value = '';
  $('page-canvas').hidden = true; $('page-empty').hidden = false;
  $('page-empty').textContent = '源文件已变化；当前页面和检查结果已失效。';
  $('identity').textContent = '文件身份已失效，请重新打开工作区';
  renderIssues(); renderReport([]);
}
async function openDocument(ident) {
  const epoch = ++state.documentEpoch;
  state.current = ident; state.page = 1; state.count = 0; state.details = null; state.navigation = null;
  state.thumbnailsLoaded = 0; state.thumbnailBusy = false; state.pageImage = null;
  $('search-query').value = ''; queryChanged();
  $('bookmark-filter').value = ''; $('thumbnails').replaceChildren();
  $('thumbnail-panel').hidden = true; $('show-thumbnails').setAttribute('aria-expanded', 'false');
  const file = state.files.find(item => item.id === ident);
  $('document-name').textContent = file.relative_path;
  $('document-name').title = file.relative_path;
  $('node-id').value = file.context.node_id || '';
  $('document-role').value = file.context.document_role || '';
  $('language').value = file.context.language || '';
  $('context-summary').textContent = file.context.node_id || '待确认';
  $('context-details').open = !file.context.node_id;
  $('issue-status').value = 'all'; $('issue-query').value = '';
  $('bookmarks').replaceChildren(el('p', '正在读取书签…', 'muted'));
  renderIssues(); renderReport([]); renderFiles();
  api('navigation', {id: ident}).then(data => {
    if (state.documentEpoch !== epoch) return;
    state.navigation = data; state.count = data.page_count; renderBookmarks();
  }).catch(error => {
    if (state.documentEpoch !== epoch) return;
    $('bookmarks').replaceChildren(el('p', error.message, 'muted'));
    sourceFailure(error);
  });
  await Promise.allSettled([loadPage(1), loadDetails()]);
}
async function loadPage(number) {
  if (!state.current) return;
  if (!Number.isInteger(number) || number < 1 || (state.count && number > state.count)) {
    $('page-number').value = state.page;
    notice('请输入有效的物理页码。', true); return;
  }
  const sequence = ++state.sequence, epoch = state.documentEpoch, ident = state.current,
    queryEpoch = state.queryEpoch;
  state.pageImage = null;
  state.page = number; $('page-number').value = number;
  $('reader-status').textContent = '正在读取';
  $('page-empty').textContent = '正在解析页面…'; $('page-empty').hidden = false;
  $('page-canvas').hidden = true; $('page-text').value = ''; $('search-count').textContent = '';
  $('prev').disabled = number <= 1; $('next').disabled = !!state.count && number >= state.count;
  const query = $('search-query').value.trim() || null;
  try {
    const data = await api('page', {id: ident, page: number, dpi: Number($('dpi').value), query});
    if (sequence !== state.sequence || epoch !== state.documentEpoch) return;
    const image = new Image(); image.src = 'data:image/png;base64,' + data.png_base64;
    await image.decode();
    if (sequence !== state.sequence || epoch !== state.documentEpoch) return;
    const canvas = $('page-canvas');
    canvas.width = data.width_px; canvas.height = data.height_px;
    state.pageImage = image;
    const ctx = canvas.getContext('2d'); ctx.drawImage(image, 0, 0);
    const queryCurrent = queryEpoch === state.queryEpoch && query === ($('search-query').value.trim() || null);
    ctx.fillStyle = 'rgba(245,176,32,0.35)'; ctx.strokeStyle = 'rgba(178,112,5,0.8)'; ctx.lineWidth = 1;
    for (const match of queryCurrent ? data.search_matches || [] : []) {
      for (const rect of match.rectangles_px || []) {
        const [x0, y0, x1, y1] = rect;
        ctx.fillRect(x0, y0, x1 - x0, y1 - y0); ctx.strokeRect(x0, y0, x1 - x0, y1 - y0);
      }
    }
    canvas.hidden = false; $('page-empty').hidden = true; $('page-text').value = data.text || '';
    state.pageWidth = data.size[0]; applyZoom();
    state.count = data.page_count; $('page-count').textContent = '/ ' + data.page_count;
    $('page-number').max = data.page_count;
    $('page-label').textContent = '页标签：' + (data.page_label || '无');
    $('page-label').title = 'PDF 页标签：' + (data.page_label || '未设置') + '；物理页为 ' + number;
    $('identity').textContent = '当前 SHA-256：' + data.input_sha256;
    const dpi = data.effective_dpi || data.dpi;
    $('reader-status').textContent = data.width_px + ' × ' + data.height_px + ' · ' +
      data.rotation_degrees + '° · ' + Number(dpi).toFixed(dpi < 10 ? 2 : 0) + ' DPI' +
      (data.resolution_reduced ? '（已按预算降低清晰度，完整页面）' : '');
    $('search-count').textContent = query && queryCurrent ? data.search_matches.length + (data.search_truncated ? '+' : '') + ' 处' : '';
    $('prev').disabled = number <= 1; $('next').disabled = number >= data.page_count;
    for (const button of document.querySelectorAll('.thumbnail')) {
      const active = Number(button.dataset.page) === number;
      button.classList.toggle('current', active); button.setAttribute('aria-pressed', String(active));
    }
    renderBookmarks();
  } catch (error) {
    if (sequence !== state.sequence || epoch !== state.documentEpoch) return;
    $('page-empty').textContent = error.message;
    $('reader-status').textContent = '未完成读取'; $('identity').textContent = '本次页面读取失败，未显示旧页面';
    sourceFailure(error); notice(error.message, true);
  }
}
function applyZoom() {
  const mode = $('zoom').value, canvas = $('page-canvas');
  canvas.style.maxWidth = mode === 'fit' ? '100%' : 'none';
  canvas.style.width = mode === 'fit' ? '100%' : ((state.pageWidth || 595) * 96 / 72 * Number(mode) / 100) + 'px';
}
function renderBookmarks() {
  const data = state.navigation;
  if (!data) return;
  const query = $('bookmark-filter').value.trim().toLocaleLowerCase(), items = data.bookmarks;
  const byId = new Map(items.map((item, index) => [item.id || String(index), item]));
  const matches = new Set(), visible = new Set();
  items.forEach((item, index) => {
    if (query && !item.title.toLocaleLowerCase().includes(query)) return;
    const id = item.id || String(index); matches.add(id); visible.add(id);
    let parent = item.parent_id;
    const seen = new Set();
    while (parent && !seen.has(parent)) {
      seen.add(parent); visible.add(parent); parent = (byId.get(parent) || {}).parent_id;
    }
  });
  $('bookmarks').replaceChildren();
  items.forEach((item, index) => {
    const id = item.id || String(index);
    if (!visible.has(id)) return;
    const page = item.physical_page, b = el('button', item.title + (page ? ' · 第 ' + page + ' 页' : ' · 目标未解析'),
      'bookmark' + (query && !matches.has(id) ? ' ancestor' : '') + (page === state.page ? ' current' : ''));
    b.style.paddingLeft = (6 + Math.min(item.level, 7) * 11) + 'px';
    b.disabled = !page; b.dataset.bookmarkId = id;
    b.addEventListener('click', safe(() => loadPage(page))); $('bookmarks').append(b);
  });
  if (!visible.size) $('bookmarks').append(el('p', query ? '没有匹配的书签。' : '当前未发现可列出的书签。', 'muted'));
  if (data.truncated) $('bookmarks').append(el('p', '导航存在处理上限；当前列表不能视为完整结构检查。', 'muted'));
}
async function loadThumbnails() {
  if (!state.current || state.thumbnailBusy || !state.count) return;
  const epoch = state.documentEpoch, ident = state.current;
  state.thumbnailBusy = true; $('thumbnails-more').disabled = true;
  const first = state.thumbnailsLoaded + 1, last = Math.min(state.count, first + 11);
  let cursor = first;
  const buttons = new Map();
  for (let page = first; page <= last; page++) {
    const b = el('button', '正在读取…', 'thumbnail' + (page === state.page ? ' current' : ''));
    b.dataset.page = String(page); b.title = '物理页 ' + page;
    b.setAttribute('aria-label', '阅读物理页 ' + page); b.setAttribute('aria-pressed', String(page === state.page));
    b.addEventListener('click', safe(() => loadPage(page)));
    $('thumbnails').append(b); buttons.set(page, b);
  }
  const run = async () => {
    // Finish this bounded group when merely collapsed, so hidden placeholders
    // are not marked loaded without a request. Switching documents still stops
    // the old generation before another request is issued.
    while (cursor <= last && epoch === state.documentEpoch) {
      const number = cursor++, b = buttons.get(number);
      try {
        const data = await api('thumbnail', {id: ident, page: number});
        if (epoch !== state.documentEpoch) return;
        const image = el('img'); image.src = 'data:image/png;base64,' + data.png_base64; image.alt = '物理页 ' + number + ' 预览';
        b.replaceChildren(image, el('span', String(number)));
        if (data.page_label) b.append(el('small', '标签 ' + data.page_label));
      } catch (error) {
        if (epoch !== state.documentEpoch) return;
        b.replaceChildren(el('span', '第 ' + number + ' 页'), el('small', '预览未完成'));
        b.title = error.message; sourceFailure(error);
      }
    }
  };
  try {
    await Promise.allSettled([run(), run()]);
    if (epoch === state.documentEpoch) state.thumbnailsLoaded = last;
  } finally {
    if (epoch === state.documentEpoch) {
      state.thumbnailBusy = false; $('thumbnails-more').disabled = false;
      $('thumbnails-more').hidden = state.thumbnailsLoaded >= state.count;
      $('thumbnails-more').textContent = '继续加载 · ' + state.thumbnailsLoaded + ' / ' + state.count + ' 页';
    }
  }
}
function locateButton(page) {
  const button = el('button', '定位第 ' + page + ' 页');
  button.addEventListener('click', safe(() => loadPage(page))); return button;
}
function evidenceValue(value) {
  return typeof value === 'string' ? value : JSON.stringify(value, null, 2);
}
function evidenceBlock(evidence) {
  const details = el('details'), list = el('div', undefined, 'evidence-list');
  details.append(el('summary', '查看 ' + evidence.length + ' 条对象证据'));
  for (const entry of evidence) {
    const row = el('div', undefined, 'evidence-item'), dl = el('dl');
    const fields = [['类型', entry.kind], ['对象', entry.object_ref], ['物理页', entry.page], ['观察值', entry.value], ['说明', entry.note]];
    for (const [key, value] of fields) if (value !== null && value !== undefined) {
      dl.append(el('dt', key), el('dd', evidenceValue(value)));
    }
    row.append(dl); list.append(row);
  }
  const raw = el('details'); raw.append(el('summary', '原始证据 JSON'), el('pre', JSON.stringify(evidence, null, 2)));
  details.append(list, raw); return details;
}
function renderIssues() {
  const scan = state.details && state.details.scan;
  $('issues').replaceChildren(); $('issue-controls').hidden = !scan;
  if (!scan) { $('issues').append(el('p', '尚未扫描。空列表不等于通过。', 'empty-note')); return; }
  const evaluations = scan.rule_evaluations || [], findings = scan.findings || [];
  const grouped = new Map();
  for (const finding of findings) {
    if (!grouped.has(finding.rule_id)) grouped.set(finding.rule_id, []);
    grouped.get(finding.rule_id).push(finding);
  }
  const rank = item => item.status === 'FAIL' ? 0 : item.status === 'NOT_RUN' ? 1 :
    item.status === 'INDETERMINATE' ? (grouped.has(item.rule_id) ? 2 : 3) : item.status === 'PASS' ? 4 : 5;
  const ordered = [...evaluations].sort((a,b) => rank(a) - rank(b) ||
    a.rule_id.localeCompare(b.rule_id, undefined, {numeric: true}));
  const status = $('issue-status').value, query = $('issue-query').value.trim().toLocaleLowerCase();
  const filtered = ordered.filter(item => {
    const hasStatus = status === 'all' || (status === 'attention'
      ? ['FAIL','NOT_RUN','INDETERMINATE'].includes(item.status) : item.status === status);
    return hasStatus && (!query || (JSON.stringify(item) + JSON.stringify(grouped.get(item.rule_id) || []))
      .toLocaleLowerCase().includes(query));
  });
  const counts = key => evaluations.filter(e => e.status === key).length;
  $('issues').append(el('p', counts('FAIL') + ' 项问题 · ' + counts('INDETERMINATE') +
    ' 项无法判定 · ' + counts('NOT_RUN') + ' 项未运行。显示 ' + filtered.length + ' / ' + evaluations.length + ' 条规则。', 'issue-counts'));
  for (const evaluation of filtered) {
    const row = el('div', undefined, 'rule-row'), header = el('header');
    row.dataset.ruleId = evaluation.rule_id; row.dataset.status = evaluation.status;
    header.append(el('b', evaluation.rule_id), el('span', statusLabels[evaluation.status] || evaluation.status,
      'state ' + (evaluation.status === 'FAIL' ? 'fail' : evaluation.status === 'PASS' ? 'pass' : 'pending')));
    row.append(header);
    const entries = grouped.get(evaluation.rule_id) || [];
    for (const finding of entries) {
      if (finding.title) row.append(el('p', finding.title, 'rule-title'));
      row.append(el('p', findingLabels[finding.message] || finding.message));
      const evidence = finding.evidence || [], pages = [...new Set(evidence.map(e => e.page)
        .filter(page => Number.isInteger(page) && page > 0))].sort((a,b) => a-b);
      if (pages.length) {
        const links = el('div', undefined, 'evidence-pages');
        for (const page of pages) links.append(locateButton(page));
        row.append(links);
      }
      if (evidence.length) row.append(evidenceBlock(evidence));
    }
    row.append(el('p', reasonLabels[evaluation.reason] || evaluation.reason));
    $('issues').append(row);
  }
  if (!filtered.length) $('issues').append(el('p', '没有符合当前筛选条件的规则。可切回“全部规则”查看完整状态。', 'muted'));
}
function renderReport(items) {
  $('report-issues').replaceChildren();
  if (!items.length) {
    $('report-issues').append(el('p', '当前文件没有原报告路径候选。可导入报告；没有观察不等于通过。', 'empty-note'));
    return;
  }
  $('report-issues').append(el('h3', '原报告观察 · 独立保留', 'report-heading'),
    el('p', '仅按完整相对路径形成候选；未证明报告中的文件与当前版本字节相同。坐标也尚未核实。', 'muted'));
  for (const item of items) {
    const row = el('div', undefined, 'rule-row');
    row.append(el('b', item.rule_id + ' · ' + item.report_icon_status), el('p', item.raw_text));
    const raw = item.reported_page_raw || '', numbers = raw.match(/\d+/g) || [];
    if (numbers.length === 1 && Number(numbers[0]) > 0) row.append(locateButton(Number(numbers[0])));
    $('report-issues').append(row);
  }
}
async function loadDetails() {
  const ident = state.current, epoch = state.documentEpoch, detailEpoch = ++state.detailsEpoch;
  if (!ident) return;
  try {
    const data = await api('details', {id: ident});
    if (state.documentEpoch !== epoch || state.detailsEpoch !== detailEpoch) return;
    state.details = data; renderIssues(); renderReport(data.report_items);
  } catch (error) {
    if (state.documentEpoch !== epoch || state.detailsEpoch !== detailEpoch) return;
    state.details = null; renderIssues(); renderReport([]);
    $('issues').replaceChildren(el('p', error.message, 'empty-note')); sourceFailure(error);
  }
}
function snippetNode(snippet, query) {
  const small = el('small'), at = snippet.toLocaleLowerCase().indexOf(query.toLocaleLowerCase());
  if (at < 0) { small.textContent = snippet; return small; }
  small.append(document.createTextNode(snippet.slice(0, at)), el('mark', snippet.slice(at, at + query.length)),
    document.createTextNode(snippet.slice(at + query.length)));
  return small;
}
function renderSearch() {
  const search = state.search; if (!search) return;
  $('doc-search-heading').hidden = false; $('doc-search-results').replaceChildren();
  for (const match of search.matches) {
    const count = match.hit_count_exact === false ? '≥' + (match.hit_count_lower_bound || match.hit_count) : match.hit_count;
    const button = el('button', '第 ' + match.physical_page + ' 页' +
      (match.page_label ? ' · 标签 ' + match.page_label : '') + ' · ' + count + ' 处', 'search-hit');
    button.append(snippetNode(match.snippet || '', search.query));
    button.addEventListener('click', safe(() => loadPage(match.physical_page)));
    $('doc-search-results').append(button);
  }
  const incomplete = search.unsearched.length || search.capped.length;
  let summary = '已检索 ' + search.scanned + '/' + search.pageCount + ' 页，' + search.matches.length + ' 页有命中。';
  if (search.noText.length) summary += ' ' + search.noText.length + ' 页无可提取文本（未做 OCR）。';
  if (search.unsearched.length) summary += ' ' + search.unsearched.length + ' 页读取未完成。';
  if (search.capped.length) summary += ' ' + search.capped.length + ' 页命中数量达到上限，计数为下界。';
  if (search.nextPage) summary += ' 可继续检索第 ' + search.nextPage + ' 页起的后续页面。';
  else if (incomplete) summary += ' 存在未完成项，不能视为全量结果。';
  else summary += ' 已遍历全部页面的文本层；未进行 OCR。';
  $('search-results-summary').textContent = summary;
  $('search-more').hidden = !search.nextPage;
  $('search-more').textContent = search.nextPage ? '继续检索 · 从第 ' + search.nextPage + ' 页开始' : '检索结束';
  if (!search.matches.length) $('doc-search-results').append(el('p',
    search.nextPage || search.unsearched.length ? '本轮已读取页面中没有命中，尚不能判断整份文档。'
      : '可提取文本中没有命中；扫描或图片中的文字未参与检索。', 'muted'));
}
async function searchDocument(continuation = false) {
  if (!state.current || !$('search-query').value.trim() || state.searchBusy) return;
  const query = $('search-query').value.trim(), ident = state.current, docEpoch = state.documentEpoch;
  if (!continuation || !state.search || state.search.query !== query) {
    invalidateSearch();
    state.search = {query, matches: [], scanned: 0, visited: 0, pageCount: 0,
      noText: [], unsearched: [], capped: [], nextPage: 1, sha: null};
  }
  const epoch = state.searchEpoch, search = state.search, start = search.nextPage;
  if (!start) return;
  state.searchBusy = true; $('search-doc').disabled = true; $('search-more').disabled = true;
  tab('nav'); notice('正在检索当前文档的文本层；不会执行 OCR。');
  try {
    const data = await api('search', {id: ident, query, start_page: start, page_limit: 200});
    if (docEpoch !== state.documentEpoch || epoch !== state.searchEpoch) return;
    if (search.sha && search.sha !== data.source_sha256) throw new Error('Search identity mismatch');
    search.sha = data.source_sha256; search.pageCount = data.page_count;
    search.scanned += data.pages_scanned; search.visited += data.pages_visited;
    search.matches.push(...data.matches); search.noText.push(...data.pages_without_text);
    search.unsearched.push(...data.unsearched_pages); search.capped.push(...data.match_count_truncated_pages);
    search.nextPage = data.next_page;
    renderSearch(); notice($('search-results-summary').textContent);
  } catch (error) {
    if (docEpoch !== state.documentEpoch || epoch !== state.searchEpoch) return;
    sourceFailure(error); notice(error.message + '。本轮检索未完成，已有结果不能视为全量。', true);
  } finally {
    if (docEpoch === state.documentEpoch && epoch === state.searchEpoch) {
      state.searchBusy = false; $('search-doc').disabled = false; $('search-more').disabled = false;
    }
  }
}
async function startJob(kind, payload) {
  if (state.polling) return;
  state.polling = true; updateSelection();
  try {
    const answer = await api(kind, payload);
    await connectJob(answer.job_id);
  } catch (error) {
    // A lost response may follow a successfully accepted server job. Recover its
    // state before offering another command; never infer cancellation from HTTP.
    state.submissionUnknown = true; state.pollEpoch++;
    $('job-strip').hidden = false; $('resume-job').hidden = false;
    $('cancel-job').hidden = true; $('job-results').hidden = true;
    $('job-text').textContent = '任务提交结果待确认 · 请重新连接';
    try {
      const history = await api('history');
      reconcileHistory(history);
      if (state.lastJob) await connectJob(state.lastJob);
      else notice(error.message + '；服务器未发现任务，现可重新操作。', true);
    } catch (_) { connectionIssue(error.message + '；连接恢复前任务状态未知。'); }
    updateSelection();
  }
}
async function connectJob(ident) {
  const epoch = ++state.pollEpoch;
  state.lastJob = ident; state.polling = true; state.submissionUnknown = false;
  $('job-strip').hidden = false; $('job-results').hidden = true;
  $('cancel-job').hidden = false; $('resume-job').hidden = true;
  updateSelection(); await pollJob(ident, epoch);
}
async function pollJob(ident, epoch) {
  try {
    const job = await api('job', {id: ident});
    if (epoch !== state.pollEpoch) return;
    clearConnectionIssue();
    state.lastJobData = job;
    $('job-text').textContent = jobNames[job.kind] + ' · ' + job.done + '/' + job.total +
      (job.current ? ' · ' + job.current : '') + ' · ' + (jobStates[job.status] || job.status);
    $('job-progress').max = Math.max(1, job.total); $('job-progress').value = job.done;
    $('resume-job').hidden = true;
    if (running(job)) { setTimeout(() => pollJob(ident, epoch), 400); return; }
    state.polling = false; updateSelection();
    $('cancel-job').hidden = true; $('job-results').hidden = false;
    await refresh(); await loadDetails();
    if (epoch !== state.pollEpoch) return;
    if (job.kind === 'plan' || job.kind === 'apply') showJob(job);
    if (job.message) notice(job.message, true);
  } catch (error) {
    if (epoch !== state.pollEpoch) return;
    $('resume-job').hidden = false;
    $('job-text').textContent = '任务连接中断 · 完成状态待确认';
    connectionIssue(error.message + '。后台任务状态尚未确认，请重新连接进度。');
  }
}
function reconcileHistory(history) {
  // A successful history response resolves uncertainty even when no request was
  // accepted. Never repeat a mutation just because its response was lost.
  clearConnectionIssue(); state.submissionUnknown = false;
  const latest = history.jobs.find(job => job.id === history.active_job_id) || history.jobs[0];
  state.lastJob = latest ? latest.id : null;
  state.polling = !!history.active_job_id;
  if (!state.polling) state.pollEpoch++;
  $('job-strip').hidden = false;
  $('cancel-job').hidden = !state.polling;
  $('resume-job').hidden = !state.polling;
  $('job-results').hidden = state.polling || !latest;
  if (latest) {
    state.lastJobData = latest;
    $('job-text').textContent = jobNames[latest.kind] + ' · ' + latest.done + '/' + latest.total +
      ' · ' + (jobStates[latest.status] || latest.status);
    $('job-progress').max = Math.max(1, latest.total); $('job-progress').value = latest.done;
  } else {
    $('job-text').textContent = '未发现活动任务，可以重新开始。';
    $('job-progress').max = 1; $('job-progress').value = 0;
  }
  updateSelection();
}
function outcomeLabels(job) {
  const counts = job.counts || {};
  return [['成功', counts.succeeded], ['错误', counts.errors], ['已取消', counts.cancelled],
    ['未开始', counts.pending], ['已阻断', counts.blocked], ['无需处理', counts.skipped]]
    .filter(row => row[1] > 0);
}
function showJob(job) {
  const planning = job.kind === 'plan'; state.dialogJob = job; state.plan = job.can_apply ? job.id : null;
  $('dialog-title').textContent = planning ? '快速 Web 查看 · 修改前计划' : jobNames[job.kind] + ' · 任务结果';
  $('dialog-description').textContent = planning
    ? '检查每份文件后，再确认生成副本。只调整 PDF 存储结构；正文、文本、导航与全页图像仍须复验。签名、加密、表单、动态内容或附件会阻断重写。' +
      (job.status === 'COMPLETED_WITH_ERRORS' ? ' 本批有未完成项；仅下方身份已核实的合格文件可执行，其余项明确排除。' : '')
    : '成功副本保留相对路径并附 .ezctd.json 复验证据。错误、取消和未开始项分别保留；工作目录中的副本不是全量申报资料包，也不表示 CDE 已通过。';
  if (planning && job.status === 'CANCELLED') {
    $('dialog-description').textContent += ' 已取消计划不能执行；“重试”只处理未完成项。已完成规划的文件如需处理，请重新选择并生成计划。';
  }
  $('job-outcomes').replaceChildren();
  for (const [label, count] of outcomeLabels(job)) $('job-outcomes').append(el('span', label + ' ' + count, label === '错误' ? 'error' : ''));
  const table = el('table'), head = el('tr');
  for (const title of ['相对路径', '状态', '证据 / 原因']) head.append(el('th', title));
  const thead = el('thead'); thead.append(head); table.append(thead);
  const tbody = el('tbody');
  const invalidated = new Set(job.invalidated_plan_ids || []);
  const eligible = new Set(job.plan_eligible_ids || []);
  for (const row of job.results || []) {
    const tr = el('tr');
    if (row.status === 'ERROR') tr.classList.add('row-error');
    let label = {ELIGIBLE: '可生成副本', BLOCKED: '已阻断', NO_CHANGE_NEEDED: '无需重复处理',
      VERIFIED_COPY: '副本已复验', SCANNED: '本地检查已完成', ERROR: '未完成',
      CANCELLED: '已取消', NOT_STARTED: '未开始'}[row.eligibility || row.status] || row.status;
    let detail = row.message || (row.blockers || []).map(code => blockers[code] || code).join('；');
    if (row.proof) detail = row.proof.page_count + ' 页 · 150 DPI 全页像素/文本/结构复验一致 · ' + row.output_relative;
    else if (row.eligibility === 'ELIGIBLE') detail = row.page_count + ' 页 · 执行前再次检查 SHA-256';
    else if (row.status === 'NOT_STARTED') detail = '本次未开始处理；可在新任务中继续。';
    if (planning && invalidated.has(row.id)) {
      label = '计划失效'; detail = '源文件身份或上下文已变化；本项已排除，须重新打开资料并生成计划。';
      tr.classList.add('row-error');
    } else if (planning && row.eligibility === 'ELIGIBLE' && (!job.can_apply || !eligible.has(row.id))) {
      label = '预检时符合条件'; detail = row.page_count + ' 页 · 历史预检记录，本计划当前不能执行此项。';
    }
    tr.append(el('td', row.relative_path), el('td', label), el('td', detail || '—')); tbody.append(tr);
  }
  table.append(tbody); $('dialog-rows').replaceChildren(table);
  $('apply-plan').hidden = !job.can_apply;
  $('apply-plan').disabled = state.polling;
  $('apply-plan').textContent = '确认生成 ' + (job.eligible_count || 0) + ' 份副本';
  $('retry-job').hidden = !job.can_retry;
  $('retry-job').disabled = state.polling;
  $('retry-job').textContent = job.kind === 'apply'
    ? '为 ' + job.retryable_count + ' 个未完成项重新生成计划'
    : '重试 ' + job.retryable_count + ' 个未完成项';
  $('output-path').textContent = '工作目录：' + state.session.output_root +
    (job.output_relative_root ? '/' + job.output_relative_root : '') +
    (job.retry_of ? ' · 本任务承接 ' + job.retry_of.slice(0,8) : '');
  if (!$('task-dialog').open) $('task-dialog').showModal();
}
async function showHistory() {
  const history = await api('history');
  reconcileHistory(history);
  $('history-count').textContent = String(history.jobs.length);
  $('history-list').replaceChildren();
  if (!history.jobs.length) $('history-list').append(el('p', '本次会话还没有任务。扫描或生成计划后会在这里保留记录。', 'empty-note'));
  for (const job of history.jobs) {
    const button = el('button', undefined, 'history-job'); button.dataset.jobId = job.id;
    button.append(el('strong', jobNames[job.kind] + ' · ' + (jobStates[job.status] || job.status) + ' · ' + job.done + '/' + job.total),
      el('small', new Date(job.created_unix * 1000).toLocaleString('zh-CN', {hour12: false}) +
        ' · ' + outcomeLabels(job).map(row => row[0] + ' ' + row[1]).join(' · ')),
      el('small', '任务 ' + job.id.slice(0,8) + (job.retry_of ? ' · 承接 ' + job.retry_of.slice(0,8) : '') +
        (job.can_apply ? ' · ' + job.eligible_count + ' 份可确认生成副本' : '')));
    button.addEventListener('click', safe(async () => {
      $('history-dialog').close();
      if (running(job)) await connectJob(job.id);
      else showJob(await api('job', {id: job.id, include_results: true}));
    }));
    $('history-list').append(button);
  }
  if (!$('history-dialog').open) $('history-dialog').showModal();
}
$('file-filter').addEventListener('input', renderFiles);
$('file-status').addEventListener('change', renderFiles);
$('select-all').addEventListener('change', () => {
  for (const file of filteredFiles()) {
    if ($('select-all').checked) state.selected.add(file.id); else state.selected.delete(file.id);
  }
  renderFiles();
});
for (const button of document.querySelectorAll('[data-tab]')) {
  button.addEventListener('click', () => tab(button.dataset.tab));
  button.addEventListener('keydown', event => {
    const buttons = [...document.querySelectorAll('[data-tab]')], index = buttons.indexOf(button);
    let next = null;
    if (event.key === 'ArrowRight') next = (index + 1) % buttons.length;
    if (event.key === 'ArrowLeft') next = (index + buttons.length - 1) % buttons.length;
    if (event.key === 'Home') next = 0;
    if (event.key === 'End') next = buttons.length - 1;
    if (next !== null) { event.preventDefault(); tab(buttons[next].dataset.tab); buttons[next].focus(); }
  });
}
$('prev').addEventListener('click', safe(() => loadPage(state.page - 1)));
$('next').addEventListener('click', safe(() => loadPage(state.page + 1)));
$('page-number').addEventListener('change', safe(() => loadPage(Number($('page-number').value))));
$('zoom').addEventListener('change', applyZoom);
$('dpi').addEventListener('change', safe(() => loadPage(state.page)));
$('search-page').addEventListener('click', safe(() => loadPage(state.page)));
$('search-query').addEventListener('input', queryChanged);
$('search-query').addEventListener('keydown', safe(event => {
  if (event.key === 'Enter') return event.shiftKey ? searchDocument() : loadPage(state.page);
}));
$('search-doc').addEventListener('click', safe(() => searchDocument()));
$('search-more').addEventListener('click', safe(() => searchDocument(true)));
$('clear-search').addEventListener('click', safe(() => {
  $('search-query').value = ''; queryChanged(); return loadPage(state.page);
}));
$('bookmark-filter').addEventListener('input', renderBookmarks);
$('show-thumbnails').addEventListener('click', safe(async () => {
  $('thumbnail-panel').hidden = !$('thumbnail-panel').hidden;
  $('show-thumbnails').setAttribute('aria-expanded', String(!$('thumbnail-panel').hidden));
  if (!$('thumbnail-panel').hidden && !state.thumbnailsLoaded) await loadThumbnails();
}));
$('thumbnails-more').addEventListener('click', safe(loadThumbnails));
$('issue-status').addEventListener('change', renderIssues);
$('issue-query').addEventListener('input', renderIssues);
$('focus-mode').addEventListener('click', () => {
  const focused = document.body.classList.toggle('reading-focus');
  $('focus-mode').textContent = focused ? '退出专注' : '专注阅读';
  $('focus-mode').setAttribute('aria-pressed', String(focused));
});
$('scan-all').addEventListener('click', safe(() => startJob('scan', {ids: state.files.map(file => file.id)})));
$('scan-selected').addEventListener('click', safe(() => startJob('scan', {ids: [...state.selected]})));
$('plan').addEventListener('click', safe(() => startJob('plan', {ids: [...state.selected]})));
$('cancel-job').addEventListener('click', safe(async () => {
  await api('cancel', {id: state.lastJob}); notice('已请求取消；尚未完成复验的 PDF 不会发布。');
}));
$('resume-job').addEventListener('click', safe(async () => {
  const data = await api('history');
  reconcileHistory(data);
  if (state.lastJob) await connectJob(state.lastJob);
  else notice('未发现活动任务，操作已恢复。');
}));
$('job-results').addEventListener('click', safe(async () => showJob(await api('job', {id: state.lastJob, include_results: true}))));
$('history').addEventListener('click', safe(showHistory));
$('close-history').addEventListener('click', () => $('history-dialog').close());
$('close-dialog').addEventListener('click', () => $('task-dialog').close());
$('apply-plan').addEventListener('click', safe(async () => {
  const plan = state.plan; if (!plan) return;
  $('task-dialog').close(); await startJob('apply', {plan_id: plan, confirmed: true});
}));
$('retry-job').addEventListener('click', safe(async () => {
  const job = state.dialogJob; if (!job || !job.can_retry) return;
  $('task-dialog').close(); await startJob('retry', {id: job.id});
}));
$('save-context').addEventListener('click', safe(async () => {
  if (!state.current) return;
  const id = state.current, epoch = state.documentEpoch;
  const context = {node_id: $('node-id').value.trim(), document_role: $('document-role').value, language: $('language').value};
  for (const key of Object.keys(context)) if (!context[key]) delete context[key];
  await api('context', {id, context}); await refresh();
  if (epoch !== state.documentEpoch) return;
  $('context-summary').textContent = context.node_id || '待确认'; $('context-details').open = false;
  await loadDetails(); notice('上下文已更新；旧扫描和修改计划不再沿用，请重新检查。');
}));
$('copy-text').addEventListener('click', safe(async () => {
  await navigator.clipboard.writeText($('page-text').value); notice('当前页提取文本已复制。');
}));
$('import-report').addEventListener('click', () => $('report-file').click());
$('report-file').addEventListener('change', safe(async event => {
  const file = event.target.files[0]; if (!file) return;
  if (file.size > 5 * 1024 * 1024) throw new Error('界面报告导入限 5 MiB；更大文件使用命令行导入。');
  const bytes = new Uint8Array(await file.arrayBuffer()), parts = [];
  for (let i = 0; i < bytes.length; i += 32768) parts.push(String.fromCharCode(...bytes.subarray(i, i + 32768)));
  const result = await api('report', {report_base64: btoa(parts.join(''))});
  await refresh(); await loadDetails(); tab('report');
  const b = result.binding_summary;
  notice('原报告已作为数据导入：' + b.matched_observations + ' 条路径候选，' +
    b.unmatched_observations + ' 条未提供或未映射。历史 PDF 字节身份尚未证明。' +
    (result.parse_state !== 'PARSED_COUNTS_RECONCILED' ? ' 报告解析不完整，不能视为全量导入。' : ''));
  event.target.value = '';
}));
document.addEventListener('keydown', safe(event => {
  if ((event.ctrlKey || event.metaKey) && event.key === 'f') {
    event.preventDefault(); $('search-query').focus(); return;
  }
  if (event.altKey && !event.ctrlKey && !event.metaKey && !document.querySelector('dialog[open]')) {
    if (event.key === 'ArrowRight') { event.preventDefault(); return loadPage(state.page + 1); }
    if (event.key === 'ArrowLeft') { event.preventDefault(); return loadPage(state.page - 1); }
  }
}));
safe(async () => {
  await refresh(); tab('issues');
  notice('选择文件阅读或扫描。所有处理留在本机；上下文与本地检查由当前资料确定。');
  const first = state.files.find(file => !/corrupt|broken|locked|password/i.test(file.relative_path));
  if (first) await openDocument(first.id);
  if (state.session.active_job_id) await connectJob(state.session.active_job_id);
})();
