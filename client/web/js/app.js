// app.js — fluxo do usuário final na web pública (Locutus cego).
//
// I) chave (nome.chave) -> Iniciar; II) combobox de workflows + criar;
// III) lista de ocorrências (lida do índice publicado pelo núcleo no MySQL);
// IV) popup de nova ocorrência com form dinâmico (schema de inputs do catálogo);
// V) salvar fecha o popup e atualiza a lista; VI) duplo-clique abre o detalhe
// (estrutograma Nassi colorido). Toda cifra/decifra é aqui; o PHP só vê blobs.

import * as C from './myass-crypto.js?v=2';

let secret = null;
let workflows = [];                 // [{hash, label, versao, inputs:{nome:{tipo,obrigatorio}}}]
let detailOcc = null;               // occ_id aberto no modal de detalhe

const $ = id => document.getElementById(id);
const log = msg => { $('status').textContent = msg; };
const show = (id, on) => $(id).classList.toggle('hidden', !on);
const el = (tag, cls, txt) => { const e = document.createElement(tag); if (cls) e.className = cls; if (txt != null) e.textContent = txt; return e; };

// ---- transporte (blobs no Locutus) -----------------------------------
async function getBlob(addr) {
  const r = await fetch('/' + addr, { method: 'GET' });
  if (r.status === 404) return null;
  if (!r.ok) throw new Error('GET ' + addr + ' -> ' + r.status);
  return new Uint8Array(await r.arrayBuffer());
}
async function putBlob(addr, bytes) {
  const r = await fetch('/' + addr, { method: 'PUT', body: bytes });
  if (!r.ok && r.status !== 204) throw new Error('PUT ' + addr + ' -> ' + r.status);
}

// ---- I — iniciar: carrega catálogo e o painel ------------------------
async function iniciar() {
  const raw = $('chave').value.trim();
  const hex = (raw.includes('.') ? raw.slice(raw.lastIndexOf('.') + 1) : raw).trim();
  if (!/^[0-9a-fA-F]{64}$/.test(hex)) { log('chave inválida (use nome.chave ou 64 hex).'); return; }
  secret = C.hexToBytes(hex);
  try {
    const blob = await getBlob(C.catalogAddress(secret));
    if (!blob) { log('nenhum catálogo para esta chave (ainda).'); return; }
    const cat = JSON.parse(C.fromUtf8(C.openCatalog(C.catalogKey(secret), blob)));
    workflows = Array.isArray(cat) ? cat : (cat.workflows || []);
    $('client-name').textContent = (Array.isArray(cat) ? '' : (cat.name || '')) || 'Meus workflows';
  } catch (e) { log('falha ao decifrar o catálogo (chave errada?): ' + e); return; }

  const sel = $('workflows');
  sel.innerHTML = '';
  for (const wf of workflows) {
    const o = el('option'); o.value = wf.hash; o.textContent = `${wf.label} (${wf.versao || ''})`;
    sel.appendChild(o);
  }
  show('login', false); show('main', true);
  await carregarOcorrencias();
  log(`${workflows.length} workflow(s) disponível(is).`);
}

// ---- III — lista de ocorrências (do índice no Locutus) ---------------
async function carregarOcorrencias() {
  let lista = [];
  try {
    const blob = await getBlob(C.occIndexAddress(secret));
    if (blob) lista = JSON.parse(C.fromUtf8(C.openOccIndex(C.occIndexKey(secret), blob)));
  } catch (e) { log('falha ao ler ocorrências: ' + e); return; }
  // limpa e preenche no MESMO tick (sem await no meio): duas chamadas concorrentes
  // (ex.: clicar Iniciar/Atualizar 2×) não duplicam linhas — a última vence.
  const tbody = $('occ-rows'); tbody.innerHTML = '';
  for (const o of lista) {
    const tr = el('tr', 'occ-row');
    tr.appendChild(el('td', null, o.occurrence_id));
    tr.appendChild(el('td', null, o.workflow || ''));
    const td = el('td'); const b = el('span', 'badge ' + (statusClass(o.status) || ''), o.status); td.appendChild(b); tr.appendChild(td);
    tr.addEventListener('dblclick', () => abrirDetalhe(o.occurrence_id));
    tbody.appendChild(tr);
  }
}

