const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
let state={}, kind='expense', loadVersion=0;

function digitsOnly(value){
  return String(value??'').replace(/\D/g,'');
}

function formatMoneyInput(input){
  const original=String(input.value||''),
        caret=input.selectionStart??original.length,
        digitsBefore=original.slice(0,caret).replace(/\D/g,'').length,
        raw=digitsOnly(original),
        formatted=raw.replace(/\B(?=(\d{3})+(?!\d))/g,'.');
  input.value=formatted;
  let pos=0, seen=0;
  while(pos<formatted.length && seen<digitsBefore){
    if(/\d/.test(formatted[pos])) seen++;
    pos++;
  }
  if(document.activeElement===input) input.setSelectionRange(pos,pos);
  return raw;
}

document.addEventListener('input', e=>{
  if(e.target.matches('[data-money]')) formatMoneyInput(e.target);
});
document.querySelectorAll('[data-money]').forEach(formatMoneyInput);

const rupiah=n=>new Intl.NumberFormat('id-ID',{style:'currency',currency:'IDR',maximumFractionDigits:0}).format((n||0)/100);
const csrf=()=>sessionStorage.csrf;

async function api(url,opt={}){
  opt.cache=opt.cache||'no-store';
  const isForm=opt.body instanceof FormData;
  opt.headers={...(opt.headers||{}),...(isForm?{}:{'Content-Type':'application/json'}),'X-CSRF-Token':csrf()};
  let r=await fetch(url,opt), d=await r.json();
  if(r.status===403 && d.csrf){
    sessionStorage.csrf=d.csrf;
    opt.headers['X-CSRF-Token']=d.csrf;
    r=await fetch(url,opt);
    d=await r.json();
  }
  if(r.status===401){
    location.href='/login';
    throw Error(d.error);
  }
  if(!r.ok){
    const err=Error(d.error||'Terjadi kesalahan');
    err.status=r.status;
    err.data=d;
    throw err;
  }
  return d;
}

/* ---------- Shared UI helpers (used by budgets.js, wishes.js, behaviour.js) ---------- */

// Styled replacement for window.confirm(). Resolves true only when the user picks the confirm button.
function askConfirm({title='Lanjutkan?', message='', confirmLabel='Ya, lanjutkan', eyebrow='KONFIRMASI', danger=false}={}){
  const dlg=$('#confirm-dialog');
  if(!dlg) return Promise.resolve(window.confirm(message||title));
  // A second request while one is open would reset returnValue and cancel the first; refuse it.
  if(dlg.open) return Promise.resolve(false);
  $('#confirm-eyebrow').textContent=eyebrow;
  $('#confirm-title').textContent=title;
  $('#confirm-message').textContent=message;
  const ok=$('#confirm-ok');
  ok.textContent=confirmLabel;
  ok.classList.toggle('danger',danger);
  dlg.returnValue='';
  return new Promise(resolve=>{
    dlg.addEventListener('close',()=>resolve(dlg.returnValue==='ok'),{once:true});
    dlg.showModal();
    $('#confirm-cancel').focus();
  });
}

// Overflow (⋮) menu markup. items: [{label, icon, attrs, danger}]
function actionMenu(items,label='Opsi'){
  return `
    <div class="action-menu" data-action-menu>
      <button type="button" class="action-menu-trigger" aria-haspopup="menu" aria-expanded="false" aria-label="${h(label)}" title="${h(label)}">
        <span class="material-symbols-outlined text-[20px]" aria-hidden="true">more_vert</span>
      </button>
      <div class="action-menu-list" role="menu" hidden>
        ${items.map(item=>`<button type="button" role="menuitem" class="${item.danger?'danger':''}" ${item.attrs||''}><span class="material-symbols-outlined text-[18px]" aria-hidden="true">${item.icon}</span><span>${h(item.label)}</span></button>`).join('')}
      </div>
    </div>`;
}

function closeActionMenus(except){
  $$('[data-action-menu]').forEach(menu=>{
    if(menu===except)return;
    menu.querySelector('.action-menu-list').hidden=true;
    menu.querySelector('.action-menu-trigger').setAttribute('aria-expanded','false');
  });
}

document.addEventListener('click',e=>{
  const trigger=e.target.closest('.action-menu-trigger');
  if(trigger){
    const menu=trigger.closest('[data-action-menu]'), list=menu.querySelector('.action-menu-list'), open=list.hidden;
    closeActionMenus(menu);
    list.hidden=!open;
    trigger.setAttribute('aria-expanded',String(open));
    if(open) list.querySelector('[role=menuitem]')?.focus();
    return;
  }
  // Picking an item or clicking anywhere else closes open menus.
  closeActionMenus(e.target.closest('[role=menuitem]')?null:e.target.closest('[data-action-menu]'));
});

document.addEventListener('keydown',e=>{
  if(e.key!=='Escape')return;
  const open=$$('[data-action-menu]').find(menu=>!menu.querySelector('.action-menu-list').hidden);
  if(open){
    closeActionMenus();
    open.querySelector('.action-menu-trigger').focus();
  }
});

// Disable a submit button and show its busy label while an async save runs.
function setBusy(button,busy){
  if(!button)return;
  button.disabled=busy;
  button.setAttribute('aria-busy',String(busy));
  const label=button.querySelector('[data-busy-label]');
  if(label){
    if(busy){
      label.dataset.idleLabel=label.dataset.idleLabel||label.textContent;
      label.textContent=label.dataset.busyLabel;
    }else if(label.dataset.idleLabel){
      label.textContent=label.dataset.idleLabel;
    }
  }
}

// Random ID for idempotent saves. crypto.getRandomValues also works on plain-HTTP LAN access.
function newRequestId(){
  const bytes=new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return [...bytes].map(b=>b.toString(16).padStart(2,'0')).join('');
}

// Emoji icon chosen by the user for a category, on its chosen background. '' when none is set.
function categoryEmojiIcon(cat,size='md'){
  if(!cat?.icon) return '';
  const bg=/^#[0-9a-f]{6}$/i.test(cat.icon_bg||'')?cat.icon_bg:'#f1f5f9';
  return `<span class="category-icon category-icon-${size}" style="background:${bg}" aria-hidden="true">${h(cat.icon)}</span>`;
}

/* ---------- Komposisi aset (Akun & Dompet): one segmented bar ----------
   Categorical palette validated with the dataviz validator on the white card surface
   (all hard checks pass; the contrast WARN for aqua/yellow/magenta is relieved by the
   legend + the account cards below, which act as the table view). */
const ASSET_SLOTS=['#2a78d6','#eb6834','#1baf7a','#eda100','#e87ba4','#008300','#6250d6','#e34948'];
const ASSET_OTHER='#94a3b8';
// Label inside a fill: white, except near-black on yellow (palette rule).
const assetInk=color=>color==='#eda100'?'#0b0b0b':'#ffffff';

