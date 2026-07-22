const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

function showToast(message, error = false) {
  const el = $('#appToast');
  if (!el) return;
  el.classList.toggle('text-bg-danger', error);
  el.classList.toggle('text-bg-success', !error);
  $('.toast-body', el).textContent = message;
  bootstrap.Toast.getOrCreateInstance(el, { delay: 4200 }).show();
}

async function api(url, options = {}) {
  const config = { credentials: 'same-origin', ...options };
  if (config.body && !(config.body instanceof FormData)) config.headers = { 'Content-Type': 'application/json', ...(config.headers || {}) };
  const response = await fetch(url, config);
  if (response.status === 401 && !['/login', '/cadastro'].includes(location.pathname)) {
    location.href = '/login';
    throw new Error('Sessão expirada.');
  }
  if (response.status === 204) return null;
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = Array.isArray(data.detail) ? data.detail.map(x => x.msg).join(' ') : data.detail;
    throw new Error(detail || 'Não foi possível concluir a operação.');
  }
  return data;
}

function formObject(form) {
  return Object.fromEntries(new FormData(form).entries());
}

$('#menuToggle')?.addEventListener('click', () => $('#sidebar').classList.toggle('open'));
$('#logout')?.addEventListener('click', async () => { await api('/api/auth/logout', { method: 'POST' }); location.href = '/'; });

$('#loginForm')?.addEventListener('submit', async event => {
  event.preventDefault();
  try { await api('/api/auth/login', { method: 'POST', body: JSON.stringify(formObject(event.target)) }); location.href = '/dashboard'; }
  catch (error) { showToast(error.message, true); }
});

$('#forgotPassword')?.addEventListener('click', async () => {
  const data = await api('/api/auth/forgot-password', { method: 'POST' });
  showToast(data.message);
});

$('#registerForm')?.addEventListener('submit', async event => {
  event.preventDefault();
  const data = formObject(event.target);
  data.accept_terms = data.accept_terms === 'on';
  try { await api('/api/auth/register', { method: 'POST', body: JSON.stringify(data) }); location.href = '/dashboard'; }
  catch (error) { showToast(error.message, true); }
});

const statusLabels = {draft:'Rascunho',review:'Em revisão',scheduled:'Agendada',sending:'Enviando',sent:'Concluída',simulated:'Simulada',cancelled:'Cancelada',failed:'Falhou',pending:'Pendente'};
function badge(value, type='status-badge') {
  const span = document.createElement('span');
  span.className = type + (['sent','delivered','read'].includes(value) ? ' success' : ['failed','cancelled'].includes(value) ? ' danger' : ['scheduled','review','simulated'].includes(value) ? ' warning' : '');
  span.textContent = statusLabels[value] || value;
  return span;
}
function cell(row, value) { const td=document.createElement('td'); if(value instanceof Node) td.append(value); else td.textContent=value ?? '—'; row.append(td); return td; }
function formatDate(value) { return value ? new Intl.DateTimeFormat('pt-BR',{dateStyle:'short',timeStyle:'short'}).format(new Date(value)) : '—'; }

async function loadDashboard() {
  if (!$('body[data-page="dashboard"]')) return;
  try {
    const data = await api('/api/dashboard');
    const labels = {contacts:['bi-people','Contatos'],campaigns:['bi-megaphone','Campanhas'],scheduled:['bi-calendar','Agendadas'],sent_campaigns:['bi-send-check','Enviadas'],delivered:['bi-check2-circle','Entregues'],errors:['bi-exclamation-triangle','Erros'],publications:['bi-share','Publicações'],clicks:['bi-cursor','Cliques']};
    $('#stats').replaceChildren(...Object.entries(data.totals).map(([key,value]) => { const col=document.createElement('div'); col.className='col-6 col-md-4 col-xl-2'; col.innerHTML=`<div class="stat-card"><i class="bi ${labels[key][0]}"></i><strong></strong><span></span></div>`; $('strong',col).textContent=value; $('span',col).textContent=labels[key][1]; return col; }));
    const activities = $('#activities');
    data.activities.forEach(item => { const div=document.createElement('div'); div.className='activity-item'; const title=document.createElement('div'); title.textContent=item.action.replaceAll('.',' · '); const date=document.createElement('small'); date.textContent=formatDate(item.date); div.append(title,date); activities.append(div); });
    if (!data.activities.length) activities.textContent='Nenhuma atividade registrada.';
    new Chart($('#performanceChart'), {type:'bar',data:{labels:data.chart.labels,datasets:[{data:data.chart.values,backgroundColor:['#635bff','#8b63da','#b37bc4','#16a085'],borderRadius:8}]},options:{maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{y:{beginAtZero:true,ticks:{precision:0}},x:{grid:{display:false}}}}});
  } catch(error) { showToast(error.message,true); }
}

