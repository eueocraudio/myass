// app.js — fluxo do usuário final na web pública.
//
// 1) informa a chave criptográfica -> 2) busca o catálogo (blob E2E) e lista os
// workflows -> 3) escolhe um e cria uma ocorrência (deposita o pedido cifrado) ->
// 4) faz polling da resposta. O servidor PHP só vê blobs opacos.

import * as C from './myass-crypto.js';

let secret = null;

const $ = id => document.getElementById(id);
const log = msg => { $('status').textContent = msg; };

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

async function carregarCatalogo() {
  try {
    secret = C.hexToBytes($('chave').value.trim());
  } catch {
    log('chave inválida (esperado hex de 32 bytes)');
    return;
  }
  const blob = await getBlob(C.catalogAddress(secret));
  const lista = $('workflows');
  lista.innerHTML = '';
  if (!blob) { log('nenhum catálogo para esta chave (ainda).'); return; }
  const catalogo = JSON.parse(C.fromUtf8(C.openCatalog(C.catalogKey(secret), blob)));
  for (const wf of catalogo) {
    const opt = document.createElement('option');
    opt.value = wf.hash;
    opt.textContent = `${wf.label} (${wf.versao || ''})`;
    lista.appendChild(opt);
  }
  log(`${catalogo.length} workflow(s) disponível(is).`);
}

async function criarOcorrencia() {
  if (!secret) { log('carregue o catálogo primeiro.'); return; }
  const workflow_hash = $('workflows').value;
  let inputs = {};
  try { inputs = JSON.parse($('inputs').value || '{}'); }
  catch { log('inputs JSON inválido'); return; }

  const request_id = crypto.randomUUID();
  const pedido = C.utf8(JSON.stringify({
    request_id, action: 'start_occurrence', workflow_hash, inputs,
  }));
  await putBlob(C.requestAddress(secret), C.sealRequest(C.requestKey(secret), pedido));
  log('pedido enviado; aguardando resposta…');
  pollResposta();
}

async function pollResposta(tentativas = 60) {
  const addr = C.responseAddress(secret), key = C.responseKey(secret);
  for (let i = 0; i < tentativas; i++) {
    const blob = await getBlob(addr);
    if (blob) {
      const resp = JSON.parse(C.fromUtf8(C.openResponse(key, blob)));
      $('resposta').textContent = JSON.stringify(resp, null, 2);
      log('resposta recebida.');
      return;
    }
    await new Promise(r => setTimeout(r, 2000));
  }
  log('sem resposta no tempo esperado.');
}

window.addEventListener('DOMContentLoaded', () => {
  $('btn-catalogo').addEventListener('click', carregarCatalogo);
  $('btn-criar').addEventListener('click', criarOcorrencia);
});
