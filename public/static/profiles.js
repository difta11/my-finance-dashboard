/* Profiles: one login, several profiles, each with its own accounts/transactions/budgets/wishes.
   The sidebar drop-up (and the phone account menu) lists them, switches between them,
   and offers "Tambah profil" / "Edit profil ini" (where a profile can also be deleted).
   Also shows the storage-mode notice (local file vs Firebase, set in .env). */
(()=>{
  const q=s=>document.querySelector(s);
  const dialog=q('#profile-dialog'), form=q('#profile-form');
  let data={active:'default',profiles:[]};

  const initials=name=>(String(name||'').trim().split(/\s+/).filter(Boolean).slice(0,2).map(w=>w[0].toUpperCase()).join(''))||'?';
  const active=()=>data.profiles.find(p=>p.id===data.active)||data.profiles[0]||{name:'Profil'};

  function renderMenus(){
    const current=active();
    document.querySelectorAll('[data-profile-avatar]').forEach(el=>{ el.textContent=initials(current.name); });
    document.querySelectorAll('[data-profile-name]').forEach(el=>{ el.textContent=current.name; });
    const trigger=q('.profile-trigger');
    if(trigger) trigger.setAttribute('aria-label',`Profil aktif: ${current.name}. Ganti profil`);
    const others=data.profiles.length>1;
    const html=`
      <p class="profile-menu-title">Profil</p>
      ${data.profiles.map(p=>`
        <button type="button" role="menuitem" class="profile-item${p.id===data.active?' is-active':''}" data-switch-profile="${h(p.id)}" ${p.id===data.active?'aria-current="true"':''}>
          <span class="profile-avatar xs" aria-hidden="true">${h(initials(p.name))}</span>
          <span class="profile-item-text"><b>${h(p.name)}</b></span>
          ${p.id===data.active?'<span class="material-symbols-outlined profile-check" aria-hidden="true">check</span>':''}
        </button>`).join('')}
      ${others?'':'<p class="profile-menu-hint">Belum ada profil lain.</p>'}
      <div class="profile-menu-sep" role="separator"></div>
      <button type="button" role="menuitem" data-add-profile><span class="material-symbols-outlined text-[18px]" aria-hidden="true">person_add</span><span>Tambah profil</span></button>
      <button type="button" role="menuitem" data-edit-profile><span class="material-symbols-outlined text-[18px]" aria-hidden="true">edit</span><span>Edit profil ini</span></button>`;
    document.querySelectorAll('[data-profile-menu]').forEach(el=>{ el.innerHTML=html; });
  }

  async function refresh(){
    try{ data=await api('/api/profiles'); renderMenus(); }
    catch(err){ console.warn('Profil tidak dapat dimuat',err); }
  }

  /* ---------- add / edit dialog ---------- */
  const preview=()=>{
    q('#profile-avatar').textContent=initials(form.name.value);
    q('#profile-display-name').textContent=form.name.value.trim()||'Profil baru';
  };
  function openDialog(profile){
    form.reset();
    form.profile_id.value=profile?.id||'';
    form.name.value=profile?.name||'';
    q('#delete-profile').hidden=!profile||profile.id==='default';
    q('#profile-eyebrow').textContent=profile?'EDIT PROFIL':'PROFIL BARU';
    q('#profile-title').textContent=profile?'Edit profil':'Tambah profil';
    q('#profile-subtitle').textContent=profile?'':'Profil baru punya data sendiri: akun, transaksi, budget, dan target terpisah dari profil lain.';
    q('#profile-storage').textContent=profile?'Profil aktif':'Akan dibuka setelah disimpan';
    preview();
    dialog.showModal();
    form.name.focus();
  }
  form.addEventListener('input',preview);
  q('#close-profile').onclick=q('#cancel-profile').onclick=()=>dialog.close();
  form.onsubmit=async e=>{
    e.preventDefault();
    const button=form.querySelector('button[type=submit]');
    if(button.getAttribute('aria-busy')==='true')return;
    const id=form.profile_id.value, body=JSON.stringify({name:form.name.value});
    setBusy(button,true);
    try{
      if(id){
        data=await api('/api/profiles/'+encodeURIComponent(id),{method:'PUT',body});
        renderMenus();
        dialog.close();
        toast('Profil diperbarui');
      }else{
        await api('/api/profiles',{method:'POST',body});
        // The new profile is now active: reload so every view shows its (empty) data.
        location.reload();
      }
    }catch(err){toast(err.message)}
    finally{setBusy(button,false)}
  };

  /* ---------- delete ---------- */
  const LABELS={transactions:'transaksi',accounts:'akun',budgets:'budget',wishes:'wish'};
  q('#delete-profile').onclick=async()=>{
    const button=q('#delete-profile'), id=form.profile_id.value;
    const profile=data.profiles.find(p=>p.id===id);
    if(!profile||id==='default'||button.getAttribute('aria-busy')==='true')return;
    let detail='';
    try{
      const {counts}=await api('/api/profiles/'+encodeURIComponent(id)+'/summary');
      const parts=Object.entries(LABELS).filter(([k])=>counts[k]).map(([k,label])=>`${counts[k]} ${label}`);
      detail=parts.length?` Data yang ikut terhapus: ${parts.join(', ')}.`:' Profil ini belum punya transaksi, budget, atau wish.';
    }catch(err){ toast(err.message); return; }
    dialog.close();
    const ok=await askConfirm({eyebrow:'HAPUS PROFIL',title:`Hapus profil "${profile.name}"?`,
      message:`Semua data profil ini dihapus permanen dan tidak bisa dikembalikan.${detail}`,confirmLabel:'Hapus profil',danger:true});
    if(!ok){ dialog.showModal(); return; }
    setBusy(button,true);
    try{
      await api('/api/profiles/'+encodeURIComponent(id),{method:'DELETE'});
      // Deleting the active profile opens Profil utama; reload either way so the menus are fresh.
      location.reload();
    }catch(err){toast(err.message); setBusy(button,false)}
  };

  /* ---------- menu actions ---------- */
  document.addEventListener('click',async e=>{
    const sw=e.target.closest('[data-switch-profile]');
    if(sw){
      if(sw.dataset.switchProfile===data.active)return;
      try{
        await api('/api/profiles/'+encodeURIComponent(sw.dataset.switchProfile)+'/switch',{method:'POST',body:'{}'});
        location.reload(); // every view, cache and form starts fresh for the other profile
      }catch(err){toast(err.message)}
      return;
    }
    if(e.target.closest('[data-add-profile]')){ openDialog(null); return; }
    if(e.target.closest('[data-edit-profile]')){ openDialog(active()); }
  });

  // Bootstrap says which profile is shown; keep the trigger right even before the list loads.
  window.addEventListener('dashboard:loaded',()=>{
    if(state.profile && !data.profiles.some(p=>p.id===state.profile.id)) refresh();
    else if(state.profile){ data.active=state.profile.id; renderMenus(); }
  });
  refresh();

  /* ---------- storage-mode notice ---------- */
  window.addEventListener('dashboard:loaded',()=>{
    const f=state.features||{}, chip=q('#storage-chip'), warning=q('#storage-warning');
    const local=f.storage!=='firebase';
    chip.hidden=!local;
    chip.textContent='Mode lokal';
    chip.title='Data disimpan di perangkat ini. Isi FIREBASE_SERVICE_ACCOUNT_BASE64 di file .env agar data tersimpan di Firebase.';
    warning.hidden=!(local&&f.vercel);
    warning.innerHTML=warning.hidden?'':'<b>Data belum aman.</b> Aplikasi berjalan di Vercel tanpa Firebase, sehingga data lokal bisa hilang kapan saja. Isi FIREBASE_SERVICE_ACCOUNT_BASE64 di Environment Variables Vercel.';
  });
})();