async function loadContacts(query='') {
  const table=$('#contactsTable'); if(!table) return;
  try { const contacts=await api('/api/contacts?q='+encodeURIComponent(query)); table.replaceChildren(); contacts.forEach(contact=>{const tr=document.createElement('tr');const check=document.createElement('input');check.type='checkbox';check.className='form-check-input contact-select';check.value=contact.id;cell(tr,check); const identity=document.createElement('div'); const strong=document.createElement('strong'); strong.textContent=contact.name; const small=document.createElement('small'); small.className='d-block text-muted'; small.textContent=contact.email||'Sem e-mail'; identity.append(strong,small); cell(tr,identity);cell(tr,contact.phone);const consent=document.createElement('div');contact.consents.filter(x=>x.is_granted&&!x.revoked_at).forEach(x=>consent.append(badge(x.channel,'channel-badge me-1')));if(!consent.children.length)consent.textContent='Sem consentimento';cell(tr,consent);cell(tr,badge(contact.permanently_blocked?'Bloqueado':contact.is_active?'Ativo':'Inativo'));const actions=document.createElement('div');actions.className='d-flex gap-1';const toggle=document.createElement('button');toggle.className='btn btn-sm btn-light';toggle.textContent=contact.is_active?'Inativar':'Ativar';toggle.onclick=async()=>{await api(`/api/contacts/${contact.id}`,{method:'PATCH',body:JSON.stringify({is_active:!contact.is_active})});loadContacts()};const remove=document.createElement('button');remove.className='btn btn-sm btn-outline-danger';remove.textContent='Excluir';remove.onclick=async()=>{if(confirm('Excluir este contato e seus consentimentos?')){await api(`/api/contacts/${contact.id}`,{method:'DELETE'});showToast('Contato excluído.');loadContacts()}};actions.append(toggle,remove);cell(tr,actions);table.append(tr);}); if(!contacts.length){const tr=document.createElement('tr');const td=document.createElement('td');td.colSpan=6;td.className='text-center text-muted py-5';td.textContent='Nenhum contato encontrado.';tr.append(td);table.append(tr);}} catch(error){showToast(error.message,true)}
}
let searchTimer; $('#contactSearch')?.addEventListener('input',event=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>loadContacts(event.target.value),300)});
$('#contactForm')?.addEventListener('submit',async event=>{event.preventDefault();const d=formObject(event.target);const payload={name:d.name,phone:d.phone,email:d.email||null,source:d.source,consents:d.whatsapp?[{channel:'whatsapp',is_granted:true,source:d.source}]:[]};try{await api('/api/contacts',{method:'POST',body:JSON.stringify(payload)});bootstrap.Modal.getInstance($('#contactModal')).hide();event.target.reset();showToast('Contato salvo.');loadContacts();}catch(error){showToast(error.message,true)}});
$('#csvFile')?.addEventListener('change',async event=>{const form=new FormData();form.append('file',event.target.files[0]);try{const data=await api('/api/contacts/import/csv',{method:'POST',body:form});showToast(`${data.created} contatos importados; ${data.skipped} ignorados.`);loadContacts();}catch(error){showToast(error.message,true)}});
$('#selectAllContacts')?.addEventListener('change',event=>$$('.contact-select').forEach(x=>x.checked=event.target.checked));
$('#createList')?.addEventListener('click',async()=>{const ids=$$('.contact-select:checked').map(x=>Number(x.value));if(!ids.length){showToast('Selecione ao menos um contato.',true);return}const name=prompt('Nome da nova lista:');if(!name)return;try{await api('/api/contacts/lists',{method:'POST',body:JSON.stringify({name,contact_ids:ids})});showToast('Lista criada.');}catch(error){showToast(error.message,true)}});

