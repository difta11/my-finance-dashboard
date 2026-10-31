(()=>{
  const money=cents=>new Intl.NumberFormat('id-ID',{style:'currency',currency:'IDR',maximumFractionDigits:0}).format((Number(cents)||0)/100);
  const etaText=months=>{
    const targetDate=shiftMonths(localDate(),months);
    return new Date(targetDate+'T00:00:00').toLocaleDateString('id-ID',{month:'long',year:'numeric'});
  };
  const render=()=>{
    if(!Array.isArray(state.wishes))return;
    const stats=state.wish_stats||{},assets=Number(stats.current_assets_cents)||0,days=Math.max(1,Number(stats.period_days)||90),monthlyIncome=Math.round((Number(stats.income_90d_cents)||0)*30/days),monthlyExpense=Math.round((Number(stats.expense_90d_cents)||0)*30/days),monthlyAsset=Math.round((Number(stats.asset_change_90d_cents)||0)*30/days);
    document.querySelector('#wish-rates').innerHTML=`<div class="wish-rate-grid"><div><small>Pemasukan / bulan</small><b class="green">${money(monthlyIncome)}</b></div><div><small>Pengeluaran / bulan</small><b class="coral">${money(monthlyExpense)}</b></div><div><small>Penambahan aset / bulan</small><b class="${monthlyAsset>=0?'green':'coral'}">${money(monthlyAsset)}</b></div></div><p class="wish-rate-note">Perkiraan memakai perubahan saldo aset aktual selama ${days} hari terakhir.</p>`;
    const list=document.querySelector('#wish-list');
    list.innerHTML=state.wishes.length?state.wishes.map(w=>{
      const target=Number(w.target_cents)||0,progress=target?Math.max(0,Math.min(100,assets/target*100)):0,remaining=Math.max(0,target-assets),projection=remaining===0?'Impian tercapai':monthlyAsset>0?`Sekitar ${Math.ceil(remaining/monthlyAsset)} bulan lagi - ${etaText(Math.ceil(remaining/monthlyAsset))}`:'Belum dapat diprediksi karena aset belum bertambah';
      return `<article class="panel wish-card"><div class="wish-card-head"><div><p class="eyebrow">TARGET IMPIAN</p><h3>${h(w.name)}</h3></div><button class="category-archive" data-delete-wish="${w.id}" title="Hapus impian">Hapus</button></div><div class="wish-target"><span>Target ${money(target)}</span><b>${progress.toFixed(1)}%</b></div><div class="wish-progress"><i style="width:${progress}%"></i></div><div class="wish-saved"><span>Total aset saat ini</span><b>${money(assets)}</b></div><div class="wish-remaining"><span>${remaining?`Sisa ${money(remaining)}`:'Target sudah terpenuhi'}</span><b>${projection}</b></div></article>`
    }).join(''):'<div class="panel empty">Belum ada impian. Tambahkan target pertama Anda.</div>';
  };
  const form=document.querySelector('#wish-form'),showButton=document.querySelector('#show-wish-form');
  const toggleForm=visible=>{
    form.classList.toggle('hidden',!visible);
    showButton.classList.toggle('hidden',visible);
    if(visible)form.elements.name.focus();
  };
  window.addEventListener('dashboard:loaded',render);
  showButton.onclick=()=>toggleForm(true);
  document.querySelector('#close-wish-form').onclick=document.querySelector('#cancel-wish').onclick=()=>{
    form.reset();
    toggleForm(false);
  };
  form.onsubmit=async event=>{
    event.preventDefault();
    const data=Object.fromEntries(new FormData(form));
    data.target=digitsOnly(data.target);
    try{
      await api('/api/wishes',{method:'POST',body:JSON.stringify(data)});
      form.reset();
      toggleForm(false);
      await load();
      toast('Impian ditambahkan');
    }catch(error){toast(error.message)}
  };
  document.addEventListener('click',async event=>{
    const button=event.target.closest('[data-delete-wish]');
    if(!button||!confirm('Hapus impian ini?'))return;
    try{
      await api('/api/wishes/'+button.dataset.deleteWish,{method:'DELETE'});
      await load();
      toast('Impian dihapus');
    }catch(error){toast(error.message)}
  });
  if(Array.isArray(state.wishes))render();
})();