// ---- IV — popup nova ocorrência (form dinâmico) ----------------------
function abrirNova() {
  const wf = workflows.find(w => w.hash === $('workflows').value);
  if (!wf) { log('selecione um workflow.'); return; }
  $('new-title').textContent = `Nova ocorrência — ${wf.label}`;
  const form = $('new-form'); form.innerHTML = ''; form.dataset.hash = wf.hash;
  const schema = wf.inputs || {};
  if (!Object.keys(schema).length) {
    form.appendChild(el('p', null, 'Este workflow não declara entradas.'));
  }
  for (const [nome, spec] of Object.entries(schema)) {
    const tipo = (spec && spec.tipo) || 'str';
    const lbl = el('label', null, `${nome}${spec && spec.obrigatorio ? ' *' : ''} (${tipo})`);
    form.appendChild(lbl);
    let inp;
    if (tipo === 'bool') { inp = el('input'); inp.type = 'checkbox'; inp.style.width = 'auto'; }
    else if (tipo === 'int' || tipo === 'float') { inp = el('input'); inp.type = 'number'; if (tipo === 'float') inp.step = 'any'; }
    else if (tipo === 'list' || tipo === 'dict') { inp = el('textarea'); inp.rows = 3; inp.placeholder = tipo === 'list' ? '["..."]' : '{"...": "..."}'; }
    else { inp = el('input'); inp.type = 'text'; }
    inp.dataset.nome = nome; inp.dataset.tipo = tipo;
    form.appendChild(inp);
  }
  $('new-status').textContent = '';
  show('modal-new', true);
}

function coletarInputs() {
  const out = {};
  for (const inp of $('new-form').querySelectorAll('[data-nome]')) {
    const nome = inp.dataset.nome, tipo = inp.dataset.tipo;
    if (tipo === 'bool') { out[nome] = inp.checked; continue; }
    const v = inp.value.trim();
    if (v === '') continue;                       // vazio: omite (validação é no núcleo)
    if (tipo === 'int') out[nome] = parseInt(v, 10);
    else if (tipo === 'float') out[nome] = parseFloat(v);
    else if (tipo === 'list' || tipo === 'dict') out[nome] = JSON.parse(v);
    else out[nome] = v;
  }
  return out;
}

// ---- V — salvar: deposita o pedido, fecha, atualiza ------------------
async function salvarNova() {
  let inputs;
  try { inputs = coletarInputs(); }
  catch (e) { $('new-status').textContent = 'JSON inválido em algum campo: ' + e; return; }
  const workflow_hash = $('new-form').dataset.hash;
  const request_id = crypto.randomUUID();
  const pedido = C.utf8(JSON.stringify({ request_id, action: 'start_occurrence', workflow_hash, inputs }));
  try {
    await putBlob(C.requestAddress(secret), C.sealRequest(C.requestKey(secret), pedido));
  } catch (e) { $('new-status').textContent = 'falha ao enviar: ' + e; return; }
  show('modal-new', false);
  log('pedido enviado; aguardando o núcleo registrar a ocorrência…');
  await aguardarResposta(request_id);
  await carregarOcorrencias();
}

// aguarda a resposta do núcleo a este request_id (erro de validação aparece aqui).
async function aguardarResposta(request_id, tentativas = 20) {
  const addr = C.responseAddress(secret), key = C.responseKey(secret);
  for (let i = 0; i < tentativas; i++) {
    const blob = await getBlob(addr);
    if (blob) {
      try {
        const resp = JSON.parse(C.fromUtf8(C.openResponse(key, blob)));
        if (resp.request_id === request_id) {
          await fetch('/' + addr, { method: 'DELETE' });   // consome o slot
          const b = resp.body || {};
          log(b.erro ? ('erro: ' + b.erro) : 'ocorrência registrada.');
          return;
        }
      } catch { /* não é nossa / ainda não decifra */ }
    }
    await new Promise(r => setTimeout(r, 1500));
  }
  log('ocorrência enviada (resposta ainda não chegou; use Atualizar).');
}

// ---- VI — detalhe: estrutograma Nassi colorido -----------------------
async function abrirDetalhe(occId) {
  detailOcc = occId;
  let det;
  try {
    const blob = await getBlob(C.occDetailAddress(secret, occId));
    if (!blob) { log('detalhe ainda não disponível para ' + occId); return; }
    det = JSON.parse(C.fromUtf8(C.openOccDetail(C.occDetailKey(secret), blob)));
  } catch (e) { log('falha ao ler detalhe: ' + e); return; }
  renderDetalhe(det);
  show('modal-detail', true);
}

function renderDetalhe(det) {
  $('det-id').textContent = det.occurrence_id || '?';
  const badge = $('det-status'); badge.textContent = det.status || '?';
  badge.className = 'badge ' + (statusClass(det.status) || '');
  // diagrama
  const dia = $('det-diagram'); dia.innerHTML = '';
  if (det.template) dia.appendChild(nassi(det.template, det.node_status || {}));
  else dia.textContent = '(sem template)';
  // artefatos (PDF inline {"$b64","nome"})
  const arts = $('det-artifacts'); arts.innerHTML = '';
  $('det-pdf').innerHTML = '';
  const found = []; findArtifacts(det.result, found);
  for (const [nome, b64] of found) {
    if (/\.pdf$/i.test(nome)) {
      const bv = el('button', null, 'Visualizar ' + nome);
      bv.addEventListener('click', () => verPdf(b64)); arts.appendChild(bv);
    }
    const bs = el('button', null, 'Salvar ' + nome);
    bs.addEventListener('click', () => salvar(nome, b64)); arts.appendChild(bs);
  }
  // erros
  $('det-errors').textContent = coletarErros(det) || 'Sem erros registrados.';
}