async function renderListContactOptions(){
  const root=$('#listContactOptions');
  if(!root)return;
  root.replaceChildren();
  try{
    const contacts=await api('/api/contacts?limit=500');
    const preselected=new Set($$('.contact-select:checked').map(x=>Number(x.value)));
    if(!contacts.length){
      const empty=document.createElement('div');
      empty.className='p-3 text-muted';
      empty.textContent='Cadastre ao menos um contato antes de criar uma lista.';
      root.append(empty);
      return;
    }
    contacts.forEach(contact=>{
      const label=document.createElement('label');
      label.className='list-contact-option';
      const input=document.createElement('input');
      input.type='checkbox';
      input.className='form-check-input list-contact-select';
      input.value=contact.id;
      input.checked=preselected.has(contact.id);
      const text=document.createElement('span');
      const name=document.createElement('strong');
      name.textContent=contact.name;
      const phone=document.createElement('small');
      phone.className='d-block text-muted';
      phone.textContent=contact.phone;
      text.append(name,phone);
      label.append(input,text);
      root.append(label);
    });
  }catch(error){
    root.textContent=error.message;
  }
}

$('#openListModal')?.addEventListener('click',async()=>{
  const feedback=$('#listFormFeedback');
  feedback.classList.add('d-none');
  feedback.textContent='';
  bootstrap.Modal.getOrCreateInstance($('#listModal')).show();
  await renderListContactOptions();
});

$('#toggleListContacts')?.addEventListener('click',event=>{
  const checks=$$('.list-contact-select');
  const selectAll=checks.some(x=>!x.checked);
  checks.forEach(x=>x.checked=selectAll);
  event.currentTarget.textContent=selectAll?'Desmarcar todos':'Selecionar todos';
});

$('#listForm')?.addEventListener('submit',async event=>{
  event.preventDefault();
  const feedback=$('#listFormFeedback');
  feedback.classList.add('d-none');
  const data=formObject(event.target);
  const ids=$$('.list-contact-select:checked').map(x=>Number(x.value));
  if(!ids.length){
    feedback.textContent='Selecione ao menos um contato para a lista.';
    feedback.classList.remove('d-none');
    return;
  }
  const button=$('button[type="submit"]',event.target);
  button.disabled=true;
  try{
    await api('/api/contacts/lists',{method:'POST',body:JSON.stringify({name:data.name,description:data.description||null,contact_ids:ids})});
    bootstrap.Modal.getInstance($('#listModal')).hide();
    event.target.reset();
    showToast('Lista criada com sucesso.');
    await loadContactLists();
  }catch(error){
    feedback.textContent=error.message;
    feedback.classList.remove('d-none');
  }finally{
    button.disabled=false;
  }
});

async function loadContactLists(){
  const root=$('#contactLists');
  if(!root)return;
  try{
    const lists=await api('/api/contacts/lists/all');
    root.replaceChildren();
    $('#contactListsCount').textContent=`${lists.length} ${lists.length===1?'lista':'listas'}`;
    lists.forEach(item=>{
      const col=document.createElement('div');
      col.className='col-md-6 col-xl-4';
      const card=document.createElement('div');
      card.className='list-card';
      const name=document.createElement('strong');
      name.textContent=item.name;
      const count=document.createElement('small');
      count.textContent=`${item.contacts} ${item.contacts===1?'contato':'contatos'}`;
      const description=document.createElement('p');
      description.className='small mb-0 mt-2 text-muted';
      description.textContent=item.description||'Sem descrição';
      card.append(name,count,description);
      col.append(card);
      root.append(col);
    });
    if(!lists.length){
      const empty=document.createElement('div');
      empty.className='text-muted';
      empty.textContent='Nenhuma lista criada ainda.';
      root.append(empty);
    }
  }catch(error){
    root.textContent=error.message;
  }
}

