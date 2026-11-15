(()=>{
  const money=cents=>new Intl.NumberFormat('id-ID',{style:'currency',currency:'IDR',maximumFractionDigits:0}).format((Number(cents)||0)/100);
  const pct=value=>new Intl.NumberFormat('id-ID',{maximumFractionDigits:1}).format(Number(value)||0);
  const form=document.querySelector('#budget-form');
  const submitButton=form.querySelector('button[type="submit"]');
  const detailDialog=document.querySelector('#budget-detail-dialog');

  const findBudget=id=>(state.budgets||[]).find(item=>String(item.id)===String(id));

  // Sidebar dot: hidden while every budget is green; otherwise the colour of the most urgent one
  // (any red budget makes it red, even if others are green or yellow).
  const URGENCY={safe:0,warning:1,danger:2,over:2};
  const renderNavDot=budgets=>{
    const dot=document.querySelector('#nav-budget-dot');
    if(!dot)return;
    const level=Math.max(0,...budgets.map(b=>URGENCY[b.status]??0));
    dot.hidden=level===0;
    dot.className='nav-budget-dot'+(level===2?' is-danger':level===1?' is-warning':'');
    const label=level===2?'Ada budget yang hampir habis atau terlampaui':'Ada budget yang mulai menipis';
    dot.title=level?label:'';
    dot.setAttribute('aria-label',level?label:'');
    dot.setAttribute('role','img');
  };
  const dayLabel=iso=>new Date(iso+'T00:00:00').toLocaleDateString('id-ID',{day:'numeric',month:'short',year:'numeric'});

  // One-month period: 15 Nov -> 14 Des; 31 Jan -> 28 Feb (same rule as the server's reset).
  const oneMonthEnd=start=>{ const next=shiftMonths(start,1); return next.slice(8)===start.slice(8)?shiftDays(next,-1):next; };
  const setOneMonth=()=>{
    const start=form.elements.period_start.value||localDate();
    form.elements.period_start.value=start;
    form.elements.period_end.value=oneMonthEnd(start);
  };
  // What "Reset" will create: same length for dated budgets, one month for calendar-month ones.
  const nextPeriod=budget=>{
    const today=localDate();
    if(!budget.custom_period) return [today,oneMonthEnd(today)];
    const days=Math.round((Date.parse(budget.period_end)-Date.parse(budget.period_start))/86400000);
    return [today,shiftDays(today,days)];
  };

  const setFormMode=budget=>{
    form.elements.budget_id.value=budget?budget.id:'';
    document.querySelector('#budget-form-eyebrow').textContent=budget?'EDIT ANGGARAN':'ANGGARAN BARU';
    document.querySelector('#budget-form-title').textContent=budget?'Edit budget':'Buat alokasi budget';
  };

  // The form lives in a pop-up dialog (same pattern as "Tambah akun baru").
  const dialog=document.querySelector('#budget-dialog');
  const toggleForm=visible=>{
    if(visible){
      if(!dialog.open) dialog.showModal();
      form.elements.name.focus();
    }else if(dialog.open){
      dialog.close();
    }
  };

  const closeForm=()=>toggleForm(false);
  // Any way of closing (Batal, ×, Esc, after saving) leaves a clean form for next time.
  dialog.addEventListener('close',()=>{
    form.reset();
    setFormMode(null);
    document.querySelector('#budget-spent-hint').hidden=true;
  });

  const fillCategoryOptions=()=>{
    const select=document.querySelector('#budget-category');
    if(!select)return;
    const items=(state.categories||[]).filter(item=>item.kind==='expense');
    const selected=select.value;
    select.innerHTML=items.length?items.map(item=>`<option value="${item.id}">${h(item.name)}</option>`).join(''):'<option value="">Buat kategori pengeluaran terlebih dahulu</option>';
    if(items.some(item=>String(item.id)===selected))select.value=selected;
    submitButton.disabled=!items.length;
  };

  const openEdit=budget=>{
    fillCategoryOptions();
    setFormMode(budget);
    form.elements.name.value=budget.name||'';
    form.elements.amount.value=String(Math.round((Number(budget.allocated_cents)||0)/100));
    formatMoneyInput(form.elements.amount);
    if([...form.elements.category_id.options].some(o=>o.value===String(budget.category_id)))form.elements.category_id.value=String(budget.category_id);
    // Calendar-month budgets keep the dates empty (they repeat every month).
    form.elements.period_start.value=budget.custom_period?budget.period_start:'';
    form.elements.period_end.value=budget.custom_period?budget.period_end:'';
    const hint=document.querySelector('#budget-spent-hint');
    hint.innerHTML=`Terpakai saat ini <b>${money(budget.spent_cents)}</b> dari alokasi ${money(budget.allocated_cents)} (${h(budget.period_label)}). Ubah <b>Nominal alokasi</b> di atas untuk menambah atau mengurangi budget.`;
    hint.hidden=false;
    toggleForm(true);
  };

  const usageLine=budget=>{
    if(budget.status==='over')
      return `<span class="budget-over-label">Overbudget ${money(budget.overspent_cents)} (${pct(budget.overspent_percent)}%)</span>`;
    return `<span>${money(budget.remaining_cents)} tersisa</span>`;
  };

  const dailyLine=budget=>{
    const days=Number(budget.days_left)||0;
    if(budget.period_state==='upcoming')return `Periode dimulai ${h(dayLabel(budget.period_start))}.`;
    if(budget.period_state==='ended')return `Periode berakhir ${h(dayLabel(budget.period_end))}. Edit tanggal atau reset untuk memulai periode baru.`;
    return `Batas belanja harian: <b>${money(budget.daily_allowance_cents)}</b> / hari untuk ${days} hari tersisa.`;
  };

  // 100% used: the card changes look and offers Reset or Hapus right away.
  const exhaustedPanel=budget=>`
    <div class="budget-exhausted">
      <span class="material-symbols-outlined" aria-hidden="true">block</span>
      <div>
        <b>${budget.status==='over'?`Budget terlampaui ${money(budget.overspent_cents)}`:'Budget sudah habis'}</b>
        <small>${money(budget.spent_cents)} dari ${money(budget.allocated_cents)} terpakai. Reset untuk memulai periode baru, atau hapus budget ini.</small>
      </div>
    </div>
    <div class="budget-exhausted-actions">
      <button type="button" class="primary compact" data-budget-action="reset" data-budget-id="${budget.id}"><span class="material-symbols-outlined text-[16px]" aria-hidden="true">restart_alt</span><span>Reset budget</span></button>
      <button type="button" class="secondary danger-outline" data-budget-action="delete" data-budget-id="${budget.id}"><span class="material-symbols-outlined text-[16px]" aria-hidden="true">delete</span><span>Hapus</span></button>
    </div>`;

  const card=budget=>{
    const status=budget.status||'safe', bar=Math.max(0,Math.min(100,Number(budget.bar_percent)||0));
    const exhausted=Boolean(budget.exhausted);
    return `
      <article class="budget-card status-${status}${exhausted?' is-exhausted':''}" data-budget-card="${budget.id}">
        <div>
          <div class="budget-card-head">
            <div class="min-w-0">
              <h3>${h(budget.name)}</h3>
              <p class="eyebrow budget-period-eyebrow">${h(String(budget.period_label||'').toUpperCase())}</p>
            </div>
            ${actionMenu([
              {label:'Edit Budget',icon:'edit',attrs:`data-budget-action="edit" data-budget-id="${budget.id}"`},
              {label:'Hapus Budget',icon:'delete',danger:true,attrs:`data-budget-action="delete" data-budget-id="${budget.id}"`}
            ],'Opsi budget '+budget.name)}
          </div>
          <div class="budget-context">
            <span>Kategori: <b>${h(budget.category||'Kategori diarsipkan')}</b></span>
          </div>
          <div class="budget-progress-label">
            ${usageLine(budget)}
            <b>${pct(budget.used_percent)}% terpakai</b>
          </div>
          <div class="budget-progress" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.round(bar)}" aria-label="${pct(budget.used_percent)}% alokasi terpakai">
            <i style="width:${bar}%"></i>
          </div>
        </div>
        <div>
          <div class="budget-totals">
            <span>Alokasi <b>${money(budget.allocated_cents)}</b></span>
            <span>Terpakai <b>${money(budget.spent_cents)}</b></span>
          </div>
          ${exhausted?exhaustedPanel(budget):`<p class="budget-daily">${dailyLine(budget)}</p>`}
          <button type="button" class="budget-detail-link" data-budget-detail="${budget.id}" aria-haspopup="dialog">
            Lihat rincian · ${(budget.transactions||[]).length} transaksi
            <span class="material-symbols-outlined text-[16px]" aria-hidden="true">chevron_right</span>
          </button>
        </div>
      </article>
    `;
  };

  const render=()=>{
    fillCategoryOptions();
    const budgets=state.budgets||[];
    const grid=document.querySelector('#budget-grid');
    if(!grid)return;

    // Dashed card at the end opens the create form (replaces the old "Buat budget baru" button).
    grid.innerHTML=budgets.map(card).join('')+addCard('Buat budget baru','data-add-budget');
    renderNavDot(budgets);

    // Keep an open detail dialog in sync after a reload.
    if(detailDialog.open&&detailDialog.dataset.budgetId){
      const current=findBudget(detailDialog.dataset.budgetId);
      if(current)fillDetail(current);else detailDialog.close();
    }
  };

  const fillDetail=budget=>{
    detailDialog.dataset.budgetId=budget.id;
    document.querySelector('#budget-detail-period').textContent=`PERIODE ${String(budget.period_label||'').toUpperCase()}`;
    document.querySelector('#budget-detail-title').textContent=budget.name;
    document.querySelector('#budget-detail-summary').innerHTML=`
      <div><small>Alokasi</small><b>${money(budget.allocated_cents)}</b></div>
      <div><small>Terpakai</small><b class="${budget.status==='over'?'coral':''}">${money(budget.spent_cents)}</b></div>
      <div><small>${budget.status==='over'?'Overbudget':'Sisa'}</small><b class="${budget.status==='over'?'coral':'green'}">${money(budget.status==='over'?budget.overspent_cents:budget.remaining_cents)}</b></div>
      <p>Pengeluaran kategori <b>${h(budget.category)}</b> dengan tanggal transaksi pada ${h(budget.period_label)}.</p>`;
    const items=budget.transactions||[];
    document.querySelector('#budget-detail-list').innerHTML=items.length?`
      <ul>
        ${items.map(tx=>{
          const when=new Date(tx.occurred_at).toLocaleString('id-ID',{day:'numeric',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit'});
          return `<li>
            <div class="min-w-0">
              <b>${h(tx.description||budget.category||'Pengeluaran')}</b>
              <small>${h(when)}${tx.account?' · '+h(tx.account):''}${tx.payment_method?' · '+h(tx.payment_method):''}</small>
            </div>
            <span>−${money(tx.amount_cents)}</span>
          </li>`;
        }).join('')}
      </ul>`
      :'<p class="empty text-center text-slate-400 py-8">Belum ada pengeluaran di kategori ini pada periode aktif.</p>';
  };

  const openDetail=budget=>{
    fillDetail(budget);
    detailDialog.showModal();
  };

  window.addEventListener('dashboard:loaded',render);
  document.addEventListener('click',event=>{
    if(!event.target.closest('[data-add-budget]'))return;
    form.reset();
    setFormMode(null);
    fillCategoryOptions();
    setOneMonth(); // new budgets start with a one-month period from today
    toggleForm(true);
  });
  form.querySelector('[data-budget-period="1m"]').onclick=setOneMonth;
  document.querySelector('#cancel-budget-form').onclick=document.querySelector('#cancel-budget').onclick=closeForm;
  document.querySelector('#close-budget-detail').onclick=()=>detailDialog.close();

  form.onsubmit=async event=>{
    event.preventDefault();
    if(submitButton.getAttribute('aria-busy')==='true')return;
    const data=Object.fromEntries(new FormData(form));
    const budgetId=data.budget_id;
    delete data.budget_id;
    data.amount=digitsOnly(data.amount);
    if(Boolean(data.period_start)!==Boolean(data.period_end)){ toast('Isi tanggal mulai dan selesai, atau kosongkan keduanya'); return; }
    if(data.period_start&&data.period_end<data.period_start){ toast('Tanggal selesai harus sama atau setelah tanggal mulai'); return; }
    setBusy(submitButton,true);
    try{
      await api(budgetId?'/api/budgets/'+budgetId:'/api/budgets',{method:budgetId?'PUT':'POST',body:JSON.stringify(data)});
      closeForm();
      await load();
      toast(budgetId?'Budget diperbarui':'Budget berhasil dibuat');
    }catch(error){toast(error.message)}
    finally{
      setBusy(submitButton,false);
      fillCategoryOptions();
    }
  };

  document.addEventListener('click',async event=>{
    const action=event.target.closest('[data-budget-action]');
    if(action){
      const budget=findBudget(action.dataset.budgetId);
      if(!budget)return;
      if(action.dataset.budgetAction==='edit'){
        openEdit(budget);
        return;
      }
      if(action.dataset.budgetAction==='reset'){
        const [from,to]=nextPeriod(budget);
        const ok=await askConfirm({
          eyebrow:'RESET BUDGET',
          title:`Reset budget "${budget.name}"?`,
          message:`Periode baru ${dayLabel(from)} – ${dayLabel(to)} dengan alokasi ${money(budget.allocated_cents)}. Pengeluaran sebelum ${dayLabel(from)} tidak dihitung lagi; riwayat transaksi tidak berubah.`,
          confirmLabel:'Reset budget'
        });
        if(!ok)return;
        try{
          await api('/api/budgets/'+budget.id+'/reset',{method:'POST',body:'{}'});
          await load();
          toast('Budget direset ke periode baru');
        }catch(error){toast(error.message)}
        return;
      }
      const ok=await askConfirm({
        eyebrow:'HAPUS BUDGET',
        title:`Hapus budget "${budget.name}"?`,
        message:'Budget dan alokasinya akan dihapus permanen. Riwayat transaksi dan saldo akun tidak berubah.',
        confirmLabel:'Hapus budget',
        danger:true
      });
      if(!ok)return;
      try{
        await api('/api/budgets/'+budget.id,{method:'DELETE'});
        await load();
        toast('Budget dihapus');
      }catch(error){toast(error.message)}
      return;
    }
    // Only the "Lihat rincian" link opens the transaction breakdown.
    const detailLink=event.target.closest('[data-budget-detail]');
    if(detailLink){
      const budget=findBudget(detailLink.dataset.budgetDetail);
      if(budget)openDetail(budget);
    }
  });

  if(Array.isArray(state.budgets))render();
})();
