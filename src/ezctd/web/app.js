'use strict';
const $ = id => document.getElementById(id);
const token = new URLSearchParams(location.hash.slice(1)).get('key');
history.replaceState(null, '', '/');
const state = {files: [], selected: new Set(), current: null, page: 1, count: 0,
  sequence: 0, lastJob: null, plan: null, session: null, polling: false};
const statusLabels = {PASS: '本地条件满足', FAIL: '发现问题', NOT_APPLICABLE: '不适用',
  INDETERMINATE: '无法判定', NOT_RUN: '未运行'};
const blockers = {SIGNATURE_SIGNAL: '发现数字签名信号', DOCUMENT_PERMISSIONS_SIGNAL: '存在文档权限信号',
  ENCRYPTED_OR_PERMISSION_RESTRICTED: '加密或权限限制', PASSWORD_REQUIRED: '需要密码',
  INTERACTIVE_FORM_OR_PORTFOLIO_NOT_SUPPORTED: '表单或文档组合不在本次处理范围',
  ACTIVE_CONTENT_NOT_SUPPORTED: '动态内容需单独复核', ATTACHMENTS_NOT_SUPPORTED_FOR_REWRITE: '含附件，暂不重写',
  SOURCE_SYNTAX_WARNINGS: '源文件结构警告', PAGE_LIMIT_OR_EMPTY_DOCUMENT: '页数超限或空文档'};

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
async function api(route, payload = {}) {
  if (!token) throw new Error('本地会话凭证缺失。请从启动器给出的完整地址重新打开。');
  const response = await fetch('/api/' + route, {method: 'POST', cache: 'no-store', credentials: 'omit',
    headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + token}, body: JSON.stringify(payload)});
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || '操作失败');
  return body;
}
function safe(action) {
  return async (...args) => { try { await action(...args); } catch (error) { notice(error.message, true); } };
}
function tab(name) {
  for (const button of document.querySelectorAll('[data-tab]')) {
    const active = button.dataset.tab === name;
    button.classList.toggle('active', active);
    button.setAttribute('aria-selected', String(active));
    $('tab-' + button.dataset.tab).hidden = !active;
  }
}
async function refresh() {
  const data = await api('session'); state.session = data; state.files = data.files;
  $('root-name').textContent = data.root_name;
  $('summary').textContent = `${data.files.length} 份 PDF · 仅处理已提供的临床资料 · 无需 XML`;
  $('file-count').textContent = String(data.files.length);
  $('output-path').textContent = '工作目录：' + data.output_root;
  renderFiles();
}
function filteredFiles() {
  const q = $('file-filter').value.toLocaleLowerCase();
  return state.files.filter(file => file.relative_path.toLocaleLowerCase().includes(q));
}
function renderFiles() {
  const list = $('files'); list.replaceChildren();
  for (const file of filteredFiles()) {
    const row = el('div', undefined, 'file-row' + (file.id === state.current ? ' selected' : ''));
    const check = document.createElement('input'); check.type = 'checkbox';
    check.checked = state.selected.has(file.id); check.setAttribute('aria-label', '勾选 ' + file.relative_path);
    check.addEventListener('change', () => { if (check.checked) state.selected.add(file.id); else state.selected.delete(file.id); updateSelection(); });
    const button = el('button', undefined, 'file-open');
    button.title = file.relative_path;
    button.setAttribute('aria-pressed', String(file.id === state.current));
    const parts = file.relative_path.split('/');
    button.append(el('strong', parts.at(-1)), el('small', parts.slice(0, -1).join('/') || '输入根目录'));
    button.append(el('small', `${Math.max(1, Math.round(file.size / 1024))} KB${file.scanned ? ' · 已有本地检查' : ''}`));
    if (file.report_count) button.append(el('small', `${file.report_count} 条原报告观察（路径候选）`, 'tag'));
    button.addEventListener('click', safe(() => openDocument(file.id)));
    row.append(check, button); list.append(row);
  }
  updateSelection();
}
function updateSelection() {
  $('selected-count').textContent = String(state.selected.size);
  $('plan').disabled = state.selected.size === 0 || state.polling;
  $('scan-all').disabled = state.polling || state.files.length === 0;
  const visible = filteredFiles();
  $('select-all').checked = visible.length > 0 && visible.every(file => state.selected.has(file.id));
}
async function openDocument(ident) {
  state.current = ident; state.page = 1; state.count = 0;
  $('search-query').value = ''; $('doc-search-results').replaceChildren();
  $('doc-search-heading').hidden = true;
  const file = state.files.find(item => item.id === ident);
  $('document-name').textContent = file.relative_path;
  $('document-name').title = file.relative_path;
  $('node-id').value = file.context.node_id || '';
  $('document-role').value = file.context.document_role || '';
  $('language').value = file.context.language || '';
  $('bookmarks').replaceChildren(el('p', '正在读取书签…', 'muted'));
  renderFiles();
  const navSeq = state.sequence + 1;
  api('navigation', {id: ident}).then(data => {
    if (state.current !== ident || navSeq > state.sequence) return;
    $('bookmarks').replaceChildren();
    for (const item of data.bookmarks) {
      const b = el('button', item.title + (item.physical_page ? ` · 第 ${item.physical_page} 页` : ' · 目标未解析'), 'bookmark');
      b.style.paddingLeft = (6 + Math.min(item.level, 5) * 12) + 'px';
      b.disabled = !item.physical_page;
      b.addEventListener('click', safe(() => loadPage(item.physical_page)));
      $('bookmarks').append(b);
    }
    if (!data.bookmarks.length) $('bookmarks').append(el('p', '当前未发现可列出的书签。', 'muted'));
    if (data.truncated) $('bookmarks').append(el('p', '书签列表达到显示上限，并非完整。', 'muted'));
  }).catch(error => { if (state.current === ident) $('bookmarks').replaceChildren(el('p', error.message, 'muted')); });
  await Promise.allSettled([loadPage(1), loadDetails()]);
}
async function loadPage(number) {
  if (!state.current) return;
  if (!Number.isInteger(number) || number < 1 || (state.count && number > state.count)) return;
  const sequence = ++state.sequence, ident = state.current;
  state.page = number; $('page-number').value = number;
  $('reader-status').textContent = '正在读取';
  $('page-empty').textContent = '正在解析页面…'; $('page-empty').hidden = false;
  $('page-canvas').hidden = true; $('page-text').value = ''; $('search-count').textContent = '';
  const query = $('search-query').value.trim() || null;
  try {
    const data = await api('page', {id: ident, page: number, dpi: Number($('dpi').value), query});
    if (sequence !== state.sequence) return;
    const image = new Image(); image.src = 'data:image/png;base64,' + data.png_base64;
    await image.decode();
    if (sequence !== state.sequence) return;
    const canvas = $('page-canvas'); canvas.width = data.width_px; canvas.height = data.height_px;
    const ctx = canvas.getContext('2d'); ctx.drawImage(image, 0, 0);
    ctx.fillStyle = 'rgba(245, 176, 32, 0.35)'; ctx.strokeStyle = 'rgba(192, 112, 0, 0.8)'; ctx.lineWidth = 1;
    for (const match of data.search_matches || []) for (const rect of match.rectangles_px || []) {
      const [x0, y0, x1, y1] = rect; ctx.fillRect(x0, y0, x1 - x0, y1 - y0); ctx.strokeRect(x0, y0, x1 - x0, y1 - y0);
    }
    canvas.hidden = false; $('page-empty').hidden = true;
    $('page-text').value = data.text || '';
    state.pageWidth = data.size[0]; applyZoom();
    state.count = data.page_count; $('page-count').textContent = '/ ' + data.page_count;
    $('page-number').max = data.page_count;
    $('page-label').textContent = '页标签：' + (data.page_label || '无');
    $('identity').textContent = '当前 SHA-256：' + data.input_sha256;
    $('reader-status').textContent = `${data.width_px} × ${data.height_px} · ${data.rotation_degrees}°`;
    $('search-count').textContent = query ? `${data.search_matches.length}${data.search_truncated ? '+' : ''} 处` : '';
    $('prev').disabled = number <= 1; $('next').disabled = number >= data.page_count;
  } catch (error) {
    if (sequence !== state.sequence) return;
    $('page-empty').textContent = error.message;
    $('reader-status').textContent = '未完成读取'; $('identity').textContent = '本次页面读取失败，未显示旧页面';
    notice(error.message, true);
  }
}
function applyZoom() {
  const mode = $('zoom').value, canvas = $('page-canvas');
  canvas.style.maxWidth = mode === 'fit' ? '100%' : 'none';
  canvas.style.width = mode === 'fit' ? '100%' : ((state.pageWidth || 595) * 96 / 72 * Number(mode) / 100) + 'px';
}
function locateButton(page) {
  const button = el('button', `定位第 ${page} 页`);
  button.addEventListener('click', safe(() => loadPage(page)));
  return button;
}
async function loadDetails() {
  const ident = state.current; if (!ident) return;
  try {
    const data = await api('details', {id: ident});
    if (state.current !== ident) return;
    $('issues').replaceChildren(); $('report-issues').replaceChildren();
    if (!data.scan) $('issues').append(el('p', '尚未扫描。空列表不等于通过。', 'muted'));
    else {
      $('issues').append(el('h3', '本地逐规则检查'));
      for (const evaluation of data.scan.rule_evaluations || []) {
        const row = el('div', undefined, 'rule-row');
        const heading = el('header');
        heading.append(el('b', evaluation.rule_id), el('span', statusLabels[evaluation.status] || evaluation.status,
          'state ' + (evaluation.status === 'FAIL' ? 'fail' : evaluation.status === 'PASS' ? 'pass' : 'pending')));
        row.append(heading, el('p', evaluation.reason));
        const finding = (data.scan.findings || []).find(item => item.rule_id === evaluation.rule_id);
        if (finding) {
          row.append(el('p', finding.message));
          for (const e of finding.evidence || []) {
            if (Number.isInteger(e.page) && e.page > 0) row.append(locateButton(e.page));
          }
          const detail = el('details'); detail.append(el('summary', '查看对象证据'), el('pre', JSON.stringify(finding.evidence, null, 2)));
          row.append(detail);
        }
        $('issues').append(row);
      }
    }
    if (data.report_items.length) {
      $('report-issues').append(el('h3', '原报告观察 · 独立保留', 'report-heading'),
        el('p', '仅按完整相对路径形成候选；未证明报告中的文件与当前版本字节相同。坐标也尚未核实。', 'muted'));
      for (const item of data.report_items) {
        const row = el('div', undefined, 'rule-row');
        row.append(el('b', item.rule_id + ' · ' + item.report_icon_status), el('p', item.raw_text));
        const raw = item.reported_page_raw || '', numbers = raw.match(/\d+/g) || [];
        if (numbers.length === 1) row.append(locateButton(Number(numbers[0])));
        $('report-issues').append(row);
      }
    }
  } catch (error) {
    if (state.current === ident) $('issues').replaceChildren(el('p', error.message, 'muted'));
  }
}
async function searchDocument() {
  if (!state.current || !$('search-query').value.trim()) return;
  const ident = state.current, query = $('search-query').value.trim();
  $('search-doc').disabled = true; notice('正在检索当前文档的文本层；不会执行 OCR。');
  try {
    const data = await api('search', {id: ident, query});
    if (state.current !== ident) return;
    tab('nav'); $('doc-search-heading').hidden = false; $('doc-search-results').replaceChildren();
    for (const match of data.matches) {
      const button = el('button', `第 ${match.physical_page} 页 · ${match.hit_count} 处`, 'search-hit');
      button.append(el('small', match.snippet.slice(0, 140)));
      button.addEventListener('click', safe(() => { $('search-query').value = query; return loadPage(match.physical_page); }));
      $('doc-search-results').append(button);
    }
    notice(`已检索 ${data.pages_scanned}/${data.page_count} 页，${data.matches.length} 页有命中。` +
      (data.truncated ? '达到处理上限，结果不完整。' : '未进行 OCR。'));
  } finally { $('search-doc').disabled = false; }
}
async function startJob(kind, payload) {
  const answer = await api(kind, payload);
  state.lastJob = answer.job_id; state.polling = true;
  $('job-strip').hidden = false; $('job-results').hidden = true; $('cancel-job').hidden = false;
  updateSelection();
  await pollJob(answer.job_id);
}
async function pollJob(ident) {
  try {
    const job = await api('job', {id: ident}); state.lastJobData = job;
    const names = {scan: '批量检查', plan: '副本处理计划', apply: '生成与复验副本'};
    $('job-text').textContent = `${names[job.kind]} · ${job.done}/${job.total} ${job.current || ''}`;
    $('job-progress').max = Math.max(1, job.total); $('job-progress').value = job.done;
    if (job.status === 'QUEUED' || job.status === 'RUNNING' || job.status === 'FINALIZING') {
      setTimeout(() => pollJob(ident), 400); return;
    }
    state.polling = false; updateSelection();
    $('cancel-job').hidden = true; $('job-results').hidden = false;
    $('job-text').textContent += ' · ' + ({COMPLETED: '任务完成', COMPLETED_WITH_ERRORS: '部分未完成',
      CANCELLED: '已取消', ERROR: '任务失败'}[job.status] || job.status);
    await refresh(); await loadDetails();
    if (job.kind === 'plan' || job.kind === 'apply') showJob(job);
    if (job.message) notice(job.message, true);
  } catch (error) { state.polling = false; updateSelection(); notice(error.message, true); }
}
function showJob(job) {
  const planning = job.kind === 'plan'; state.plan = planning ? job.id : null;
  $('dialog-title').textContent = planning ? '快速 Web 查看 · 修改前计划' : '任务结果';
  $('dialog-description').textContent = planning
    ? '只重排 PDF 存储结构，不改变正文。签名、加密、表单、动态内容或附件将阻断重写；执行前后核验原件身份、对象结构、文本和全页图像。本操作不自动认定监管必要性。'
    : '成功副本保留相对路径，每份附有 .ezctd.json 复验证据。失败项没有成功输出；此文件夹不是全量申报资料包，也不表示 CDE 已通过。';
  const table = el('table'), head = el('tr');
  for (const title of ['相对路径', '状态', '证据 / 原因']) head.append(el('th', title));
  table.append(head);
  let eligible = 0;
  for (const row of job.results) {
    const tr = el('tr');
    const label = {ELIGIBLE: '可生成副本', BLOCKED: '已阻断', NO_CHANGE_NEEDED: '无需重复处理',
      VERIFIED_COPY: '副本已复验', SCANNED: '本地检查已完成', ERROR: '未完成', CANCELLED: '已取消'}[row.eligibility || row.status] || row.status;
    if (row.eligibility === 'ELIGIBLE') eligible += 1;
    let detail = row.message || (row.blockers || []).map(code => blockers[code] || code).join('；');
    if (row.proof) detail = `${row.proof.page_count} 页 · 150 DPI 全页像素/文本/结构复验一致 · ${row.output_relative}`;
    else if (row.eligibility === 'ELIGIBLE') detail = `${row.page_count} 页 · 执行前再次检查 SHA-256`;
    tr.append(el('td', row.relative_path), el('td', label), el('td', detail || '—')); table.append(tr);
  }
  $('dialog-rows').replaceChildren(table);
  $('apply-plan').hidden = !planning || eligible === 0 || job.status !== 'COMPLETED';
  $('apply-plan').textContent = `确认生成 ${eligible} 份副本`;
  $('output-path').textContent = '工作目录：' + state.session.output_root +
    (job.output_relative_root ? '/' + job.output_relative_root : '');
  $('task-dialog').showModal();
}
$('file-filter').addEventListener('input', renderFiles);
$('select-all').addEventListener('change', () => {
  for (const file of filteredFiles()) if ($('select-all').checked) state.selected.add(file.id); else state.selected.delete(file.id);
  renderFiles();
});
for (const button of document.querySelectorAll('[data-tab]')) button.addEventListener('click', () => tab(button.dataset.tab));
$('prev').addEventListener('click', safe(() => loadPage(state.page - 1)));
$('next').addEventListener('click', safe(() => loadPage(state.page + 1)));
$('page-number').addEventListener('change', safe(() => loadPage(Number($('page-number').value))));
$('zoom').addEventListener('change', applyZoom);
$('dpi').addEventListener('change', safe(() => loadPage(state.page)));
$('search-page').addEventListener('click', safe(() => loadPage(state.page)));
$('search-query').addEventListener('keydown', safe(event => { if (event.key === 'Enter') return loadPage(state.page); }));
$('search-doc').addEventListener('click', safe(searchDocument));
$('scan-all').addEventListener('click', safe(() => startJob('scan', {ids: state.files.map(file => file.id)})));
$('plan').addEventListener('click', safe(() => startJob('plan', {ids: [...state.selected]})));
$('cancel-job').addEventListener('click', safe(async () => { await api('cancel', {id: state.lastJob}); notice('已请求取消；未完成复验的 PDF 不会发布。'); }));
$('job-results').addEventListener('click', safe(async () => showJob(await api('job', {id: state.lastJob, include_results: true}))));
$('close-dialog').addEventListener('click', () => $('task-dialog').close());
$('apply-plan').addEventListener('click', safe(async () => {
  const planId = state.plan; $('task-dialog').close();
  await startJob('apply', {plan_id: planId, confirmed: true});
}));
$('save-context').addEventListener('click', safe(async () => {
  if (!state.current) return;
  const context = {node_id: $('node-id').value.trim(), document_role: $('document-role').value, language: $('language').value};
  for (const key of Object.keys(context)) if (!context[key]) delete context[key];
  await api('context', {id: state.current, context}); await refresh(); await loadDetails();
  notice('上下文已更新；旧扫描和修改计划不再沿用，请重新检查。');
}));
$('copy-text').addEventListener('click', safe(async () => { await navigator.clipboard.writeText($('page-text').value); notice('当前页提取文本已复制。'); }));
$('import-report').addEventListener('click', () => $('report-file').click());
$('report-file').addEventListener('change', safe(async event => {
  const file = event.target.files[0]; if (!file) return;
  if (file.size > 5 * 1024 * 1024) throw new Error('界面报告导入限 5 MiB；更大文件使用命令行导入。');
  const bytes = new Uint8Array(await file.arrayBuffer()), parts = [];
  for (let i = 0; i < bytes.length; i += 32768) parts.push(String.fromCharCode(...bytes.subarray(i, i + 32768)));
  const result = await api('report', {report_base64: btoa(parts.join(''))});
  await refresh(); await loadDetails();
  const b = result.binding_summary;
  notice(`原报告已作为数据导入：${b.matched_observations} 条路径候选，${b.unmatched_observations} 条未提供或未映射。历史 PDF 字节身份尚未证明。` +
    (result.parse_state !== 'PARSED_COUNTS_RECONCILED' ? ' 报告解析不完整，不能视为全量导入。' : ''));
  event.target.value = '';
}));
document.addEventListener('keydown', event => { if ((event.ctrlKey || event.metaKey) && event.key === 'f') { event.preventDefault(); $('search-query').focus(); } });
safe(async () => { await refresh(); notice('先使用合成或可丢弃副本。当前不执行 OCR、字体替换、附件删除或跨文件链接改写。');
  const first = state.files.find(file => !/corrupt|broken|locked|password/i.test(file.relative_path));
  if (first) await openDocument(first.id);
})();
