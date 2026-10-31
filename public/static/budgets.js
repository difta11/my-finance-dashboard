(()=>{
  const money=cents=>new Intl.NumberFormat('id-ID',{style:'currency',currency:'IDR',maximumFractionDigits:0}).format((Number(cents)||0)/100);
  const fillOptions=(select,items,emptyLabel)=>{
    const selected=select.value;
    select.innerHTML=items.length?items.map(item=>`<option value="${item.id}">${h(item.name)}</option>`).join(''):`<option value="">${emptyLabel}</option>`;
    if(items.some(item=>String(item.id)===selected))select.value=selected;
  };
  const render=()=>{
    const categories=(state.categories||[]).filter(item=>item.kind==='expense');
    const accounts=state.accounts||[];
    fillOptions(document.querySelector('#budget-category'),categories,'Buat kategori pengeluaran terlebih dahulu');
    fillOptions(document.querySelector('#budget-account'),accounts,'Buat akun terlebih dahulu');
    const submit=document.querySelector('#budget-form button[type="submit"]');
    submit.disabled=!categories.length||!accounts.length;
    const budgets=state.budgets||[];
    const grid=document.querySelector('#budget-grid');
    grid.innerHTML=budgets.length?budgets.map(budget=>{
      const percent=Math.max(0,Math.min(100,Number(budget.remaining_percent)||0));
      const over=Number(budget.overspent_cents)||0;
      return `<article class="panel budget-card"><div class="budget-card-head"><div><p class="eyebrow">BUDGET KEBUTUHAN</p><h3>${h(budget.name)}</h3></div><button type="button" class="category-archive" data-delete-budget="${budget.id}" title="Hapus budget">Hapus</button></div><div class="budget-context"><span>Kategori: <b>${h(budget.category||'—')}</b></span><span>Sumber dana: <b>${h(budget.account||'—')}</b></span></div><div class="budget-progress-label"><span>${money(budget.remaining_cents)} tersisa</span><b class="${percent<=20?'coral':'green'}">${percent}%</b></div><div class="budget-progress"><i class="${percent<=20?'low':''}" style="width:${percent}%"></i></div><div class="budget-totals"><span>Alokasi <b>${money(budget.allocated_cents)}</b></span><span>Terpakai <b>${money(budget.spent_cents)}</b></span></div>${over?`<p class="budget-over">Melebihi budget ${money(over)}</p>`:''}<p class="budget-note">Pengeluaran kategori ini setelah budget dibuat akan mengurangi sisa budget.</p></article>`
    }).join(''):'<article class="panel empty budget-empty">Belum ada budget. Buat budget pertama, lalu hubungkan dengan kategori pengeluaran.</article>';
  };
  window.addEventListener('dashboard:loaded',render);
  document.querySelector('#budget-form').onsubmit=async event=>{
    event.preventDefault();
    const form=event.currentTarget,data=Object.fromEntries(new FormData(form));
    data.amount=digitsOnly(data.amount);
    try{
      await api('/api/budgets',{method:'POST',body:JSON.stringify(data)});
      form.reset();
      await load();
      toast('Budget dibuat');
    }catch(error){toast(error.message)}
  };
  document.addEventListener('click',async event=>{
    const button=event.target.closest('[data-delete-budget]');
    if(!button||!confirm('Hapus budget ini? Riwayat transaksi dan saldo akun tidak berubah.'))return;
    try{
      await api('/api/budgets/'+button.dataset.deleteBudget,{method:'DELETE'});
      await load();
      toast('Budget dihapus');
    }catch(error){toast(error.message)}
  });
  if(Array.isArray(state.budgets))render();
})();
