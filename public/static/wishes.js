(()=>{
  const money=cents=>new Intl.NumberFormat('id-ID',{style:'currency',currency:'IDR',maximumFractionDigits:0}).format((Number(cents)||0)/100);
  const monthYear=iso=>new Date(iso+'T00:00:00').toLocaleDateString('id-ID',{month:'long',year:'numeric'});
  const DEFICIT_TEXT='Arus kas bulanan masih defisit — tingkatkan surplus untuk menghitung estimasi.';
  const form=document.querySelector('#wish-form'),submitButton=form.querySelector('button[type="submit"]');
  const fundDialog=document.querySelector('#wish-fund-dialog'),fundForm=document.querySelector('#wish-fund-form');
  // Simulator picks survive re-renders (e.g. after a data reload).
  const simulation=new Map();

  const findWish=id=>(state.wishes||[]).find(w=>String(w.id)===String(id));
  const stats=()=>state.wish_stats||{};
  const surplus=()=>Number(stats().monthly_surplus_cents)||0;

  const currentMonth=()=>localDate().slice(0,7);
  const nextMonth=()=>shiftMonths(currentMonth()+'-01',1).slice(0,7);
  const monthsBetween=(fromYm,toYm)=>{
    const [fy,fm]=fromYm.split('-').map(Number),[ty,tm]=toYm.split('-').map(Number);
    return (ty*12+tm)-(fy*12+fm);
  };

  const renderRates=()=>{
    const s=stats(),value=surplus();
    // Only the empty state gets a note; with data the three numbers speak for themselves.
    const note=s.has_data?'':'Belum ada transaksi. Rata-rata dihitung setelah Anda mulai mencatat pemasukan dan pengeluaran.';
    document.querySelector('#wish-rates').innerHTML=`
      <div class="wish-rate-grid">
        <div><small>Rata-rata pemasukan / bulan</small><b class="green">${money(s.avg_income_cents)}</b></div>
        <div><small>Rata-rata pengeluaran / bulan</small><b class="coral">${money(s.avg_expense_cents)}</b></div>
        <div><small>Surplus bersih / bulan</small><b class="${value>0?'green':'coral'}">${value<0?'−':''}${money(Math.abs(value))}</b></div>
      </div>
      ${note?`<p class="wish-rate-note">${note}</p>`:''}`;
  };

  const projection=w=>{
    const remaining=Number(w.remaining_cents)||0;
    if(!remaining)return {text:'Target tercapai',tone:'green'};
    if(!stats().has_data)return {text:'Belum ada data transaksi untuk menghitung estimasi.',tone:'muted'};
    const rate=surplus();
    if(rate<=0)return {text:DEFICIT_TEXT,tone:'coral'};
    const months=Math.ceil(remaining/rate);
    return {text:`± ${months} bulan lagi · ${monthYear(shiftMonths(localDate(),months))}`,tone:'green'};
  };

  const simulationResult=(w,ym)=>{
    if(!ym)return '<span class="muted">Pilih bulan target untuk menghitung tabungan yang dibutuhkan per bulan.</span>';
    const months=monthsBetween(currentMonth(),ym),remaining=Number(w.remaining_cents)||0;
    if(months<=0)return '<span class="coral">Pilih bulan setelah bulan berjalan.</span>';
    if(!remaining)return '<span class="green">Target sudah terpenuhi.</span>';
    const need=Math.ceil(remaining/months),rate=surplus();
    const comparison=rate<=0
      ?'<small class="coral">Surplus bulanan Anda saat ini masih defisit.</small>'
      :need<=rate
        ?`<small class="green">Masih di bawah rata-rata surplus Anda (${money(rate)}/bulan).</small>`
        :`<small class="coral">Kurang ${money(need-rate)}/bulan dari kemampuan menabung saat ini (rata-rata surplus ${money(rate)}/bulan).</small>`;
    return `<span>Perlu menabung <b>${money(need)}</b> / bulan selama ${months} bulan.</span>${comparison}`;
  };

  const sourceLine=w=>{
    if(w.funding_mode==='account')return `Saldo akun <b>${h(w.linked_account_name)}</b>`;
    if(w.funding_mode==='account_missing')return `<span class="coral">Akun tertaut ${w.linked_account_name?h(w.linked_account_name)+' ':''}sudah diarsipkan. Edit target untuk memilih akun lain.</span>`;
    return 'Alokasi manual';
  };

  const card=w=>{
    const target=Number(w.target_cents)||0,progress=Math.max(0,Math.min(100,Number(w.progress_percent)||0)),remaining=Number(w.remaining_cents)||0,p=projection(w),sim=simulation.get(String(w.id))||'';
    const fundItem=w.funding_mode==='account'
      ?{label:'Tambah Dana (transfer)',icon:'savings',attrs:`data-wish-action="fund" data-wish-id="${w.id}"`}
      :{label:'Tambah Dana Manual',icon:'savings',attrs:`data-wish-action="fund" data-wish-id="${w.id}"`};
    const emptyHint=w.funding_mode==='manual'&&!Number(w.saved_cents)
      ?'<p class="wish-hint">Belum ada dana dialokasikan. Tambah dana manual, atau tautkan target ke kantong tabungan khusus lewat Edit Target.</p>':'';
    return `
      <article class="panel wish-card">
        <div class="wish-card-head">
          <h3 class="min-w-0">${h(w.name)}</h3>
          ${actionMenu([
            {label:'Edit Target',icon:'edit',attrs:`data-wish-action="edit" data-wish-id="${w.id}"`},
            fundItem,
            {label:'Hapus',icon:'delete',danger:true,attrs:`data-wish-action="delete" data-wish-id="${w.id}"`}
          ],'Opsi target '+w.name)}
        </div>
        <div class="wish-target"><span>Target ${money(target)}</span><b>${progress.toFixed(1)}%</b></div>
        <div class="wish-progress" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.round(progress)}" aria-label="Progres ${h(w.name)}"><i style="width:${progress}%"></i></div>
        <div class="wish-saved"><span>Dana terkumpul · ${sourceLine(w)}</span><b>${money(w.saved_cents)}</b></div>
        <div class="wish-remaining"><span>${remaining?`Sisa ${money(remaining)}`:'Target sudah terpenuhi'}</span><b class="${p.tone}">${p.text}</b></div>
        ${emptyHint}
        <div class="wish-sim">
          <label>
            <span>Simulasi target tanggal</span>
            <input type="month" min="${nextMonth()}" value="${h(sim)}" data-wish-sim="${w.id}" aria-label="Bulan target pencapaian ${h(w.name)}">
          </label>
          <div class="wish-sim-result" data-wish-sim-result="${w.id}" aria-live="polite">${simulationResult(w,sim)}</div>
        </div>
      </article>`;
  };

  const render=()=>{
    if(!Array.isArray(state.wishes))return;
    renderRates();
    const list=document.querySelector('#wish-list');
    // Dashed card at the end opens the create form.
    list.innerHTML=state.wishes.map(card).join('')+addCard('Tambah impian','data-add-wish');
  };

  /* ---------- Create / edit form ---------- */
  const fundingMode=()=>form.querySelector('[name=funding_mode]:checked')?.value||'manual';
  const syncFundingFields=()=>{
    const mode=fundingMode();
    form.querySelectorAll('[data-funding-field]').forEach(el=>el.classList.toggle('hidden',el.dataset.fundingField!==mode));
    form.elements.linked_account_id.required=mode==='account';
  };

  const fillAccountOptions=wishId=>{
    const select=form.elements.linked_account_id,taken=new Map();
    (state.wishes||[]).forEach(w=>{
      if(w.linked_account_id&&String(w.id)!==String(wishId))taken.set(String(w.linked_account_id),w.name);
    });
    select.innerHTML='<option value="">Pilih akun tabungan</option>'+(state.accounts||[]).map(a=>{
      const owner=taken.get(String(a.id));
      return `<option value="${a.id}" ${owner?'disabled':''}>${h(a.name)} · ${money(a.balance_cents)}${owner?` (dipakai: ${h(owner)})`:''}</option>`;
    }).join('');
  };

  const setFormMode=w=>{
    form.elements.wish_id.value=w?w.id:'';
    document.querySelector('#wish-form-eyebrow').textContent=w?'EDIT TARGET':'IMPIAN BARU';
    document.querySelector('#wish-form-title').textContent=w?'Edit target impian':'Target impian & tabungan';
  };

  // The form lives in a pop-up dialog (same pattern as "Tambah akun baru").
  const dialog=document.querySelector('#wish-dialog');
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
    syncFundingFields();
  });

  const openForm=w=>{
    form.reset();
    setFormMode(w);
    fillAccountOptions(w?.id);
    if(w){
      form.elements.name.value=w.name||'';
      form.elements.target.value=String(Math.round((Number(w.target_cents)||0)/100));
      formatMoneyInput(form.elements.target);
      const linked=w.funding_mode!=='manual';
      form.querySelector(`[name=funding_mode][value=${linked?'account':'manual'}]`).checked=true;
      if(linked&&[...form.elements.linked_account_id.options].some(o=>o.value===String(w.linked_account_id)&&!o.disabled))form.elements.linked_account_id.value=String(w.linked_account_id);
      form.elements.saved.value=String(Math.round((Number(w.manual_saved_cents)||0)/100));
      formatMoneyInput(form.elements.saved);
    }
    syncFundingFields();
    toggleForm(true);
  };

  form.addEventListener('change',e=>{if(e.target.name==='funding_mode')syncFundingFields()});

  window.addEventListener('dashboard:loaded',render);
  document.addEventListener('click',event=>{ if(event.target.closest('[data-add-wish]'))openForm(null); });
  document.querySelector('#close-wish-form').onclick=document.querySelector('#cancel-wish').onclick=closeForm;

  form.onsubmit=async event=>{
    event.preventDefault();
    if(submitButton.getAttribute('aria-busy')==='true')return;
    const raw=Object.fromEntries(new FormData(form)),wishId=raw.wish_id,mode=fundingMode();
    const data={name:raw.name,target:digitsOnly(raw.target),linked_account_id:mode==='account'?raw.linked_account_id:''};
    if(mode==='manual')data.saved=digitsOnly(raw.saved)||'0';
    setBusy(submitButton,true);
    try{
      await api(wishId?'/api/wishes/'+wishId:'/api/wishes',{method:wishId?'PUT':'POST',body:JSON.stringify(data)});
      closeForm();
      await load();
      toast(wishId?'Target diperbarui':'Impian ditambahkan');
    }catch(error){toast(error.message)}
    finally{setBusy(submitButton,false)}
  };

  /* ---------- Manual funds ---------- */
  const fundButton=fundForm.querySelector('button[type=submit]');
  document.querySelector('#close-wish-fund').onclick=document.querySelector('#cancel-wish-fund').onclick=()=>fundDialog.close();
  fundForm.onsubmit=async event=>{
    event.preventDefault();
    if(fundButton.getAttribute('aria-busy')==='true')return;
    const id=fundForm.elements.wish_id.value,amount=digitsOnly(fundForm.elements.amount.value);
    setBusy(fundButton,true);
    try{
      await api('/api/wishes/'+id+'/funds',{method:'POST',body:JSON.stringify({amount})});
      fundDialog.close();
      await load();
      toast('Dana ditambahkan ke target');
    }catch(error){toast(error.message)}
    finally{setBusy(fundButton,false)}
  };

  /* ---------- Card interactions ---------- */
  document.addEventListener('input',event=>{
    const input=event.target.closest('[data-wish-sim]');
    if(!input)return;
    const w=findWish(input.dataset.wishSim);
    if(!w)return;
    simulation.set(String(w.id),input.value);
    document.querySelector(`[data-wish-sim-result="${w.id}"]`).innerHTML=simulationResult(w,input.value);
  });

  document.addEventListener('click',async event=>{
    const action=event.target.closest('[data-wish-action]');
    if(!action)return;
    const w=findWish(action.dataset.wishId);
    if(!w)return;
    const type=action.dataset.wishAction;
    if(type==='edit'){
      openForm(w);
      return;
    }
    if(type==='fund'){
      if(w.funding_mode==='account'){
        // Linked wishes grow with the account balance, so money moves in via a real transfer.
        openTxDialog({kind:'transfer',destination_id:w.linked_account_id,description:'Menabung untuk '+w.name});
        return;
      }
      fundForm.reset();
      fundForm.elements.wish_id.value=w.id;
      document.querySelector('#wish-fund-title').textContent='Tambah dana: '+w.name;
      fundDialog.showModal();
      fundForm.elements.amount.focus();
      return;
    }
    if(type==='delete'){
      const ok=await askConfirm({
        eyebrow:'HAPUS TARGET',
        title:`Hapus target "${w.name}"?`,
        message:w.funding_mode==='manual'?'Target dan catatan alokasi manualnya akan dihapus. Saldo akun tidak berubah.':'Target akan dihapus. Saldo akun yang ditautkan tidak berubah.',
        confirmLabel:'Hapus target',
        danger:true
      });
      if(!ok)return;
      try{
        await api('/api/wishes/'+w.id,{method:'DELETE'});
        simulation.delete(String(w.id));
        await load();
        toast('Impian dihapus');
      }catch(error){toast(error.message)}
    }
  });

  syncFundingFields();
  if(Array.isArray(state.wishes))render();
})();
