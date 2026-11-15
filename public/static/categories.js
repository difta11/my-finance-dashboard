(()=>{
  const tabs=[...document.querySelectorAll('[data-transaction-tab]')];
  const dialog=document.querySelector('#category-dialog'),form=document.querySelector('#category-form'),submitButton=form.querySelector('button[type=submit]');
  const KIND_LABEL={expense:'Pengeluaran',income:'Pemasukan'};
  const QUICK_EMOJI=['🍔','🍜','☕','🧋','🛒','🛍️','⛽','🚗','🛵','🚌','🏠','💡','📱','🌐','🎮','🎬','🎵','🏥','💊','📚','🎓','✈️','🏖️','🐱','👶','🎁','💼','💰','💵','📈','🏦','🧾'];
  const SWATCHES=['#fee2e2','#ffedd5','#fef3c7','#ecfccb','#d1fae5','#cffafe','#dbeafe','#e0e7ff','#f3e8ff','#fce7f3','#e2e8f0','#1e293b'];

  const getCategoryDetails = (c) => {
    const text = (c.name || '').toLowerCase();
    if(c.kind === 'income') {
      if(/gaji|salary|upah/.test(text)) return { icon: 'payments', bg: 'bg-emerald-50 text-emerald-700 border-emerald-100', badge: '' };
      if(/saku|tunjangan|bonus|hadiah/.test(text)) return { icon: 'card_giftcard', bg: 'bg-purple-50 text-purple-700 border-purple-100', badge: '' };
      if(/investasi|dividen|saham|reksadana|crypto/.test(text)) return { icon: 'trending_up', bg: 'bg-teal-50 text-teal-700 border-teal-100', badge: '' };
      if(/freelance|proyek|side/.test(text)) return { icon: 'laptop_mac', bg: 'bg-indigo-50 text-indigo-700 border-indigo-100', badge: '' };
      return { icon: 'arrow_downward', bg: 'bg-emerald-50 text-emerald-700 border-emerald-100', badge: '' };
    }
    if(/makan|minum|food|beverage|resto|kopi/.test(text)) return { icon: 'restaurant', bg: 'bg-amber-50 text-amber-700 border-amber-100', badge: '' };
    if(/hiburan|game|movie|nonton|rekreasi/.test(text)) return { icon: 'movie', bg: 'bg-purple-50 text-purple-700 border-purple-100', badge: '' };
    if(/bensin|transport|bbm|tol|ojek/.test(text)) return { icon: 'local_gas_station', bg: 'bg-blue-50 text-blue-700 border-blue-100', badge: '' };
    if(/internet|pulsa|wifi|data|paket/.test(text)) return { icon: 'wifi', bg: 'bg-cyan-50 text-cyan-700 border-cyan-100', badge: '' };
    return { icon: 'label', bg: 'bg-slate-100 text-slate-600 border-slate-200', badge: '' };
  };

  // Custom emoji icon when the user picked one, otherwise the automatic icon based on the name.
  const iconHtml=(c,size='lg')=>categoryEmojiIcon(c,size)||(()=>{
    const d=getCategoryDetails(c);
    return `<span class="category-icon category-icon-${size} ${d.bg} border" aria-hidden="true"><span class="material-symbols-outlined">${d.icon}</span></span>`;
  })();

  const render=()=>{
    const items=state.categories||[];
    for(const kind of ['expense','income']){
      const list=document.querySelector('#category-'+kind+'-list'),
            group=items.filter(c=>c.kind===kind);
      list.innerHTML=group.length?group.map(c=>{
        const count=Number(c.transaction_count)||0;
        const details=getCategoryDetails(c);
        const badge=details.badge?`<span class="text-[10px] font-bold px-1.5 py-0.5 rounded bg-amber-100 text-amber-800">${details.badge}</span>`:'';
        return `
          <div class="category-row group flex items-center justify-between p-3.5 rounded-xl bg-white border border-slate-200/80 shadow-xs hover:shadow-md hover:bg-slate-50/70 transition-all mb-3 last:mb-0">
            <div class="flex items-center gap-3.5 min-w-0">
              ${iconHtml(c)}
              <div class="min-w-0">
                <div class="flex items-center gap-2">
                  <b class="font-bold text-sm text-slate-900 truncate">${h(c.name)}</b>
                  ${badge}
                </div>
                <small class="text-xs text-slate-500 block mt-0.5">${count} transaksi</small>
              </div>
            </div>
            <div class="category-actions flex items-center gap-1 shrink-0 ml-3">
              <button type="button" class="category-edit w-8 h-8 rounded-lg flex items-center justify-center text-slate-400 hover:text-emerald-700 hover:bg-slate-100 transition-all" data-edit-category="${c.id}" title="Edit nama, ikon, dan warna" aria-label="Edit kategori ${h(c.name)}">
                <span class="material-symbols-outlined text-[18px]">edit</span>
              </button>
              <button type="button" class="category-delete w-8 h-8 rounded-lg flex items-center justify-center text-slate-400 hover:text-rose-600 hover:bg-rose-50 transition-all ${count?'disabled opacity-40 cursor-not-allowed':''}" data-delete-category="${c.id}" data-category-name="${h(c.name)}" ${count?'disabled':''} title="${count?'Kategori masih digunakan oleh transaksi':'Hapus kategori'}" aria-label="Hapus ${h(c.name)}">
                <span class="material-symbols-outlined text-[18px]">remove</span>
              </button>
            </div>
          </div>
        `;
      }).join(''):'<div class="empty p-6 text-center text-slate-400">Belum ada kategori.</div>';
    }
  };

  const selectTab=tab=>{
    const isCategories=tab==='categories';
    document.querySelector('#transaction-list-view').classList.toggle('hidden',isCategories);
    document.querySelector('#transaction-categories-view').classList.toggle('hidden',!isCategories);
    tabs.forEach(b=>{
      const selected=b.dataset.transactionTab===tab;
      b.classList.toggle('selected',selected);
      b.setAttribute('aria-selected',String(selected));
    });
    document.querySelector('#heading').textContent=isCategories?'Kategori':'Transaksi';
    if(isCategories)render();
    else{ markTransactionsSeen(); window.historyOnShow?.(); }
  };

  tabs.forEach(b=>b.onclick=()=>selectTab(b.dataset.transactionTab));
  document.querySelector('.sidebar .nav[data-view="transactions"]').addEventListener('click',()=>selectTab('transactions'));

  /* ---------- Add / edit dialog with emoji + background colour ---------- */
  const emojiGrid=document.querySelector('#category-emoji-grid'),swatchRow=document.querySelector('#category-swatches');
  const colorInput=form.elements.icon_bg,iconInput=form.elements.icon;
  emojiGrid.innerHTML=QUICK_EMOJI.map(e=>`<button type="button" class="emoji-choice" data-emoji="${e}" aria-label="Pilih ${e}">${e}</button>`).join('');
  swatchRow.insertAdjacentHTML('afterbegin',SWATCHES.map(c=>`<button type="button" class="swatch" data-swatch="${c}" style="background:${c}" aria-label="Warna ${c}"></button>`).join(''));

  const updatePreview=()=>{
    const kind=form.elements.kind.value,icon=iconInput.value.trim(),bg=colorInput.value;
    const preview={name:form.elements.name.value.trim()||'Nama kategori',kind,icon,icon_bg:bg};
    const target=document.querySelector('#category-preview-icon');
    target.outerHTML=iconHtml(preview,'xl').replace('<span class="category-icon','<span id="category-preview-icon" class="category-icon');
    document.querySelector('#category-preview-name').textContent=preview.name;
    document.querySelector('#category-preview-kind').textContent=`Kategori ${KIND_LABEL[kind]||''}${icon?'':' · ikon bawaan'}`;
    emojiGrid.querySelectorAll('[data-emoji]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.emoji===icon)));
    swatchRow.querySelectorAll('[data-swatch]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.swatch===bg.toLowerCase())));
  };

  const openDialog=({kind,category}={})=>{
    form.reset();
    form.elements.category_id.value=category?.id||'';
    form.elements.kind.value=category?.kind||kind;
    form.elements.name.value=category?.name||'';
    iconInput.value=category?.icon||'';
    colorInput.value=category?.icon_bg||'#d1fae5';
    const label=KIND_LABEL[form.elements.kind.value].toLowerCase();
    document.querySelector('#category-dialog-eyebrow').textContent=category?'EDIT KATEGORI':'KATEGORI BARU';
    document.querySelector('#category-dialog-title').textContent=category?`Edit kategori ${label}`:`Tambah kategori ${label}`;
    form.elements.name.placeholder=form.elements.kind.value==='income'?'Contoh: Komisi Freelance, Dividen':'Contoh: Perawatan Kucing, Kopi & Snack';
    updatePreview();
    dialog.showModal();
    form.elements.name.focus();
  };

  form.addEventListener('input',updatePreview);
  emojiGrid.addEventListener('click',e=>{
    const choice=e.target.closest('[data-emoji]');
    if(!choice)return;
    iconInput.value=choice.dataset.emoji;
    updatePreview();
  });
  swatchRow.addEventListener('click',e=>{
    const swatch=e.target.closest('[data-swatch]');
    if(!swatch)return;
    colorInput.value=swatch.dataset.swatch;
    updatePreview();
  });
  document.querySelector('#category-reset-icon').onclick=()=>{
    iconInput.value='';
    updatePreview();
  };
  document.querySelector('#close-category').onclick=document.querySelector('#cancel-category').onclick=()=>dialog.close();

  form.onsubmit=async e=>{
    e.preventDefault();
    if(submitButton.getAttribute('aria-busy')==='true')return;
    const id=form.elements.category_id.value,icon=iconInput.value.trim();
    const body={name:form.elements.name.value,kind:form.elements.kind.value,icon,icon_bg:icon?colorInput.value:''};
    setBusy(submitButton,true);
    try{
      const result=await api(id?'/api/categories/'+id:'/api/categories',{method:id?'PUT':'POST',body:JSON.stringify(body)});
      dialog.close();
      await load();
      render();
      toast(id?'Kategori diperbarui':result.reactivated?'Kategori diaktifkan kembali':'Kategori ditambahkan');
    }catch(err){toast(err.message)}
    finally{setBusy(submitButton,false)}
  };

  document.addEventListener('click',async e=>{
    const add=e.target.closest('[data-add-category]');
    if(add){
      openDialog({kind:add.dataset.addCategory});
      return;
    }
    const edit=e.target.closest('[data-edit-category]');
    if(edit){
      const category=state.categories.find(c=>String(c.id)===edit.dataset.editCategory);
      if(category)openDialog({category});
      return;
    }
    const remove=e.target.closest('[data-delete-category]');
    if(!remove||remove.disabled)return;
    const ok=await askConfirm({eyebrow:'HAPUS KATEGORI',title:`Hapus kategori "${remove.dataset.categoryName}"?`,message:'Kategori yang belum dipakai transaksi atau budget akan dihapus dari daftar.',confirmLabel:'Hapus kategori',danger:true});
    if(!ok)return;
    try{
      const categoryId=remove.dataset.deleteCategory;
      const result=await api('/api/categories/'+categoryId,{method:'DELETE',body:'{}'});
      if(!result.ok)throw Error('Kategori gagal dihapus');
      state.categories=(state.categories||[]).filter(c=>String(c.id)!==String(categoryId));
      render();
      await load();
      if((state.categories||[]).some(c=>String(c.id)===String(categoryId)))throw Error('Kategori masih aktif. Muat ulang data lalu coba lagi.');
      render();
      toast('Kategori dihapus');
    }catch(err){toast(err.message)}
  });

  window.addEventListener('dashboard:loaded',render);
  if(Array.isArray(state.categories))render();
})();