async function loadCampaigns(){const table=$('#campaignsTable');if(!table)return;try{const campaigns=await api('/api/campaigns');table.replaceChildren();campaigns.forEach(c=>{const tr=document.createElement('tr');const title=document.createElement('div');title.innerHTML='<strong></strong><small class="d-block text-muted"></small>';$('strong',title).textContent=c.internal_name;$('small',title).textContent=c.title;cell(tr,title);cell(tr,badge(c.channel,'channel-badge'));cell(tr,formatDate(c.scheduled_at));cell(tr,badge(c.status));const actions=document.createElement('div');actions.className='d-flex gap-1';const duplicate=document.createElement('button');duplicate.className='btn btn-sm btn-light';duplicate.textContent='Duplicar';duplicate.onclick=async()=>{await api(`/api/campaigns/${c.id}/duplicate`,{method:'POST'});showToast('Campanha duplicada.');loadCampaigns()};const send=document.createElement('button');send.className='btn btn-sm btn-primary';send.textContent='Enviar';send.disabled=['sent','sending','cancelled'].includes(c.status);send.onclick=async()=>{const warning=c.requires_confirmation?'Esta campanha é grande. Confirme novamente que a base e os consentimentos foram revisados.':'Confirma o envio? Somente destinatários consentidos serão processados.';if(!confirm(warning))return;try{const response=await api(`/api/campaigns/${c.id}/send?confirm=${c.requires_confirmation}`,{method:'POST'});showToast(response.message);loadCampaigns()}catch(error){showToast(error.message,true)}};actions.append(duplicate,send);cell(tr,actions);table.append(tr)});if(!campaigns.length){const tr=document.createElement('tr');const td=document.createElement('td');td.colSpan=5;td.className='text-center text-muted py-5';td.textContent='Crie sua primeira campanha.';tr.append(td);table.append(tr)}}catch(error){showToast(error.message,true)}}
async function loadLists(){const select=$('#campaignList');if(!select)return;try{const lists=await api('/api/contacts/lists/all');lists.forEach(x=>{const o=document.createElement('option');o.value=x.id;o.textContent=`${x.name} (${x.contacts})`;select.append(o)})}catch(error){showToast(error.message,true)}}
$('#campaignForm')?.addEventListener('submit',async event=>{event.preventDefault();const d=formObject(event.target);const media=$('input[name="media"]',event.target).files[0];const payload={internal_name:d.internal_name,title:d.title,body:d.body,channel:d.channel,timezone:'America/Sao_Paulo',contact_list_id:d.contact_list_id?Number(d.contact_list_id):null,scheduled_at:d.scheduled_at?new Date(d.scheduled_at).toISOString():null,call_to_action:d.call_to_action||null,link_url:d.link_url||null};try{const campaign=await api('/api/campaigns',{method:'POST',body:JSON.stringify(payload)});if(media){const upload=new FormData();upload.append('file',media);await api(`/api/campaigns/${campaign.id}/upload`,{method:'POST',body:upload})}bootstrap.Modal.getInstance($('#campaignModal')).hide();event.target.reset();showToast('Campanha salva.');loadCampaigns()}catch(error){showToast(error.message,true)}});

let generatedId=null;$('#contentForm')?.addEventListener('submit',async event=>{event.preventDefault();const button=$('button[type="submit"]',event.target);button.disabled=true;button.textContent='Gerando…';try{const data=await api('/api/content/generate',{method:'POST',body:JSON.stringify(formObject(event.target))});generatedId=data.id;$('#generatedContent').value=data.content;$('#aiProvider').textContent=data.provider==='simulation'?'SIMULAÇÃO':'API oficial';$('#approveContent').disabled=false;showToast('Sugestão criada. Revise antes de aprovar.')}catch(error){showToast(error.message,true)}finally{button.disabled=false;button.innerHTML='<i class="bi bi-stars"></i> Gerar sugestão'}});
$('#copyContent')?.addEventListener('click',async()=>{await navigator.clipboard.writeText($('#generatedContent').value);showToast('Texto copiado.')});
$('#approveContent')?.addEventListener('click',async()=>{if(!generatedId)return;await api(`/api/content/${generatedId}/approve`,{method:'POST'});showToast('Conteúdo aprovado. Copie-o para uma campanha.')});

async function loadIntegrations(){if(!$('#integrationCards'))return;try{const integrations=await api('/api/integrations');integrations.forEach(i=>{const card=$(`.integration-card[data-provider="${i.provider}"]`);if(!card)return;const status=$('.integration-status',card);status.textContent=i.active?'Conectada':i.credential_hints.length?`Salva ${i.credential_hints.join(', ')}`:'Não configurada';status.className=`badge integration-status ${i.active?'text-bg-success':'text-bg-secondary'}`;card.dataset.id=i.id})}catch(error){showToast(error.message,true)}}
$$('.configureIntegration').forEach(button=>button.addEventListener('click',()=>{const card=button.closest('.integration-card');const form=$('#integrationForm');form.reset();form.elements.provider.value=card.dataset.provider;bootstrap.Modal.getOrCreateInstance($('#integrationModal')).show()}));
$('#integrationForm')?.addEventListener('submit',async event=>{event.preventDefault();const d=formObject(event.target);const keyNames={whatsapp:'access_token',facebook:'page_access_token',instagram:'page_access_token',ai:'api_key'};const credentials={};if(d.token)credentials[keyNames[d.provider]]=d.token;try{const result=await api('/api/integrations',{method:'POST',body:JSON.stringify({provider:d.provider,external_account_id:d.external_account_id||null,credentials})});bootstrap.Modal.getInstance($('#integrationModal')).hide();event.target.reset();showToast(result.message);loadIntegrations()}catch(error){showToast(error.message,true)}});