const STATUS_CLASS = { done: 'st-done', running: 'st-running', failed: 'st-failed' };
const STATUS_BG = { done: '#cdebd3', running: '#fde2b3', failed: '#f5c6c6' };
const statusClass = s => STATUS_CLASS[s] || null;

function nassi(node, ns) {
  if (node && node.raiz) return nassi(node.raiz, ns);
  const tipo = node && node.tipo;
  const stBg = node && node.nome ? STATUS_BG[ns[node.nome]] : null;  // inline: vence o tipo
  if (tipo === 'block') {
    const d = el('div', 'nassi-block');
    const filhos = node.filhos || [];
    if (!filhos.length) d.appendChild(el('div', 'nassi-box', '(bloco vazio)'));
    filhos.forEach(ch => d.appendChild(nassi(ch, ns)));
    return d;
  }
  if (tipo === 'action') {
    const b = el('div', 'nassi-box');
    b.appendChild(el('div', null, node.nome || 'ação'));
    if (stBg) b.style.background = stBg;
    return b;
  }
  if (tipo === 'loop') {
    const w = el('div', 'nassi-loop');
    const h = el('div', 'nassi-loop-head', `↻ ${node.nome || 'loop'} — para cada item de ${node.array || '?'}`);
    if (stBg) h.style.background = stBg;
    w.appendChild(h);
    const body = el('div', 'nassi-loop-body');
    if (node.corpo) body.appendChild(nassi(node.corpo, ns));
    w.appendChild(body);
    w.appendChild(el('div', 'nassi-foot', `join → ${node.join || ''}`));
    return w;
  }
  if (tipo === 'decision') {
    const w = el('div', 'nassi-decision');
    const dh = el('div', 'nassi-dec-head', `◇ ${node.nome || 'decisão'}`);
    if (stBg) dh.style.background = stBg;
    w.appendChild(dh);
    const cols = el('div', 'nassi-cols');
    for (const [label, sub] of Object.entries(node.rotas || {})) {
      const col = el('div', 'nassi-col');
      col.appendChild(el('div', 'nassi-col-label', label));
      col.appendChild(nassi(sub, ns));
      cols.appendChild(col);
    }
    w.appendChild(cols);
    return w;
  }
  return el('div', 'nassi-box', `[${tipo}]`);
}

function findArtifacts(v, out) {
  if (v && typeof v === 'object' && !Array.isArray(v)) {
    if (v.$b64) { out.push([v.nome || 'arquivo.bin', v.$b64]); return; }
    for (const k of Object.keys(v)) findArtifacts(v[k], out);
  } else if (Array.isArray(v)) { for (const x of v) findArtifacts(x, out); }
}
function coletarErros(det) {
  const out = [];
  if (det.fail) out.push('[FALHA] ' + (det.fail._node ? 'nó ' + det.fail._node + ': ' : '') + (det.fail.motivo || JSON.stringify(det.fail)));
  const walk = (v, ctx) => {
    if (v && typeof v === 'object' && !Array.isArray(v)) {
      if (v.motivo || v.erro) out.push(`[${v._node || ctx}] ${v.motivo || v.erro}`);
      for (const k of Object.keys(v)) walk(v[k], ctx);
    } else if (Array.isArray(v)) v.forEach(x => walk(x, ctx));
  };
  walk(det.node_outputs, 'nó');
  return out.join('\n');
}
function bytesFromB64(b64) { const bin = atob(b64); const u = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i); return u; }
// Visualizar: embute o PDF INLINE no modal (sem window.open — popups são
// bloqueados e blob: em nova aba não abre de forma confiável).
function verPdf(b64) {
  const url = URL.createObjectURL(new Blob([bytesFromB64(b64)], { type: 'application/pdf' }));
  $('det-pdf').innerHTML = '';
  const emb = el('embed'); emb.type = 'application/pdf'; emb.src = url;
  emb.style.cssText = 'width:100%;height:70vh;border:1px solid #888';
  $('det-pdf').appendChild(emb);
}
// Salvar: o anchor precisa estar NO DOM para o .click() disparar o download em
// vários browsers (Firefox); anexa, clica e remove.
function salvar(nome, b64) {
  const a = el('a'); a.href = URL.createObjectURL(new Blob([bytesFromB64(b64)]));
  a.download = nome; document.body.appendChild(a); a.click(); a.remove();
}

// ---- wiring ----------------------------------------------------------
window.addEventListener('DOMContentLoaded', () => {
  $('btn-iniciar').addEventListener('click', iniciar);
  $('chave').addEventListener('keydown', e => { if (e.key === 'Enter') iniciar(); });
  $('btn-nova').addEventListener('click', abrirNova);
  $('btn-refresh').addEventListener('click', carregarOcorrencias);
  $('btn-salvar-new').addEventListener('click', salvarNova);
  $('btn-cancel-new').addEventListener('click', () => show('modal-new', false));
  $('btn-close-detail').addEventListener('click', () => show('modal-detail', false));
  $('btn-update-detail').addEventListener('click', () => { if (detailOcc) abrirDetalhe(detailOcc); });
});
