/* Riwayat transaksi (tab Transaksi): plain-language filters, totals, and 10-row pages.
   Data comes from /api/transactions/history (all transactions, not just the dashboard range). */
(()=>{
  const PAGE_SIZE=10;
  const form=document.querySelector('#history-filters');
  const KIND_LABEL={income:'Pemasukan',expense:'Pengeluaran',transfer:'Transfer'};
  let rows=null, stale=true, inflight=null, page=1;

  window.historyRows=()=>rows||[];

  /* ---------- data ---------- */
  const visible=()=>typeof transactionListVisible==='function'&&transactionListVisible();

  async function refresh(){
    if(inflight){ stale=true; return inflight; }
    if(!rows) document.querySelector('#all-list').innerHTML='<div class="empty p-10 text-center text-slate-400">Memuat riwayat transaksi…</div>';
    stale=false;
    inflight=api('/api/transactions/history').then(d=>{
      rows=d.transactions||[];
      fillOptions();
      render();
    }).catch(err=>{
      if(!rows) document.querySelector('#all-list').innerHTML=`<div class="empty p-10 text-center text-rose-600">${h(err.message)}</div>`;
      else toast(err.message);
    }).finally(()=>{
      inflight=null;
      if(stale&&visible()) refresh(); // data changed again while loading
    });
    return inflight;
  }

  // Called by load() after every data change; refetch now if the list is on screen, else on next visit.
  window.renderHistory=()=>{ stale=true; if(visible()) refresh(); };
  window.historyOnShow=()=>{ if(!rows||stale) refresh(); else render(); };

  /* ---------- filters ---------- */
  const values=()=>{
    const f=Object.fromEntries(new FormData(form));
    return {
      keyword:(f.keyword||'').trim().toLowerCase(),
      kind:f.kind||'', category:f.category||'', account:f.account||'',
      from:f.from||'', to:f.to||'',
      min:digitsOnly(f.min)?Number(digitsOnly(f.min)):null,
      max:digitsOnly(f.max)?Number(digitsOnly(f.max)):null,
      order:f.order||'newest', top:Number(digitsOnly(f.top))||0,
    };
  };

  // Filters inside the panel (the search box is always visible, so it is not counted).
  const activeFilterCount=f=>[f.kind, f.category, f.account, f.from||f.to, f.min!==null||f.max!==null, f.order!=='newest', f.top].filter(Boolean).length;

  function fillOptions(){
    const kind=form.elements.kind.value, catSelect=form.elements.category, accSelect=form.elements.account;
    const keepCat=catSelect.value, keepAcc=accSelect.value;
    // Active categories plus archived ones that still appear in history.
    const cats=new Map((state.categories||[]).map(c=>[String(c.id),{id:String(c.id),name:c.name,kind:c.kind,archived:false}]));
    (rows||[]).forEach(t=>{ if(t.category_id&&!cats.has(String(t.category_id))) cats.set(String(t.category_id),{id:String(t.category_id),name:t.category||'Kategori arsip',kind:t.kind,archived:true}); });
    const opt=c=>`<option value="${h(c.id)}">${h(c.name)}${c.archived?' (arsip)':''}</option>`;
    const sorted=list=>list.sort((a,b)=>a.name.localeCompare(b.name,'id'));
    if(kind==='transfer'){
      catSelect.innerHTML='<option value="">Transfer tidak berkategori</option>';
      catSelect.disabled=true;
    }else{
      catSelect.disabled=false;
      const groups=(kind?[kind]:['expense','income']).map(k=>{
        const list=sorted([...cats.values()].filter(c=>c.kind===k));
        return kind?list.map(opt).join(''):`<optgroup label="${KIND_LABEL[k]}">${list.map(opt).join('')}</optgroup>`;
      }).join('');
      catSelect.innerHTML='<option value="">Semua kategori</option>'+groups;
    }
    catSelect.value=[...catSelect.options].some(o=>o.value===keepCat)?keepCat:'';

    const accs=new Map((state.accounts||[]).map(a=>[String(a.id),{id:String(a.id),name:a.name,archived:false}]));
    (rows||[]).forEach(t=>[[t.account_id,t.account],[t.destination_id,t.destination]].forEach(([id,name])=>{
      if(id&&!accs.has(String(id))) accs.set(String(id),{id:String(id),name:name||'Akun arsip',archived:true});
    }));
    accSelect.innerHTML='<option value="">Semua akun</option>'+sorted([...accs.values()]).map(opt).join('');
    accSelect.value=[...accSelect.options].some(o=>o.value===keepAcc)?keepAcc:'';
  }

  const day=t=>String(t.occurred_at||'').slice(0,10);
  const amount=t=>(Number(t.amount_cents)||0)/100;

  function matches(t,f){
    if(f.kind&&t.kind!==f.kind) return false;
    if(f.category&&String(t.category_id)!==f.category) return false;
    if(f.account&&String(t.account_id)!==f.account&&String(t.destination_id)!==f.account) return false;
    if(f.from&&day(t)<f.from) return false;
    if(f.to&&day(t)>f.to) return false;
    if(f.min!==null&&amount(t)<f.min) return false;
    if(f.max!==null&&amount(t)>f.max) return false;
    if(f.keyword){
      // Every word must appear somewhere in the row (e.g. "kopi gopay" finds a coffee paid with GoPay).
      const text=[t.description,t.original_input,t.category,t.account,t.destination,t.payment_method,KIND_LABEL[t.kind]].filter(Boolean).join(' ').toLowerCase();
      if(!f.keyword.split(/\s+/).every(word=>text.includes(word))) return false;
    }
    return true;
  }

  const ORDER={
    newest:(a,b)=>String(b.occurred_at).localeCompare(String(a.occurred_at))||(b.seq||0)-(a.seq||0),
    oldest:(a,b)=>String(a.occurred_at).localeCompare(String(b.occurred_at))||(a.seq||0)-(b.seq||0),
    largest:(a,b)=>(Number(b.amount_cents)||0)-(Number(a.amount_cents)||0)||(b.seq||0)-(a.seq||0),
    smallest:(a,b)=>(Number(a.amount_cents)||0)-(Number(b.amount_cents)||0)||(b.seq||0)-(a.seq||0),
  };

  /* ---------- period shortcuts ---------- */
  function periodRange(key){
    const today=localDate(), [y,m]=today.split('-').map(Number), pad=n=>String(n).padStart(2,'0');
    const lastDay=(yy,mm)=>new Date(yy,mm,0).getDate();
    if(key==='today') return [today,today];
    if(key==='7d') return [shiftDays(today,-6),today];
    if(key==='month') return [`${y}-${pad(m)}-01`,today];
    if(key==='lastmonth'){ const py=m===1?y-1:y, pm=m===1?12:m-1; return [`${py}-${pad(pm)}-01`,`${py}-${pad(pm)}-${pad(lastDay(py,pm))}`]; }
    if(key==='year') return [`${y}-01-01`,today];
    return ['',''];
  }

  function syncChips(f){
    document.querySelectorAll('#history-filters [data-period]').forEach(b=>{
      const [from,to]=periodRange(b.dataset.period);
      b.setAttribute('aria-pressed',String(from===f.from&&to===f.to));
    });
  }

  /* ---------- plain-language summary ---------- */
  const shortDate=iso=>new Date(iso+'T00:00:00').toLocaleDateString('id-ID',{day:'numeric',month:'short',year:'numeric'});

  function describe(f){
    const parts=[];
    parts.push(f.kind?KIND_LABEL[f.kind].toLowerCase():'semua jenis transaksi');
    if(f.category) parts.push('kategori '+(form.elements.category.selectedOptions[0]?.textContent||''));
    if(f.account) parts.push('akun '+(form.elements.account.selectedOptions[0]?.textContent||''));
    if(f.keyword) parts.push(`mengandung “${f.keyword}”`);
    if(f.from&&f.to) parts.push(f.from===f.to?'tanggal '+shortDate(f.from):`${shortDate(f.from)} – ${shortDate(f.to)}`);
    else if(f.from) parts.push('sejak '+shortDate(f.from));
    else if(f.to) parts.push('sampai '+shortDate(f.to));
    if(f.min!==null&&f.max!==null) parts.push(`nominal ${rupiah(f.min*100)} – ${rupiah(f.max*100)}`);
    else if(f.min!==null) parts.push(`nominal ≥ ${rupiah(f.min*100)}`);
    else if(f.max!==null) parts.push(`nominal ≤ ${rupiah(f.max*100)}`);
    if(f.top) parts.push(`${f.top} ${({largest:'terbesar',smallest:'terkecil',oldest:'terlama',newest:'terbaru'})[f.order]}`);
    return 'Menampilkan: '+parts.join(' · ');
  }

  // The total answers "berapa total …?". It only appears when every result is the same type
  // (e.g. all expenses), because adding income and expenses together would be meaningless.
  function renderSummary(f,matched,shown){
    const box=document.querySelector('#history-summary');
    const filtering=f.keyword||activeFilterCount(f);
    if(!matched.length){
      box.innerHTML=filtering?'<p class="hs-empty">Tidak ada transaksi yang cocok dengan pencarian atau filter ini.</p>':'';
      return;
    }
    const list=f.top?shown:matched, kinds=new Set(list.map(t=>t.kind));
    if(!filtering||kinds.size!==1){ box.innerHTML=''; return; }
    const kind=[...kinds][0], total=list.reduce((s,t)=>s+(Number(t.amount_cents)||0),0), avg=Math.round(total/list.length);
    const scope=f.top?`${shown.length} teratas dari ${matched.length} transaksi yang cocok`:`${matched.length} transaksi`;
    box.innerHTML=`
      <div class="hs-main ${kind}">
        <small>Total ${KIND_LABEL[kind].toLowerCase()}${f.top?' (yang ditampilkan)':''}</small>
        <b>${rupiah(total)}</b>
        <span>${scope} · rata-rata ${rupiah(avg)} per transaksi</span>
      </div>`;
  }

  /* ---------- table ---------- */
  const dateText=value=>{
    if(!value) return '—';
    const d=new Date(value);
    return Number.isNaN(d.getTime())?'—':d.toLocaleString('id-ID',{dateStyle:'medium',timeStyle:'short'});
  };
  const tone=t=>t.kind==='income'?'green':t.kind==='expense'?'coral':'blue';

  function selectCell(t,field,choices,current,currentName,emptyLabel,label){
    const exists=choices.some(c=>String(c.id)===String(current));
    const archived=!exists&&current?`<option value="${h(current)}" selected disabled>${h(currentName||'Arsip')} (arsip)</option>`:!current?`<option value="" selected disabled>${emptyLabel}</option>`:'';
    return `<select class="tx-inline-select" data-tx-inline="${field}" data-tx-id="${h(t.id)}" aria-label="${label} transaksi nomor ${t.seq||''}">${archived}${choices.map(c=>`<option value="${h(c.id)}" ${String(c.id)===String(current)?'selected':''}>${h(c.name)}</option>`).join('')}</select>`;
  }

  function idCell(t){
    return `<td class="tx-no-cell">
      <span class="tx-no">${t.seq??'—'}</span>
      <div class="action-menu id-menu" data-action-menu>
        <button type="button" class="action-menu-trigger" aria-haspopup="menu" aria-expanded="false" aria-label="Opsi transaksi nomor ${t.seq||''}" title="ID Firestore & hapus">
          <span class="material-symbols-outlined text-[18px]" aria-hidden="true">more_vert</span>
        </button>
        <div class="action-menu-list" role="menu" hidden>
          <div class="id-pop"><small>ID Firestore</small><code>${h(t.id)}</code></div>
          <button type="button" role="menuitem" data-copy-id="${h(t.id)}"><span class="material-symbols-outlined text-[18px]" aria-hidden="true">content_copy</span><span>Salin ID</span></button>
          <button type="button" role="menuitem" class="danger" data-delete="${h(t.id)}" data-delete-label="nomor ${t.seq??''}"><span class="material-symbols-outlined text-[18px]" aria-hidden="true">delete</span><span>Hapus transaksi</span></button>
        </div>
      </div>
    </td>`;
  }

  function table(items){
    if(!items.length) return '<div class="empty p-10 text-center text-slate-400">Transaksi tidak ditemukan.</div>';
    const accounts=state.accounts||[];
    return `
      <div class="table-scroll">
        <table class="tx-table">
          <thead><tr>
            <th>No.</th><th>Tanggal transaksi</th><th>Jenis</th><th>Nominal</th><th>Kategori</th>
            <th>Akun sumber</th><th>Akun tujuan</th><th>Deskripsi</th><th>Input asli / Struk</th>
          </tr></thead>
          <tbody>${items.map(t=>{
            const url=t.receipt_drive_url||(t.receipt_drive_id?'https://drive.google.com/open?id='+encodeURIComponent(t.receipt_drive_id):'');
            const category=t.kind==='transfer'?'<span class="text-slate-400">—</span>'
              :selectCell(t,'category_id',(state.categories||[]).filter(c=>c.kind===t.kind),t.category_id,t.category,'Pilih kategori','Kategori');
            // Income lands in its account, so that account is shown as "Akun tujuan".
            const empty='<span class="text-slate-400">—</span>';
            const source=t.kind==='income'?empty
              :selectCell(t,'account_id',accounts.filter(a=>t.kind!=='transfer'||String(a.id)!==String(t.destination_id)),t.account_id,t.account,'Pilih akun','Akun sumber');
            const destination=t.kind==='income'?selectCell(t,'account_id',accounts,t.account_id,t.account,'Pilih akun','Akun tujuan')
              :t.kind!=='transfer'?empty
              :selectCell(t,'destination_id',accounts.filter(a=>String(a.id)!==String(t.account_id)),t.destination_id,t.destination,'Pilih akun','Akun tujuan');
            return `<tr>
              ${idCell(t)}
              <td class="text-slate-600 font-medium">${h(dateText(t.occurred_at))}</td>
              <td><span class="kind-pill ${tone(t)}">${KIND_LABEL[t.kind]||h(t.kind)}</span></td>
              <td class="table-amount ${tone(t)}">${t.kind==='income'?'+':t.kind==='expense'?'−':''}${rupiah(t.amount_cents)}</td>
              <td>${category}</td>
              <td>${source}</td>
              <td>${destination}</td>
              <td class="text-slate-800 font-semibold max-w-[200px] truncate" title="${h(t.description||'—')}">${h(t.description||'—')}</td>
              <td class="original-cell">
                ${t.original_input?`<span class="truncate block max-w-[160px]">${h(t.original_input)}</span>`:''}
                ${url?`<a class="receipt-link" href="${h(url)}" target="_blank" rel="noopener">📎 ${h(t.receipt_name||'struk.jpg')}</a>`:t.receipt_file?`<a class="receipt-link" href="/api/receipts/${encodeURIComponent(t.receipt_file)}" target="_blank" rel="noopener">📎 struk.${h(t.receipt_file.split('.').pop())}</a>`:!t.original_input?'—':''}
              </td>
            </tr>`;
          }).join('')}</tbody>
        </table>
      </div>`;
  }

  /* ---------- paging: 1–10, 11–20, … ---------- */
  function pageNumbers(current,total){
    if(total<=7) return Array.from({length:total},(_,i)=>i+1);
    const set=new Set([1,total,current-1,current,current+1].filter(n=>n>=1&&n<=total));
    const list=[...set].sort((a,b)=>a-b), out=[];
    list.forEach((n,i)=>{ if(i&&n-list[i-1]>1) out.push('…'); out.push(n); });
    return out;
  }

  function renderPager(total){
    const pager=document.querySelector('#history-pager'), pages=Math.max(1,Math.ceil(total/PAGE_SIZE));
    if(total<=PAGE_SIZE){ pager.innerHTML=total?`<span class="hp-range">Menampilkan ${total===1?'1':`1–${total}`} dari ${total}</span>`:''; return; }
    const first=(page-1)*PAGE_SIZE+1, last=Math.min(page*PAGE_SIZE,total);
    pager.innerHTML=`
      <span class="hp-range">Menampilkan ${first===last?first:`${first}–${last}`} dari ${total}</span>
      <div class="hp-buttons">
        <button type="button" data-page="${page-1}" ${page===1?'disabled':''} aria-label="Halaman sebelumnya"><span class="material-symbols-outlined" aria-hidden="true">chevron_left</span></button>
        ${pageNumbers(page,pages).map(n=>n==='…'?'<span class="hp-gap">…</span>':`<button type="button" data-page="${n}" ${n===page?'aria-current="page"':''} aria-label="Halaman ${n}: transaksi ${(n-1)*PAGE_SIZE+1}–${Math.min(n*PAGE_SIZE,total)}">${n}</button>`).join('')}
        <button type="button" data-page="${page+1}" ${page===pages?'disabled':''} aria-label="Halaman berikutnya"><span class="material-symbols-outlined" aria-hidden="true">chevron_right</span></button>
      </div>`;
  }

  function render(){
    if(!rows) return;
    const f=values();
    const matched=rows.filter(t=>matches(t,f)).sort(ORDER[f.order]||ORDER.newest);
    const shown=f.top?matched.slice(0,f.top):matched;
    const pages=Math.max(1,Math.ceil(shown.length/PAGE_SIZE));
    page=Math.min(Math.max(1,page),pages);
    syncChips(f);
    const count=activeFilterCount(f), badge=document.querySelector('#hf-count');
    badge.hidden=!count;
    badge.textContent=count;
    document.querySelector('#hf-toggle').classList.toggle('has-filters',count>0);
    document.querySelector('#hf-toggle').setAttribute('aria-label',count?`Filter (${count} aktif)`:'Filter');
    document.querySelector('#hf-footer').hidden=!(count||f.keyword);
    document.querySelector('#hf-description').textContent=describe(f);
    renderSummary(f,matched,shown);
    document.querySelector('#all-list').innerHTML=table(shown.slice((page-1)*PAGE_SIZE,page*PAGE_SIZE));
    renderPager(shown.length);
  }

  /* ---------- events ---------- */
  form.addEventListener('submit',e=>e.preventDefault());
  const toggle=document.querySelector('#hf-toggle'), panel=document.querySelector('#hf-panel');
  toggle.onclick=()=>{
    panel.hidden=!panel.hidden;
    toggle.setAttribute('aria-expanded',String(!panel.hidden));
    toggle.classList.toggle('open',!panel.hidden);
  };
  // "Tampilkan" accepts digits only.
  form.elements.top.addEventListener('input',e=>{ const v=digitsOnly(e.target.value); if(v!==e.target.value) e.target.value=v; });
  form.addEventListener('input',()=>{ page=1; render(); });
  form.addEventListener('change',e=>{
    if(e.target.name==='kind') fillOptions();
    page=1;
    render();
  });
  form.addEventListener('click',e=>{
    const chip=e.target.closest('[data-period]');
    if(!chip)return;
    const [from,to]=periodRange(chip.dataset.period);
    form.elements.from.value=from;
    form.elements.to.value=to;
    page=1;
    render();
  });
  document.querySelector('#hf-reset').onclick=()=>{
    form.reset();
    fillOptions();
    page=1;
    render();
  };
  document.querySelector('#history-pager').addEventListener('click',e=>{
    const btn=e.target.closest('[data-page]');
    if(!btn||btn.disabled)return;
    page=Number(btn.dataset.page);
    render();
    document.querySelector('.tx-table-card')?.scrollIntoView({behavior:'smooth',block:'start'});
  });

  // The ID popover sits inside a scrolling table; pin it to the viewport so it is never clipped.
  document.addEventListener('click',e=>{
    const trigger=e.target.closest('.id-menu .action-menu-trigger');
    if(!trigger)return;
    const list=trigger.parentElement.querySelector('.action-menu-list');
    if(list.hidden)return;
    const r=trigger.getBoundingClientRect();
    list.style.position='fixed';
    list.style.right='auto';
    list.style.top=`${Math.min(r.bottom+4,window.innerHeight-list.offsetHeight-8)}px`;
    list.style.left=`${Math.max(8,Math.min(r.left,window.innerWidth-list.offsetWidth-8))}px`;
  });
  const closeOnScroll=()=>{ if(document.querySelector('.id-menu .action-menu-list:not([hidden])')) closeActionMenus(); };
  window.addEventListener('scroll',closeOnScroll,{passive:true});
  document.addEventListener('scroll',e=>{ if(e.target.classList?.contains('table-scroll')) closeOnScroll(); },{capture:true,passive:true});

  document.addEventListener('click',async e=>{
    const copy=e.target.closest('[data-copy-id]');
    if(!copy)return;
    const id=copy.dataset.copyId;
    try{
      await navigator.clipboard.writeText(id);
      toast('ID Firestore disalin');
    }catch{
      // Clipboard API needs HTTPS; fall back to a temporary selection on plain-HTTP LAN access.
      const area=Object.assign(document.createElement('textarea'),{value:id});
      document.body.append(area);
      area.select();
      const ok=document.execCommand('copy');
      area.remove();
      toast(ok?'ID Firestore disalin':'ID: '+id);
    }
  });

  // Category/account lists may load after this script; refresh option lists when data reloads.
  window.addEventListener('dashboard:loaded',()=>{ if(rows) fillOptions(); });
})();