function renderAssetComposition(accounts,netAssets){
  const box=$('#asset-composition');
  if(!box)return;
  // Blocks follow the account list order (never the size rank), and colours are given in palette
  // order along the bar, so every pair of touching blocks is a pair the validator checked.
  const positive=accounts.filter(a=>Number(a.balance_cents)>0), negative=accounts.filter(a=>Number(a.balance_cents)<0);
  const total=positive.reduce((s,a)=>s+Number(a.balance_cents),0);
  const fold=positive.length>ASSET_SLOTS.length;

  // Past seven accounts, the rest share one grey "Lainnya" block at the end.
  const parts=[], other={name:'Lainnya',balance_cents:0,color:ASSET_OTHER,members:[]};
  positive.forEach((a,i)=>{
    if(fold&&i>=ASSET_SLOTS.length-1){ other.balance_cents+=Number(a.balance_cents); other.members.push(a.name); }
    else parts.push({...a,color:ASSET_SLOTS[i]});
  });
  if(other.members.length) parts.push(other);
  const pct=v=>total?v/total*100:0, fmtPct=v=>new Intl.NumberFormat('id-ID',{maximumFractionDigits:v<10?1:0}).format(v)+'%';

  const head=`
    <div class="asset-comp-head">
      <div>
        <h2>Komposisi Aset</h2>
        <p>Persentase saldo tiap akun dari total saldo positif ${rupiah(total)}</p>
      </div>
      <div class="asset-comp-total"><small>Total aset bersih</small><b>${rupiah(netAssets)}</b></div>
    </div>`;
  if(!parts.length){
    box.innerHTML=head+'<p class="asset-comp-empty">Belum ada akun bersaldo positif untuk ditampilkan.</p>';
    return;
  }
  const label=p=>`${p.name}${p.members?` (${p.members.join(', ')})`:''}: ${rupiah(p.balance_cents)}, ${fmtPct(pct(p.balance_cents))} dari saldo positif`;
  box.innerHTML=head+`
    <div class="asset-bar" role="group" aria-label="Komposisi aset per akun">
      ${parts.map((p,i)=>`<div class="asset-seg" tabindex="0" role="img" data-asset-index="${i}" aria-label="${h(label(p))}" style="flex-grow:${p.balance_cents};background:${p.color};color:${assetInk(p.color)}"><span class="asset-seg-pct">${fmtPct(pct(p.balance_cents))}</span></div>`).join('')}
    </div>
    <ul class="asset-legend">
      ${parts.map((p,i)=>`<li data-asset-index="${i}"><i style="background:${p.color}"></i><b>${h(p.name)}</b><span class="asset-legend-pct">${fmtPct(pct(p.balance_cents))}</span></li>`).join('')}
    </ul>
    ${negative.length?`<p class="asset-comp-note">Tidak termasuk akun bersaldo minus: ${negative.map(a=>`${h(a.name)} (${rupiah(a.balance_cents)})`).join(', ')}.</p>`:''}`;

  // A block too narrow for its % prints none (the legend always lists every %; amounts are in the tooltip).
  box.querySelectorAll('.asset-seg').forEach(seg=>{
    const text=seg.querySelector('.asset-seg-pct');
    text.hidden=text.offsetWidth+16>seg.clientWidth;
  });

  // Hover / keyboard-focus tooltip with name, amount and share.
  const tip=$('#asset-tooltip');
  const showTip=seg=>{
    const p=parts[Number(seg.dataset.assetIndex)];
    tip.innerHTML=`<strong>${h(p.name)}</strong>${p.members?`<span class="muted">${h(p.members.join(', '))}</span>`:''}<span><b>${rupiah(p.balance_cents)}</b> · ${fmtPct(pct(p.balance_cents))}</span>`;
    tip.hidden=false;
    const r=seg.getBoundingClientRect(), t=tip.getBoundingClientRect();
    tip.style.left=`${Math.max(8,Math.min(r.left+r.width/2-t.width/2,window.innerWidth-t.width-8))}px`;
    tip.style.top=`${r.top-t.height-8<8?r.bottom+8:r.top-t.height-8}px`;
  };
  const hideTip=()=>{ tip.hidden=true; };
  box.querySelectorAll('.asset-seg').forEach(seg=>{
    seg.addEventListener('pointerenter',()=>showTip(seg));
    seg.addEventListener('focus',()=>showTip(seg));
    seg.addEventListener('pointerleave',hideTip);
    seg.addEventListener('blur',hideTip);
  });
}
window.addEventListener('scroll',()=>{ const tip=$('#asset-tooltip'); if(tip) tip.hidden=true; },{passive:true});
// Re-measure which blocks can print their % when the layout width changes.
window.addEventListener('resize',()=>{ if(state.accounts&&!$('#accounts')?.classList.contains('hidden')) renderAssetComposition(state.accounts,state.summary?.assets_cents); });

// Dashed placeholder card that opens a "create" form; used by Akun, Budget and Wish grids.
function addCard(label,attrs){
  return `<button type="button" class="add-card" ${attrs}>
    <span class="add-card-plus" aria-hidden="true"><span class="material-symbols-outlined">add</span></span>
    <span class="add-card-label">${h(label)}</span>
  </button>`;
}

/* ---------- "+N" badge on the Transaksi menu ---------- */
let markingSeen=false;

function renderNewTransactionsBadge(){
  const badge=$('#sidebar-tx-badge'), count=Number(state.new_transactions_count)||0;
  if(!badge)return;
  badge.hidden=!count;
  badge.textContent=count>99?'+99':`+${count}`;
  badge.setAttribute('aria-label',`${count} transaksi baru belum dilihat`);
}

// Called when the transaction list is on screen: everything loaded so far counts as seen.
async function markTransactionsSeen(){
  if(markingSeen || !Number(state.new_transactions_count) || !state.latest_created_at)return;
  markingSeen=true;
  try{
    await api('/api/transactions/seen',{method:'POST',body:JSON.stringify({seen_at:state.latest_created_at})});
    state.new_transactions_count=0;
    renderNewTransactionsBadge();
  }catch(err){
    console.warn('Gagal menandai transaksi sebagai sudah dilihat',err);
  }finally{markingSeen=false}
}

function transactionListVisible(){
  return !$('#transactions')?.classList.contains('hidden') && !$('#transaction-list-view')?.classList.contains('hidden');
}

const ID_MONTHS=['Januari','Februari','Maret','April','Mei','Juni','Juli','Agustus','September','Oktober','November','Desember'];

// Client-side copy of the server rule: a different year or a future time needs confirmation.
function unusualDateReason(value){
  const d=new Date(value), now=new Date();
  if(Number.isNaN(d.getTime()))return null;
  const label=`${d.getDate()} ${ID_MONTHS[d.getMonth()]} ${d.getFullYear()}`;
  if(d.getTime()>now.getTime()+10*60000) return `Tanggal transaksi (${label}) berada di masa depan.`;
  if(d.getFullYear()!==now.getFullYear()) return `Tahun transaksi (${d.getFullYear()}) berbeda dari tahun berjalan (${now.getFullYear()}); tanggal terbaca ${label}.`;
  return null;
}

function toast(s){
  const t=$('#toast');
  if(!t)return;
  t.textContent=s;
  t.classList.add('show');
  setTimeout(()=>t.classList.remove('show'),2800);
}