function campaignDateTimeLocal(value){
  if(!value)return '';
  const date=new Date(value);
  const local=new Date(date.getTime()-date.getTimezoneOffset()*60000);
  return local.toISOString().slice(0,16);
}

function openCampaignEditor(campaign=null){
  const form=$('#campaignEditorForm');
  if(!form)return;
  form.reset();
  form.elements.campaign_id.value=campaign?.id||'';
  $('#campaignModalTitle').textContent=campaign?'Editar campanha':'Nova campanha';
  $('#campaignSubmitButton').textContent=campaign?'Salvar alterações':'Salvar campanha';
  if(campaign){
    form.elements.internal_name.value=campaign.internal_name||'';
    form.elements.title.value=campaign.title||'';
    form.elements.body.value=campaign.body||'';
    form.elements.channel.value=campaign.channel;
    form.elements.contact_list_id.value=campaign.contact_list_id||'';
    form.elements.scheduled_at.value=campaignDateTimeLocal(campaign.scheduled_at);
    form.elements.call_to_action.value=campaign.call_to_action||'';
    form.elements.link_url.value=campaign.link_url||'';
  }
  bootstrap.Modal.getOrCreateInstance($('#campaignModal')).show();
}

$('#newCampaignButton')?.addEventListener('click',()=>openCampaignEditor());

$('#campaignEditorForm')?.addEventListener('submit',async event=>{
  event.preventDefault();
  const form=event.target;
  const data=formObject(form);
  const campaignId=data.campaign_id;
  const media=form.elements.media.files[0];
  const payload={
    internal_name:data.internal_name,
    title:data.title,
    body:data.body,
    channel:data.channel,
    timezone:'America/Sao_Paulo',
    contact_list_id:data.contact_list_id?Number(data.contact_list_id):null,
    scheduled_at:data.scheduled_at?new Date(data.scheduled_at).toISOString():null,
    call_to_action:data.call_to_action||null,
    link_url:data.link_url||null
  };
  const button=$('#campaignSubmitButton');
  button.disabled=true;
  try{
    const campaign=await api(campaignId?`/api/campaigns/${campaignId}`:'/api/campaigns',{method:campaignId?'PATCH':'POST',body:JSON.stringify(payload)});
    if(media){
      const upload=new FormData();
      upload.append('file',media);
      await api(`/api/campaigns/${campaign.id}/upload`,{method:'POST',body:upload});
    }
    bootstrap.Modal.getInstance($('#campaignModal')).hide();
    form.reset();
    showToast(campaignId?'Campanha atualizada com sucesso.':'Campanha criada com sucesso.');
    await loadCampaigns();
  }catch(error){
    showToast(error.message,true);
  }finally{
    button.disabled=false;
  }
});