function h(s=''){
  return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

window.addAmount = function(delta){
  const input = document.querySelector('input[name="amount"]');
  if(!input) return;
  const curr = parseInt(digitsOnly(input.value) || '0', 10);
  const next = curr + delta;
  input.value = new Intl.NumberFormat('id-ID').format(next);
  input.dispatchEvent(new Event('input', { bubbles: true }));
};

function getTxIcon(t){
  if(t.kind === 'transfer') return { icon: 'swap_horiz', bg: 'bg-blue-50', text: 'text-blue-600', border: 'border-blue-100' };
  if(t.kind === 'income') return { icon: 'payments', bg: 'bg-emerald-50', text: 'text-emerald-700', border: 'border-emerald-100' };
  const text = ((t.category||'') + ' ' + (t.description||'')).toLowerCase();
  if(/makan|minum|food|beverage|resto|kopi|coffee|cafe|snack|bakso|mie|nasi/.test(text)) {
    return { icon: 'restaurant', bg: 'bg-orange-50', text: 'text-orange-600', border: 'border-orange-100' };
  }
  if(/game|steam|playstation|xbox|hiburan|movie|film|cinema|bioskop|netflix|spotify/.test(text)) {
    return { icon: 'sports_esports', bg: 'bg-purple-50', text: 'text-purple-600', border: 'border-purple-100' };
  }
  if(/bensin|bbm|pertamina|shell|transport|tol|ojek|grab|gojek|parkir/.test(text)) {
    return { icon: 'local_gas_station', bg: 'bg-sky-50', text: 'text-sky-600', border: 'border-sky-100' };
  }
  if(/pulsa|kuota|internet|wifi|indihome|telkomsel|xl|tri/.test(text)) {
    return { icon: 'wifi', bg: 'bg-cyan-50', text: 'text-cyan-600', border: 'border-cyan-100' };
  }
  if(/belanja|tokopedia|shopee|lazada|mall|supermarket|minimarket|indomaret|alfamart/.test(text)) {
    return { icon: 'shopping_bag', bg: 'bg-amber-50', text: 'text-amber-600', border: 'border-amber-100' };
  }
  return { icon: 'receipt_long', bg: 'bg-rose-50', text: 'text-rose-600', border: 'border-rose-100' };
}

function getCatIcon(name=''){
  const text = name.toLowerCase();
  if(/makan|minum|food|beverage|resto|kopi/.test(text)) {
    return { icon: 'restaurant', bg: 'bg-amber-50', text: 'text-amber-700', border: 'border-amber-100', barColor: 'bg-amber-500', sub: 'Makan luar & kopi' };
  }
  if(/hiburan|game|movie|rekreasi/.test(text)) {
    return { icon: 'sports_esports', bg: 'bg-purple-50', text: 'text-purple-700', border: 'border-purple-100', barColor: 'bg-purple-500', sub: 'Gaming & streaming' };
  }
  if(/bensin|transport|bbm|tol/.test(text)) {
    return { icon: 'local_gas_station', bg: 'bg-blue-50', text: 'text-blue-700', border: 'border-blue-100', barColor: 'bg-blue-500', sub: 'BBM & transportasi' };
  }
  if(/internet|pulsa|wifi|data/.test(text)) {
    return { icon: 'wifi', bg: 'bg-cyan-50', text: 'text-cyan-700', border: 'border-cyan-100', barColor: 'bg-cyan-500', sub: 'Paket data & wifi' };
  }
  return { icon: 'category', bg: 'bg-slate-100', text: 'text-slate-600', border: 'border-slate-200', barColor: 'bg-slate-400', sub: 'Pos belanja aktif' };
}

function getAccountBadge(a){
  const name = a.name.toLowerCase();
  if(a.kind === 'cash' || /tunai|cash|dompet/.test(name)) {
    return { bg: 'bg-emerald-600', content: '<span class="material-symbols-outlined text-[16px]">payments</span>', kindLabel: 'Dompet Fisik' };
  }
  if(/mandiri/.test(name)) {
    return { bg: 'bg-blue-700', content: 'M', kindLabel: 'Rekening Utama' };
  }
  if(/jago/.test(name)) {
    return { bg: 'bg-amber-500', content: 'J', kindLabel: 'Kantong Belanja' };
  }
  if(/bca/.test(name)) {
    return { bg: 'bg-blue-600', content: 'B', kindLabel: 'Rekening Operasional' };
  }
  if(/bni/.test(name)) {
    return { bg: 'bg-teal-600', content: 'B', kindLabel: 'Rekening Bank' };
  }
  if(/bri/.test(name)) {
    return { bg: 'bg-blue-800', content: 'B', kindLabel: 'Rekening Bank' };
  }
  if(/gopay/.test(name)) {
    return { bg: 'bg-sky-500', content: 'G', kindLabel: 'E-Wallet' };
  }
  if(/ovo/.test(name)) {
    return { bg: 'bg-purple-600', content: 'O', kindLabel: 'E-Wallet' };
  }
  if(/dana/.test(name)) {
    return { bg: 'bg-blue-500', content: 'D', kindLabel: 'E-Wallet' };
  }
  if(a.kind === 'ewallet') {
    return { bg: 'bg-sky-600', content: a.name.charAt(0).toUpperCase() || 'E', kindLabel: 'E-Wallet' };
  }
  return { bg: 'bg-slate-700', content: a.name.charAt(0).toUpperCase() || 'A', kindLabel: 'Rekening Bank' };
}

function row(t){
  let sign = t.kind==='income'?'+':t.kind==='expense'?'−':'';
  let amountCls = t.kind==='income'?'text-emerald-700':t.kind==='expense'?'text-[#E05638]':'text-blue-600';
  let kindBadge = t.kind==='income'?'Kredit':t.kind==='expense'?'Debit':'Transfer';
  let conf = getTxIcon(t);
  let title = t.kind==='transfer' ? `${t.account||'Akun'} → ${t.destination||'Akun'}` : (t.description || t.category || 'Transaksi');
  // Transfers show their note (e.g. "Penggantian talangan") so the reason for the move stays visible.
  let categoryLabel = t.kind==='transfer' ? (t.description ? 'Transfer · '+t.description : 'Transfer Antar Akun') : (t.category || 'Tanpa Kategori');
  let dateStr = new Date(t.occurred_at).toLocaleDateString('id-ID', {day:'numeric', month:'short', year:'numeric', hour:'2-digit', minute:'2-digit'});
  let accountLabel = t.account || 'Akun';
  let txnId = t.seq ? 'No. ' + t.seq : '';
  const category = t.kind==='transfer' ? null : (state.categories||[]).find(c => String(c.id)===String(t.category_id));

  return `
    <div class="py-3.5 flex items-center justify-between hover:bg-slate-50/70 -mx-3 px-3 rounded-xl transition-colors border-b border-slate-100 last:border-b-0">
      <div class="flex items-center space-x-3.5 min-w-0">
        ${categoryEmojiIcon(category,'lg') || `<div class="w-10 h-10 rounded-xl ${conf.bg} ${conf.text} flex items-center justify-center shrink-0 border ${conf.border}">
          <span class="material-symbols-outlined text-[18px]">${conf.icon}</span>
        </div>`}
        <div class="min-w-0">
          <h4 class="text-sm font-bold text-slate-900 truncate">${h(title)}</h4>
          <p class="text-xs text-slate-400 flex items-center flex-wrap gap-1.5 mt-0.5">
            <span class="font-medium text-slate-600">${h(categoryLabel)}</span>
            <span>•</span>
            <span>${dateStr}</span>
            <span class="bg-slate-100 px-1.5 py-0.5 rounded text-[10px] text-slate-600 font-medium">${h(accountLabel)}</span>
            <span class="text-[10px] text-slate-400 font-mono">${txnId}</span>
          </p>
        </div>
      </div>
      <div class="text-right shrink-0 ml-3">
        <div class="text-sm font-extrabold ${amountCls}">${sign}${rupiah(t.amount_cents)}</div>
        <span class="text-[10px] text-slate-400 font-medium">${kindBadge}</span>
      </div>
    </div>
  `;
}

let dailyChartArgs=null, dailyChartWidth=0, dailyChartObserver=null;

function attachChartCrosshair(box,c){
  const svg=box.querySelector('.chart-plot'),
        axis=box.querySelector('.chart-yaxis'),
        scroller=box.querySelector('.chart-scroll'),
        g=svg&&svg.querySelector('.chart-crosshair'),
        ag=axis&&axis.querySelector('.chart-crosshair-y');
  if(!g||!ag||!scroller)return;

  const pick=(root,k)=>root.querySelector('[data-cx="'+k+'"]'),
        vLine=pick(g,'v'),
        hLine=pick(g,'h'),
        xBox=pick(g,'xbox'),
        yBox=pick(ag,'ybox'),
        xRect=xBox.querySelector('rect'),
        xText=xBox.querySelector('text'),
        yRect=yBox.querySelector('rect'),
        yText=yBox.querySelector('text'),
        boxH=20,
        padX=8,
        plotRight=c.W-c.right,
        plotBottom=c.top+c.plotH,
        fullDate=d=>new Date(d+'T00:00:00').toLocaleDateString('id-ID',{day:'numeric',month:'short',year:'numeric'}),
        hide=()=>{g.style.display='none';ag.style.display='none'};

  svg.addEventListener('pointermove',e=>{
    const m=svg.getScreenCTM();
    if(!m)return;
    const pt=svg.createSVGPoint();
    pt.x=e.clientX; pt.y=e.clientY;
    const p=pt.matrixTransform(m.inverse());
    if(p.x<c.left||p.x>plotRight||p.y<c.top||p.y>plotBottom){hide();return}
    g.style.display=''; ag.style.display='';

    const n=c.points.length,
          idx=n===1?0:Math.min(n-1,Math.max(0,Math.round((p.x-c.left)/c.plotW*(n-1)))),
          yValue=c.axisMax-((p.y-c.top)/c.plotH)*c.axisSpan;

    vLine.setAttribute('x1',p.x); vLine.setAttribute('x2',p.x);
    vLine.setAttribute('y1',c.top); vLine.setAttribute('y2',plotBottom);

    hLine.setAttribute('x1',0); hLine.setAttribute('x2',c.W);
    hLine.setAttribute('y1',p.y); hLine.setAttribute('y2',p.y);

    yText.textContent=c.fmt(yValue);
    const yw=Math.min(c.axisW-4,yText.getComputedTextLength()+14);
    yRect.setAttribute('x',2); yRect.setAttribute('y',p.y-boxH/2);
    yRect.setAttribute('width',yw); yRect.setAttribute('height',boxH);
    yText.setAttribute('x',2+yw/2); yText.setAttribute('y',p.y);

    xText.textContent=fullDate(c.points[idx].date);
    const xw=xText.getComputedTextLength()+padX*2,
          cx=Math.min(Math.max(p.x,xw/2),c.W-xw/2);
    xRect.setAttribute('x',cx-xw/2); xRect.setAttribute('y',plotBottom+2);
    xRect.setAttribute('width',xw); xRect.setAttribute('height',boxH);
    xText.setAttribute('x',cx); xText.setAttribute('y',plotBottom+2+boxH/2);
  });

  svg.addEventListener('pointerleave',hide);
  svg.addEventListener('pointercancel',hide);
  scroller.addEventListener('scroll',hide);
}

function renderDailyChart(series,start,end,keepScroll,axisWOverride){
  const box=$('#daily-chart');
  if(!box)return;
  dailyChartArgs=[series,start,end];
  const from=Date.parse(start+'T00:00:00Z'), to=Date.parse(end+'T00:00:00Z');
  if(!Number.isFinite(from)||!Number.isFinite(to)||to<from){
    box.innerHTML='<div class="empty p-6 text-center text-slate-400">Pilih rentang tanggal yang valid untuk melihat grafik.</div>';
    return;
  }
  const count=Math.floor((to-from)/86400000)+1;
  if(count>36525){
    box.innerHTML='<div class="empty p-6 text-center text-slate-400">Rentang terlalu panjang untuk grafik harian; ringkasan tetap mencakup seluruh periode.</div>';
    return;
  }

  const daily=new Map((series||[]).map(r=>[r.date,{assets:Number(r.assets_cents)||0,expense:Number(r.expense_cents)||0}])),
        points=[];
  for(let i=0;i<count;i++){
    const date=new Date(from+i*86400000).toISOString().slice(0,10),
          value=daily.get(date)||{assets:0,expense:0};
    points.push({date,...value});
  }

  const cs=getComputedStyle(box),
        inner=box.clientWidth-(parseFloat(cs.paddingLeft)||0)-(parseFloat(cs.paddingRight)||0),
        axisW=axisWOverride||84,
        left=16, right=16, top=18, bottom=44, H=300, step=26,
        avail=Math.max(280,(inner>0?inner:720)-axisW),
        W=Math.max(avail,Math.round(left+right+(points.length-1)*step)),
        plotW=W-left-right, plotH=H-top-bottom, boxH=18,
        low=points.reduce((v,p)=>Math.min(v,p.assets,p.expense),0),
        high=points.reduce((v,p)=>Math.max(v,p.assets,p.expense),0),
        span=high-low||100,
        axisMin=low<0?low-span*.05:0,
        axisMax=high+span*.12,
        axisSpan=axisMax-axisMin,
        y=value=>top+((axisMax-value)/axisSpan)*plotH,
        x=i=>left+(points.length===1?plotW/2:(i/(points.length-1))*plotW),
        compact=n=>new Intl.NumberFormat('id-ID',{notation:'compact',maximumFractionDigits:1}).format(n),
        compact3=n=>new Intl.NumberFormat('id-ID',{notation:'compact',maximumFractionDigits:2}).format(n),
        dateLabel=s=>new Date(s+'T00:00:00').toLocaleDateString('id-ID',{day:'numeric',month:'short'}),
        gridLines=Array.from({length:5},(_,i)=>{
          const gy=top+plotH*(i/4);
          return `<line class="chart-grid" x1="0" y1="${gy}" x2="${W}" y2="${gy}"/>`;
        }).join(''),
        axisLabels=Array.from({length:5},(_,i)=>{
          const value=axisMax-axisSpan*(i/4), gy=top+plotH*(i/4);
          return `<text class="chart-axis" x="6" y="${gy+4}" text-anchor="start">Rp ${compact(value/100)}</text>`;
        }).join(''),
        makePath=key=>points.map((p,i)=>`${i?'L':'M'} ${x(i).toFixed(1)} ${y(p[key]).toFixed(1)}`).join(' '),
        ticks=points.length===1?1:Math.min(points.length,Math.max(2,Math.floor(plotW/90))),
        labels=Array.from({length:ticks},(_,i)=>{
          const index=ticks===1?0:Math.round(i*(points.length-1)/(ticks-1));
          return `<text class="chart-axis" x="${x(index)}" y="${H-12}" text-anchor="${index===0?'start':index===points.length-1?'end':'middle'}">${dateLabel(points[index].date)}</text>`;
        }).join(''),
        dots=points.length<=60?['assets','expense'].map(key=>points.map((p,i)=>`<circle class="chart-dot ${key}" cx="${x(i)}" cy="${y(p[key])}" r="3.5"><title>${dateLabel(p.date)} · ${key==='assets'?'Total aset':'Pengeluaran'}: ${rupiah(p[key])}</title></circle>`).join('')).join(''):'',
        last=points[points.length-1],
        tags=[
          {key:'assets',color:'#0d7a57',text:'Rp '+compact3(last.assets/100),y:y(last.assets)},
          {key:'expense',color:'#e05638',text:'Rp '+compact3(last.expense/100),y:y(last.expense)}
        ].sort((a,b)=>a.y-b.y),
        gap=boxH+2;

  if(tags[1].y-tags[0].y<gap){
    const mid=(tags[0].y+tags[1].y)/2;
    tags[0].y=mid-gap/2;
    tags[1].y=mid+gap/2;
  }
  tags.forEach(t=>{t.y=Math.min(Math.max(t.y,boxH/2),top+plotH)});

  const lastBoxes=tags.map(t=>{
    const w=Math.min(axisW-4,Math.round(t.text.length*6.2+14));
    return `<g class="chart-last ${t.key}"><rect x="2" y="${t.y-boxH/2}" width="${w}" height="${boxH}" rx="5" fill="${t.color}"/><text x="${2+w/2}" y="${t.y}" fill="#fff" font-size="11" font-weight="700" text-anchor="middle" dominant-baseline="central">${t.text}</text></g>`;
  }).join(''),
        prevScroll=box.querySelector('.chart-scroll')?.scrollLeft||0;

  box.innerHTML=`
    <div class="chart-wrap" style="display:flex;flex-wrap:nowrap;align-items:flex-start;width:100%;max-width:100%;height:auto">
      <div class="chart-scroll" style="flex:1 1 auto;min-width:0;overflow-x:auto;overflow-y:hidden">
        <svg class="chart-plot" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMinYMin meet" style="display:block;flex:none;width:${W}px;min-width:${W}px;max-width:none;height:${H}px;overflow:visible" role="img" aria-label="Grafik garis total aset dan pengeluaran per hari, dapat digeser ke kanan dan kiri">
          ${gridLines}${labels}
          <path class="chart-line assets" d="${makePath('assets')}"/>
          <path class="chart-line expense" d="${makePath('expense')}"/>
          ${dots}
          <g class="chart-crosshair" style="display:none;pointer-events:none">
            <line data-cx="v" stroke="#64748b" stroke-width="1.2" stroke-dasharray="4 3"/>
            <line data-cx="h" stroke="#64748b" stroke-width="1.2" stroke-dasharray="4 3"/>
            <g data-cx="xbox"><rect rx="6" fill="#0f172a"/><text fill="#fff" font-size="11" font-weight="700" text-anchor="middle" dominant-baseline="central"></text></g>
          </g>
        </svg>
      </div>
      <svg class="chart-yaxis" width="${axisW}" height="${H}" viewBox="0 0 ${axisW} ${H}" preserveAspectRatio="xMinYMin meet" style="display:block;flex:0 0 ${axisW}px;width:${axisW}px;min-width:${axisW}px;max-width:none;height:${H}px;overflow:visible" aria-hidden="true">
        ${axisLabels}${lastBoxes}
        <g class="chart-crosshair-y" style="display:none;pointer-events:none">
          <g data-cx="ybox"><rect rx="6" fill="#0f172a"/><text fill="#fff" font-size="11" font-weight="700" text-anchor="middle" dominant-baseline="central"></text></g>
        </g>
      </svg>
    </div>`;

  const ax=box.querySelector('.chart-yaxis');
  let need=0;
  ax.querySelectorAll('.chart-last').forEach(gr=>{
    const tx=gr.querySelector('text'), rc=gr.querySelector('rect'), len=tx.getComputedTextLength();
    if(len>0){
      const w=Math.ceil(len+14);
      rc.setAttribute('width',w);
      tx.setAttribute('x',2+w/2);
      need=Math.max(need,w+4);
    }
  });
  ax.querySelectorAll('.chart-axis').forEach(tx=>{
    const len=tx.getComputedTextLength();
    if(len>0) need=Math.max(need,Math.ceil(6+len+4));
  });

  const rpMax=axisMax/100, unit=rpMax>=1e12?1e12:rpMax>=1e9?1e9:rpMax>=1e6?1e6:rpMax>=1e3?1e3:1;
  [1,1e3,1e6,1e9,1e12].filter(u=>u<=unit).forEach(u=>{
    const probe=document.createElementNS('http://www.w3.org/2000/svg','text');
    probe.setAttribute('font-size','11');
    probe.setAttribute('font-weight','700');
    probe.textContent='Rp '+compact3(888.88*u);
    ax.appendChild(probe);
    const len=probe.getComputedTextLength();
    probe.remove();
    if(len>0) need=Math.max(need,Math.ceil(len+16));
  });

  if(need>0 && !axisWOverride && need!==axisW) return renderDailyChart(series,start,end,keepScroll,need);

  const scroller=box.querySelector('.chart-scroll');
  scroller.scrollLeft=keepScroll?prevScroll:scroller.scrollWidth;
  attachChartCrosshair(box,{W,left,right,top,plotW,plotH,axisW,axisMax,axisSpan,points,fmt:v=>'Rp '+compact3(v/100)});
  dailyChartWidth=box.clientWidth;

  if(!dailyChartObserver && window.ResizeObserver){
    dailyChartObserver=new ResizeObserver(()=>{
      const w=box.clientWidth;
      if(dailyChartArgs && w && Math.abs(w-dailyChartWidth)>1) renderDailyChart(...dailyChartArgs,true);
    });
    dailyChartObserver.observe(box);
  }
}

let moneyHidden=false;
const MONEY_IDS=['#assets','#income','#expense','#net','#income-top-amount','#expense-top-amount'], MONEY_MASK='••••••••',
EYE_SVG='<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></svg>',
EYE_OFF_SVG='<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/><path d="M3 3l18 18"/></svg>';

function setMoney(sel,text){
  const el=$(sel);
  if(!el)return;
  el.dataset.money=text;
  el.textContent=moneyHidden?MONEY_MASK:text;
}

// "Terbesar: <kategori> (<nominal>)" under the income/expense card amount.
// The amount sits in its own span so the eye toggle can mask it like the card totals.
function renderTopCategory(sel,totals,emptyText){
  const el=$(sel);
  if(!el)return;
  const top=Object.entries(totals||{}).sort((a,b)=>b[1]-a[1])[0];
  if(!top||!top[1]){
    el.textContent=emptyText;
    el.title='';
    return;
  }
  // Long names are shortened with an ellipsis; the amount always stays fully visible.
  el.innerHTML=`<span>Terbesar: </span><b>${h(top[0])}</b><span class="ov-top-amount"> (<span id="${sel.slice(1)}-amount"></span>)</span>`;
  el.title=`Kategori terbesar: ${top[0]} (${rupiah(top[1])})`;
  setMoney(sel+'-amount',rupiah(top[1]));
}

let currentRecentFilter = 'all';

function renderRecentList(){
  let tx = state.transactions || [];
  if(currentRecentFilter && currentRecentFilter !== 'all'){
    tx = tx.filter(t => t.kind === currentRecentFilter);
  }
  const el = $('#recent-list');
  if(!el) return;
  el.innerHTML = tx.slice(0, 5).map(row).join('') || '<div class="empty p-6 text-center text-slate-400">Tidak ada transaksi yang sesuai filter.</div>';
}

function applyMoneyVisibility(){
  MONEY_IDS.forEach(sel=>{
    const el=$(sel);
    if(el&&el.dataset.money!==undefined) el.textContent=moneyHidden?MONEY_MASK:el.dataset.money;
  });
  const btn=$('#money-toggle');
  if(!btn)return;
  const icon = btn.querySelector('#mask-icon') || btn;
  if(icon && icon.classList.contains('material-symbols-outlined')) {
    icon.textContent = moneyHidden ? 'visibility' : 'visibility_off';
  } else {
    btn.innerHTML = moneyHidden ? EYE_SVG : EYE_OFF_SVG;
  }
  btn.setAttribute('aria-pressed', String(!moneyHidden));
  const label = moneyHidden ? 'Tampilkan nominal' : 'Sembunyikan nominal';
  btn.setAttribute('aria-label', label);
  btn.title = label;
}

function initMoneyToggle(){
  const assets = $('#assets');
  if(!assets) return;
  MONEY_IDS.forEach(sel => {
    const el = $(sel);
    if(el && el.dataset.money === undefined) el.dataset.money = el.textContent;
  });
  let btn = $('#money-toggle');
  if(!btn){
    const wrap = document.createElement('span');
    wrap.className = 'money-wrap';
    wrap.style.cssText = 'display:inline-flex;align-items:center;gap:8px;max-width:100%';
    assets.parentNode.insertBefore(wrap, assets);
    btn = document.createElement('button');
    btn.type = 'button';
    btn.id = 'money-toggle';
    btn.className = 'ov-eye-btn';
    wrap.append(assets, btn);
  }
  btn.onclick = () => {
    moneyHidden = !moneyHidden;
    applyMoneyVisibility();
  };
  applyMoneyVisibility();
}

async function load(){
  const loadToken=++loadVersion;
  const range=timeRange(),
        behaviorYear=$("#behaviour-year")?.value,
        behaviorQuery=behaviorYear?`&behavior_year=${encodeURIComponent(behaviorYear)}`:"";
  let d=await api(`/api/bootstrap?start=${range.start}&end=${range.end}&today=${localDate()}${behaviorQuery}`);
  if(loadToken!==loadVersion)return;
  state=d;
  window.dispatchEvent(new Event('dashboard:loaded'));
  renderDailyChart(d.daily||[],d.range_start||range.start,d.range_end||range.end);
  sessionStorage.csrf=d.csrf||sessionStorage.csrf;

  setMoney('#assets',rupiah(d.summary.assets_cents));
  setMoney('#income',rupiah(d.summary.income_cents));
  setMoney('#expense',rupiah(d.summary.expense_cents));
  setMoney('#net',rupiah(d.summary.net_cents));
  renderTopCategory('#income-top',d.summary.income_categories,'Belum ada pemasukan bulan ini');
  renderTopCategory('#expense-top',d.summary.categories,'Belum ada pengeluaran bulan ini');

  renderNewTransactionsBadge();

  // Net card badge & note
  const netBadge = $('#net-badge');
  const netNote = $('#net-warning-note');
  const healthy = d.summary.net_cents >= 0;
  $('#net-card')?.classList.toggle('is-healthy', healthy);
  $('#net-card')?.classList.toggle('is-warning', !healthy);
  if(!healthy) {
    if(netBadge) {
      netBadge.textContent = 'WASPADA';
      netBadge.className = 'px-2 py-0.5 text-[10px] font-bold rounded-full bg-rose-100 text-rose-800 border border-rose-300 uppercase';
    }
    if(netNote) {
      // With no income yet a percentage is meaningless, so say that plainly instead.
      const note = d.summary.income_cents > 0
        ? `Pengeluaran melebihi pemasukan bulan ini sebesar ${((d.summary.expense_cents - d.summary.income_cents) / d.summary.income_cents * 100).toFixed(1)}%.`
        : 'Belum ada pemasukan bulan ini, sementara pengeluaran sudah berjalan.';
      netNote.innerHTML = `<p class="text-[11px] text-rose-900 font-medium leading-tight">⚠️ ${note}</p>`;
    }
  } else {
    if(netBadge) {
      netBadge.textContent = 'SEHAT';
      netBadge.className = 'px-2 py-0.5 text-[10px] font-bold rounded-full bg-emerald-100 text-emerald-800 border border-emerald-300 uppercase';
    }
    if(netNote) {
      netNote.innerHTML = `<p class="text-[11px] text-emerald-900 font-medium leading-tight">✨ Arus kas positif dan seimbang periode ini.</p>`;
    }
  }

  // Spending pattern
  const spendingTipEl = $('#spending-pattern-val');
  if(spendingTipEl) {
    if(d.behavior && d.behavior.spending) {
      const wd = Number(d.behavior.spending.weekday_average_cents)||0;
      const we = Number(d.behavior.spending.weekend_average_cents)||0;
      if(wd > we && we > 0) {
        const p = Math.round((wd - we) / we * 100);
        spendingTipEl.textContent = `Weekday lebih tinggi ${p}% dari weekend.`;
      } else if(we > wd && wd > 0) {
        const p = Math.round((we - wd) / wd * 100);
        spendingTipEl.textContent = `Weekend lebih tinggi ${p}% dari weekday.`;
      } else {
        spendingTipEl.textContent = `Pengeluaran weekday dan weekend relatif seimbang.`;
      }
    } else {
      spendingTipEl.textContent = `Weekday lebih tinggi 18% dari weekend.`;
    }
  }

  // Categories
  let cats = Object.entries(d.summary.categories).sort((a,b)=>b[1]-a[1]);
  let totalExp = cats.reduce((acc, [, val]) => acc + val, 0);
  $('#categories-chart').innerHTML = cats.length ? cats.map(([name, val]) => {
    const pct = totalExp > 0 ? (val / totalExp * 100).toFixed(1) : 0;
    const catObj = (state.categories || []).find(c => c.kind === 'expense' && c.name === name);
    const txCount = (state.transactions || []).filter(t => t.kind === 'expense' && (t.category === name || t.category_id == catObj?.id)).length;
    const conf = getCatIcon(name);
    return `
      <div class="category-summary-row p-3 rounded-xl border border-slate-100 bg-slate-50/50 hover:bg-slate-50 transition-colors">
        <div class="flex items-center justify-between mb-2">
          <div class="flex items-center space-x-3 min-w-0">
            ${categoryEmojiIcon(catObj) || `<div class="w-9 h-9 rounded-xl ${conf.bg} ${conf.text} flex items-center justify-center shrink-0 border ${conf.border}">
              <span class="material-symbols-outlined text-[18px]">${conf.icon}</span>
            </div>`}
            <div class="min-w-0">
              <h4 class="text-xs font-bold text-slate-900 truncate">${h(name)}</h4>
              <p class="text-[10px] text-slate-400 mt-0.5">${txCount} transaksi • ${conf.sub}</p>
            </div>
          </div>
          <div class="text-right shrink-0">
            <div class="text-xs font-extrabold text-slate-900">${rupiah(val)}</div>
            <span class="text-[10px] font-bold text-slate-400">${pct}%</span>
          </div>
        </div>
        <div class="w-full bg-slate-200/80 h-1.5 rounded-full overflow-hidden">
          <div class="${conf.barColor} h-full rounded-full transition-all duration-300" style="width: ${Math.max(4, pct)}%"></div>
        </div>
      </div>
    `;
  }).join('') : '<div class="empty p-6 text-center text-slate-400">Belum ada pengeluaran bulan ini.</div>';

  // Accounts
  const accountsSub = $('#accounts-subtitle');
  if(accountsSub) accountsSub.textContent = `${d.accounts.length} akun aktif tersinkronisasi`;
  $('#account-list').innerHTML = d.accounts.map(a => {
    let conf = getAccountBadge(a);
    return `
      <div class="p-3 rounded-xl border border-slate-100 bg-slate-50/60 hover:bg-slate-50 flex items-center justify-between transition-colors">
        <div class="flex items-center space-x-3 min-w-0">
          <div class="w-9 h-9 rounded-xl ${conf.bg} text-white flex items-center justify-center font-bold text-xs shadow-2xs shrink-0">
            ${conf.content}
          </div>
          <div class="min-w-0">
            <h4 class="text-xs font-bold text-slate-900 truncate">${h(a.name)}</h4>
            <span class="text-[10px] text-slate-400 font-mono">${conf.kindLabel}</span>
          </div>
        </div>
        <div class="text-xs font-bold text-slate-900 font-mono shrink-0 ml-3">${rupiah(a.balance_cents)}</div>
      </div>
    `;
  }).join('') || '<div class="empty p-6 text-center text-slate-400">Belum ada akun keuangan.</div>';

  $('#account-cards').innerHTML = d.accounts.map(a => {
    let iconText = a.kind==='cash'?'💵':a.kind==='ewallet'?'💳':'🏦';
    return `
      <article class="account-card">
        <span class="account-icon">${iconText}</span>
        <h3>${h(a.name)}</h3>
        <p class="text-xs text-slate-400 capitalize m-0">${h(a.kind)}</p>
        <strong>${rupiah(a.balance_cents)}</strong>
        <button type="button" class="account-delete" data-delete-account="${a.id}" title="Hapus akun" aria-label="Hapus akun ${h(a.name)}"><span class="material-symbols-outlined" aria-hidden="true">close</span></button>
      </article>
    `;
  }).join('') + addCard('Tambah akun baru','data-add-account');
  renderAssetComposition(d.accounts, d.summary.assets_cents);

  // Update recent total count and render recent list
  const recentCountEl = $('#recent-total-count');
  if(recentCountEl) recentCountEl.textContent = (d.transactions||[]).length;
  renderRecentList();
  renderTx();
  // A transaction added while the list is open is already being looked at.
  if(transactionListVisible()) markTransactionsSeen();
}

// The Transaksi table lives in history.js (own data source, filters, paging).
// load() calls this after every data change; history.js refreshes when it is on screen.
function renderTx(){
  window.renderHistory?.();
}

function show(view){
  $$('main section').forEach(s=>s.classList.toggle('hidden',s.id!==view));
  $$('.nav[data-view]').forEach(n=>n.classList.toggle('active',n.dataset.view===view));
  const titleMap = {
    overview: 'Dashboard',
    transactions: 'Transaksi',
    accounts: 'Akun & Dompet',
    budgetting: 'Budgeting',
    wishes: 'Wish',
    behaviour: 'Behaviour'
  };
  $('#heading').textContent = titleMap[view] || 'Dashboard';
  if(transactionListVisible()) window.historyOnShow?.();
  // The bar measures its blocks, so draw it once the tab is actually visible.
  if(view==='accounts'&&state.accounts) renderAssetComposition(state.accounts,state.summary?.assets_cents);
  if(transactionListVisible()) markTransactionsSeen();
}

function localDate(value){
  const d=value||new Date();
  return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0');
}

function shiftDays(value,amount){
  const d=new Date(value+'T00:00:00Z');
  d.setUTCDate(d.getUTCDate()+amount);
  return d.toISOString().slice(0,10);
}

function shiftMonths(value,amount){
  const [year,month,day]=value.split('-').map(Number),
        d=new Date(Date.UTC(year,month-1+amount,1)),
        last=new Date(Date.UTC(d.getUTCFullYear(),d.getUTCMonth()+1,0)).getUTCDate();
  d.setUTCDate(Math.min(day,last));
  return d.toISOString().slice(0,10);
}

function timeRange(){
  const end=localDate(), choice=$('#time-range').value;
  let start=end;
  if(choice==='1day') start=shiftDays(end,-1);
  else if(choice==='1week') start=shiftDays(end,-6);
  else if(choice==='1month') start=shiftMonths(end,-1);
  else if(choice==='3month') start=shiftMonths(end,-3);
  else if(choice==='1year') start=shiftMonths(end,-12);
  else if(choice==='all') start='0001-01-01';
  return {start,end};
}

function localDateTime(value){
  let d=value?new Date(value):new Date();
  if(Number.isNaN(d.getTime())) d=new Date();
  return new Date(d.getTime()-d.getTimezoneOffset()*60000).toISOString().slice(0,16);
}

function fillForm(){
  let cats=(state.categories||[]).filter(c=>c.kind===kind);
  $('#tx-form [name=category_id]').innerHTML=cats.map(c=>`<option value="${c.id}">${h(c.name)}</option>`).join('');
  $('#tx-form [name=account_id]').innerHTML=state.accounts.map(a=>`<option value="${a.id}">${h(a.name)}</option>`).join('');
  $('#tx-form [name=destination_id]').innerHTML=state.accounts.map(a=>`<option value="${a.id}">${h(a.name)}</option>`).join('');
  $('#destination-wrap').classList.toggle('hidden',kind!=='transfer');
  $('#category-wrap').classList.toggle('hidden',kind==='transfer');
  // Money comes out of the account for expenses/transfers and goes into it for income.
  $('#account-label').textContent=kind==='income'?'Akun Tujuan':'Akun Sumber';
  // Receipt photos belong to expenses and income, not to internal transfers.
  $('#tx-receipt-field')?.classList.toggle('hidden',kind==='transfer');
  const isTransfer=kind==='transfer', description=$('#tx-form [name=description]'),
        source=$('#tx-form [name=account_id]'), destination=$('#tx-form [name=destination_id]');
  // Start transfers with two different accounts instead of "Cash → Cash".
  if(isTransfer && destination.value===source.value){
    const other=[...destination.options].find(o=>o.value!==source.value);
    if(other) destination.value=other.value;
  }
  $('#description-label').textContent=isTransfer?'Catatan transfer':'Deskripsi / Catatan';
  description.placeholder=isTransfer?'Contoh: Penggantian talangan tunai makan tim via transfer BCA':'Contoh: Makan siang bareng tim, Bensin Pertamax';
}

let txRequestId=null, txSubmitting=false;

// Opens the transaction dialog; preset can pick kind, destination and description (used by Wish).
function openTxDialog(preset={}){
  $('#tx-form').reset();
  txRequestId=null;
  window.resetTxReceipt?.();
  window.resetSmartEntry?.();
  window.setSmartEntry?.(false);
  $('#tx-form [name=occurred_at]').value=localDateTime();
  kind=preset.kind||'expense';
  $$('.type-tabs button').forEach(b=>b.classList.toggle('selected',b.dataset.kind===kind));
  fillForm();
  const form=$('#tx-form');
  if(preset.destination_id){
    form.destination_id.value=preset.destination_id;
    const source=[...form.account_id.options].find(o=>o.value!==String(preset.destination_id));
    if(source && form.account_id.value===String(preset.destination_id)) form.account_id.value=source.value;
  }
  if(preset.description) form.description.value=preset.description;
  $('#tx-dialog').showModal();
}

$$('.nav[data-view]').forEach(b=>b.onclick=()=>show(b.dataset.view));
$$('[data-goto]').forEach(b=>b.onclick=()=>show(b.dataset.goto));

$('#time-range').value='1month';
$('#refresh').onclick=()=>load().then(()=>toast('Data berhasil dimuat ulang'));

/* Light / dark mode. The choice is remembered in this browser only (the <head> script
   applies it before the first paint); without a saved choice the app stays light. */
(()=>{
  const btn=$('#theme-toggle'), root=document.documentElement;
  const sync=()=>{
    const dark=root.dataset.theme==='dark';
    btn.setAttribute('aria-pressed',String(dark));
    btn.title=dark?'Mode terang':'Mode gelap';
    btn.setAttribute('aria-label',btn.title);
  };
  btn.onclick=()=>{
    const dark=root.dataset.theme!=='dark';
    if(dark) root.dataset.theme='dark'; else delete root.dataset.theme;
    try{ localStorage.setItem('theme',dark?'dark':'light'); }catch(e){}
    sync();
  };
  sync();
})();
$('#time-range').onchange=load;

$('#add').onclick=()=>openTxDialog();
// A closed dialog means a new entry next time, so it gets a fresh idempotency key.
$('#tx-dialog').addEventListener('close',()=>{ if(!txSubmitting) txRequestId=null; });

$$('.type-tabs button').forEach(b=>b.onclick=()=>{
  kind=b.dataset.kind;
  $$('.type-tabs button').forEach(x=>x.classList.toggle('selected',x===b));
  fillForm();
});

$('#close-tx').onclick=$('#cancel-tx').onclick=()=>$('#tx-dialog').close();

$('#tx-form').onsubmit=async e=>{
  e.preventDefault();
  // One save at a time, including while the date confirmation is open: a second Enter/click
  // would otherwise start a parallel save. The button is disabled during the request too.
  if(txSubmitting)return;
  txSubmitting=true;
  const form=e.target, button=$('#tx-submit'),
        f=new FormData(form);
  // The photo field is hidden for transfers, so never upload a photo picked before switching.
  if(kind==='transfer') f.delete('receipt');
  const receipt=f.get('receipt'),
        hasReceipt=receipt instanceof File && receipt.size>0;
  try{
    if(kind==='transfer' && f.get('account_id')===f.get('destination_id')){
      toast('Akun sumber dan akun tujuan transfer harus berbeda');
      return;
    }
    const occurredAt=(f.get('occurred_at')||localDateTime())+':00',
          dateWarning=unusualDateReason(occurredAt);
    if(dateWarning && !await askConfirm({eyebrow:'PERIKSA TANGGAL', title:'Tanggal transaksi tidak biasa', message:dateWarning+' Periksa kembali tanggalnya, terutama untuk hasil baca struk. Tetap simpan dengan tanggal ini?', confirmLabel:'Tetap simpan'})) return;

    setBusy(button,true);
    txRequestId=txRequestId||newRequestId();
    f.set('kind',kind);
    f.set('amount',digitsOnly(f.get('amount')));
    f.set('occurred_at',occurredAt);
    f.set('request_id',txRequestId);
    if(dateWarning) f.set('confirm_unusual_date','true');
    const data=Object.fromEntries(f);
    delete data.receipt;
    const send=()=>api('/api/transactions',{method:'POST',body:hasReceipt?f:JSON.stringify(data)});
    let result;
    try{
      result=await send();
    }catch(err){
      // The server applies the same date rule (its clock may differ); confirm and resend once.
      if(!err.data?.needs_date_confirmation) throw err;
      if(!await askConfirm({eyebrow:'PERIKSA TANGGAL', title:'Tanggal transaksi tidak biasa', message:err.data.date_warning+' Tetap simpan dengan tanggal ini?', confirmLabel:'Tetap simpan'})) return;
      f.set('confirm_unusual_date','true');
      data.confirm_unusual_date='true';
      result=await send();
    }
    txSubmitting=false;
    $('#tx-dialog').close();
    form.reset();
    window.resetTxReceipt?.();
    // e.g. "photo not stored because Google Drive is not set up" (Drive is optional).
    toast(result?.warnings?.[0]||'Transaksi tersimpan');
    await load();
  }catch(x){toast(x.message)}
  finally{
    txSubmitting=false;
    setBusy(button,false);
  }
};

// Dashed "Tambah akun baru" card (Akun & Dompet) and the overview shortcut open the same dialog.
document.addEventListener('click',e=>{ if(e.target.closest('[data-add-account]')) $('#account-dialog').showModal(); });
$('#close-account').onclick=$('#cancel-account').onclick=()=>$('#account-dialog').close();

$('#account-form').onsubmit=async e=>{
  e.preventDefault();
  const button=e.target.querySelector('button[type=submit]');
  if(button.disabled)return;
  setBusy(button,true);
  try{
    const data=Object.fromEntries(new FormData(e.target));
    data.initial_balance=digitsOnly(data.initial_balance);
    const result=await api('/api/accounts',{method:'POST',body:JSON.stringify(data)});
    $('#account-dialog').close();
    toast(result.reactivated?'Akun diaktifkan kembali':'Akun ditambahkan');
    await load();
  }catch(x){toast(x.message)}
  finally{setBusy(button,false)}
};

$('#close-delete-account').onclick=$('#cancel-delete-account').onclick=()=>$('#delete-account-dialog').close();

$('#delete-account-form').onsubmit=async e=>{
  e.preventDefault();
  const form=e.target,
        id=form.elements.namedItem('account_id').value,
        destination_id=form.elements.namedItem('destination_id').value;
  try{
    await api('/api/accounts/'+id,{method:'DELETE',body:JSON.stringify({destination_id,occurred_at:localDateTime()+':00'})});
    $('#delete-account-dialog').close();
    await load();
    toast('Saldo dialihkan dan akun dihapus');
  }catch(err){toast(err.message)}
};

document.addEventListener('change',async e=>{
  const select=e.target.closest('[data-tx-inline]');
  if(!select)return;
  const tx=(window.historyRows?.()||[]).concat(state.transactions||[]).find(x=>String(x.id)===select.dataset.txId);
  if(!tx)return;
  const field=select.dataset.txInline, previous=String(tx[field]??'');
  select.disabled=true;
  try{
    await api('/api/transactions/'+tx.id,{method:'PATCH',body:JSON.stringify({[field]:select.value})});
    await load();
    toast('Transaksi diperbarui');
  }catch(err){
    if(select.isConnected){
      select.value=previous;
      select.disabled=false;
    }
    toast(err.message);
  }
});

document.addEventListener('click',async e=>{
  const removeAccount=e.target.closest('[data-delete-account]');
  if(removeAccount){
    const account=state.accounts.find(a=>String(a.id)===removeAccount.dataset.deleteAccount);
    if(!account)return;
    if(Number(account.balance_cents)===0){
      if(!confirm(`Hapus akun ${account.name}? Riwayat transaksi lama tetap dipertahankan.`))return;
      try{
        await api('/api/accounts/'+account.id,{method:'DELETE',body:JSON.stringify({})});
        await load();
        toast('Akun dihapus');
      }catch(err){toast(err.message)}
      return;
    }
    const form=$('#delete-account-form'),
          destination=form.elements.namedItem('destination_id'),
          choices=state.accounts.filter(a=>String(a.id)!==String(account.id));
    form.elements.namedItem('account_id').value=account.id;
    destination.innerHTML=choices.map(a=>`<option value="${a.id}">${h(a.name)}</option>`).join('')||'<option value="">Tidak ada akun tujuan</option>';
    $('#delete-account-title').textContent='Alihkan saldo akun';
    $('#delete-account-message').textContent=`Saldo ${account.name} saat ini ${rupiah(account.balance_cents)}.`;
    $('#delete-account-hint').textContent=choices.length?(account.balance_cents<0?'Saldo negatif akan dibebankan ke akun tujuan yang dipilih.':'Saldo akan dipindahkan ke akun tujuan yang dipilih.'):'Akun lain diperlukan sebagai tujuan sebelum akun ini dapat dihapus.';
    form.querySelector('button.primary').disabled=!choices.length;
    $('#delete-account-dialog').showModal();
  }
});

document.addEventListener('click',async e=>{
  const b=e.target.closest('[data-delete]');
  if(!b)return;
  const label=b.dataset.deleteLabel?` ${b.dataset.deleteLabel}`:'';
  const ok=await askConfirm({eyebrow:'HAPUS TRANSAKSI',title:`Hapus transaksi${label}?`,message:'Transaksi akan dihapus permanen dan saldo akun dihitung ulang.',confirmLabel:'Hapus transaksi',danger:true});
  if(!ok)return;
  try{
    await api('/api/transactions/'+b.dataset.delete,{method:'DELETE'});
    toast('Transaksi dihapus');
    await load();
  }catch(x){toast(x.message)}
});

document.addEventListener('click', e => {
  const recentFilterBtn = e.target.closest('[data-recent-filter]');
  if(recentFilterBtn){
    document.querySelectorAll('[data-recent-filter]').forEach(b => {
      b.classList.remove('bg-emerald-700', 'text-white', 'shadow-2xs');
      b.classList.add('text-slate-600', 'hover:bg-slate-100');
    });
    recentFilterBtn.classList.remove('text-slate-600', 'hover:bg-slate-100');
    recentFilterBtn.classList.add('bg-emerald-700', 'text-white', 'shadow-2xs');
    currentRecentFilter = recentFilterBtn.dataset.recentFilter;
    renderRecentList();
    return;
  }

  if(e.target.closest('#manage-cats-btn')){
    show('transactions');
    const catTabBtn = document.querySelector('[data-transaction-tab="categories"]');
    if(catTabBtn) catTabBtn.click();
    return;
  }

  if(e.target.closest('#btn-add-account-overview')){
    const accDialog = document.querySelector('#account-dialog');
    if(accDialog && typeof accDialog.showModal === 'function') accDialog.showModal();
    return;
  }
});

const logout=async()=>{
  await api('/api/logout',{method:'POST',body:'{}'});
  location.href='/login';
};
$('#logout').onclick=logout;
document.addEventListener('click',e=>{ if(e.target.closest('[data-logout]')) logout(); });

initMoneyToggle();
load().catch(e=>toast(e.message));