async function loadCampaigns(){
  const table=$('#campaignsTable');
  if(!table)return;
  try{
    const campaigns=await api('/api/campaigns');
    table.replaceChildren();
    campaigns.forEach(c=>{
      const tr=document.createElement('tr');
      const title=document.createElement('div');
      const strong=document.createElement('strong');
      strong.textContent=c.internal_name;
      const small=document.createElement('small');
      small.className='d-block text-muted';
      small.textContent=c.title;
      title.append(strong,small);
      cell(tr,title);
      cell(tr,badge(c.channel,'channel-badge'));
      cell(tr,formatDate(c.scheduled_at));
      cell(tr,badge(c.status));
      const actions=document.createElement('div');
      actions.className='d-flex gap-1 flex-wrap justify-content-end';
      const edit=document.createElement('button');
      edit.className='btn btn-sm btn-outline-primary';
      edit.innerHTML='<i class="bi bi-pencil"></i> Editar';
      edit.disabled=['sending','sent'].includes(c.status);
      edit.title=c.status==='sent'?'Duplique uma campanha enviada para criar uma nova versão.':'';
      edit.onclick=()=>openCampaignEditor(c);
      const duplicate=document.createElement('button');
      duplicate.className='btn btn-sm btn-light';
      duplicate.textContent='Duplicar';
      duplicate.onclick=async()=>{try{await api(`/api/campaigns/${c.id}/duplicate`,{method:'POST'});showToast('Campanha duplicada.');await loadCampaigns()}catch(error){showToast(error.message,true)}};
      const remove=document.createElement('button');
      remove.className='btn btn-sm btn-outline-danger';
      remove.innerHTML='<i class="bi bi-trash"></i> Apagar';
      remove.disabled=c.status==='sending';
      remove.onclick=async()=>{if(!confirm(`Apagar definitivamente a campanha "${c.internal_name}"?`))return;try{await api(`/api/campaigns/${c.id}`,{method:'DELETE'});showToast('Campanha apagada.');await loadCampaigns()}catch(error){showToast(error.message,true)}};
      const send=document.createElement('button');
      send.className='btn btn-sm btn-primary';
      send.textContent='Enviar';
      send.disabled=['sent','simulated','sending','cancelled'].includes(c.status);
      send.onclick=async()=>{const warning=c.requires_confirmation?'Esta campanha é grande. Confirme novamente que a base e os consentimentos foram revisados.':'Confirma o envio? Somente destinatários consentidos serão processados.';if(!confirm(warning))return;try{const response=await api(`/api/campaigns/${c.id}/send?confirm=${c.requires_confirmation}`,{method:'POST'});showToast(response.message);await loadCampaigns()}catch(error){showToast(error.message,true)}};
      actions.append(edit,duplicate,remove,send);
      cell(tr,actions);
      table.append(tr);
    });
    if(!campaigns.length){
      const tr=document.createElement('tr');
      const td=document.createElement('td');
      td.colSpan=5;
      td.className='text-center text-muted py-5';
      td.textContent='Crie sua primeira campanha.';
      tr.append(td);
      table.append(tr);
    }
  }catch(error){
    showToast(error.message,true);
  }
}

async function loadHistory(){const table=$('#historyTable');if(!table)return;try{const items=await api('/api/campaigns/history/all');items.forEach(i=>{const tr=document.createElement('tr');[i.campaign,badge(i.channel,'channel-badge'),formatDate(i.date),i.recipients,i.sent,i.failures,badge(i.status)].forEach(v=>cell(tr,v));table.append(tr)});if(!items.length)table.innerHTML='<tr><td colspan="7" class="text-center text-muted py-5">Nenhum histórico disponível.</td></tr>'}catch(error){showToast(error.message,true)}}
$('#settingsForm')?.addEventListener('submit',async event=>{event.preventDefault();const raw=formObject(event.target);const data=Object.fromEntries(Object.entries(raw).filter(([,v])=>v!==''));if(data.daily_limit)data.daily_limit=Number(data.daily_limit);try{const result=await api('/api/settings/profile',{method:'PATCH',body:JSON.stringify(data)});showToast(result.message)}catch(error){showToast(error.message,true)}});
$('#passwordForm')?.addEventListener('submit',async event=>{event.preventDefault();try{const result=await api('/api/settings/password',{method:'POST',body:JSON.stringify(formObject(event.target))});showToast(result.message);event.target.reset()}catch(error){showToast(error.message,true)}});

async function loadAdmin(){const root=$('#adminOverview');if(!root)return;try{const data=await api('/api/admin/overview');const totals={users:'Usuários',companies:'Empresas',campaigns:'Campanhas',blocked_contacts:'Contatos bloqueados',integrations:'Integrações'};root.replaceChildren(...Object.entries(totals).map(([key,label])=>{const col=document.createElement('div');col.className='col-6 col-lg';col.innerHTML='<div class="stat-card"><strong></strong><span></span></div>';$('strong',col).textContent=data[key];$('span',col).textContent=label;return col}));const table=document.createElement('table');table.className='table';const body=document.createElement('tbody');data.recent_logs.forEach(log=>{const tr=document.createElement('tr');cell(tr,log.action);cell(tr,log.company_id);cell(tr,formatDate(log.date));body.append(tr)});table.append(body);$('#adminLogs').replaceChildren(table)}catch(error){root.textContent=error.message;showToast(error.message,true)}}

loadDashboard();loadContacts();loadContactLists();loadCampaigns();loadLists();loadIntegrations();loadHistory();loadAdmin();
