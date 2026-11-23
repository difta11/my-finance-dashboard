// Debt tab: two checklists.
// * My Debt (money I owe): ticking opens a pop-up to choose the paying account; the payment
//   is recorded as an expense in the debt's category.
// * Other's Debt (money owed to me): recording it takes the amount out of the chosen account;
//   ticking it puts the amount back. Neither step counts as income or expense.
// A ticked debt shows a green "Lunas" box; clicking it again offers to undo.
(()=>{
  const money=cents=>new Intl.NumberFormat('id-ID',{style:'currency',currency:'IDR',maximumFractionDigits:0}).format((Number(cents)||0)/100);
  const dayLabel=iso=>iso?new Date(String(iso).slice(0,10)+'T00:00:00').toLocaleDateString('id-ID',{day:'numeric',month:'short',year:'numeric'}):'';
  const COPY={
    mine:{eyebrow:'MY DEBT',create:'Catat utang saya',edit:'Edit utang saya',who:'Utang ke siapa'},
    theirs:{eyebrow:"OTHER'S DEBT",create:'Catat uang yang dipinjam orang',edit:"Edit Other's Debt",who:'Siapa yang berutang'}
  };

  const section=document.querySelector('#debts');
  if(!section)return;
  const dialog=document.querySelector('#debt-dialog'),form=document.querySelector('#debt-form');
  const payDialog=document.querySelector('#debt-pay-dialog'),payForm=document.querySelector('#debt-pay-form');
  // Debts whose tick is being saved: their box is disabled until the reload finishes.
  const busy=new Set();

  const items=()=>Array.isArray(state.debts)?state.debts:[];
  const findDebt=id=>items().find(debt=>String(debt.id)===String(id));

  const ageText=debt=>{
    if(!debt.debt_on)return '';
    const days=Math.round((new Date(localDate()+'T00:00:00')-new Date(String(debt.debt_on).slice(0,10)+'T00:00:00'))/86400000);
    if(days<0)return '';
    return days===0?'hari ini':days+' hari lalu';
  };

  const meta=debt=>{
    const parts=[debt.note];
    if(debt.settled){
      parts.push('Lunas '+dayLabel(debt.settled_at));
      if(debt.account)parts.push(debt.direction==='mine'?'dibayar dari '+debt.account:'kembali ke '+debt.account);
    }else{
      parts.push(dayLabel(debt.debt_on));
      if(debt.direction==='mine'&&debt.category)parts.push(debt.category);
      if(debt.direction==='theirs'&&debt.account)parts.push('dari '+debt.account);
      parts.push(ageText(debt));
    }
    return parts.filter(Boolean).map(h).join(' · ');
  };

  const checkBox=debt=>{
    const id=h(debt.id),what=h(`${debt.name}, ${money(debt.amount_cents)}`);
    const disabled=busy.has(String(debt.id))?'disabled aria-busy="true"':'';
    return debt.settled
      ?`<button type="button" class="debt-check is-paid" role="checkbox" aria-checked="true" data-debt-toggle="${id}" ${disabled} aria-label="Lunas: ${what}. Klik untuk membatalkan." title="Batalkan lunas">Lunas</button>`
      :`<button type="button" class="debt-check" role="checkbox" aria-checked="false" data-debt-toggle="${id}" ${disabled} aria-label="Tandai lunas: ${what}" title="Tandai lunas"></button>`;
  };

  const row=debt=>{
    const id=h(debt.id);
    const menu=debt.settled
      ?[{label:'Batalkan lunas',icon:'undo',attrs:`data-debt-action="unsettle" data-debt-id="${id}"`}]
      :[{label:'Edit',icon:'edit',attrs:`data-debt-action="edit" data-debt-id="${id}"`}];
    menu.push({label:'Hapus',icon:'delete',danger:true,attrs:`data-debt-action="delete" data-debt-id="${id}"`});
    return `
      <li class="debt-item${debt.settled?' is-paid':''}">
        ${checkBox(debt)}
        <div class="debt-main"><b>${h(debt.name)}</b><small>${meta(debt)}</small></div>
        <b class="debt-amount">${money(debt.amount_cents)}</b>
        ${actionMenu(menu,'Opsi '+debt.name)}
      </li>`;
  };

  const render=()=>{
    if(!Array.isArray(state.debts))return;
    for(const direction of ['mine','theirs']){
      const list=items().filter(debt=>debt.direction===direction);  // server order: unpaid first
      const unpaid=list.filter(debt=>!debt.settled).reduce((total,debt)=>total+(Number(debt.amount_cents)||0),0);
      document.querySelector(`#debt-${direction}-list`).innerHTML=list.map(row).join('');
      document.querySelector(`#debt-${direction}-total`).textContent=money(unpaid);
    }
  };

  const fillAccounts=(select,selected)=>{
    const accounts=state.accounts||[];
    select.innerHTML='<option value="">Pilih akun</option>'+accounts.map(a=>`<option value="${h(a.id)}">${h(a.name)} · ${money(a.balance_cents)}</option>`).join('');
    if(selected&&accounts.some(a=>String(a.id)===String(selected)))select.value=String(selected);
  };

  const fillCategories=(select,selected)=>{
    const categories=(state.categories||[]).filter(c=>c.kind==='expense');
    select.innerHTML='<option value="">Pilih kategori</option>'+categories.map(c=>`<option value="${h(c.id)}">${h(c.name)}</option>`).join('');
    if(selected&&categories.some(c=>String(c.id)===String(selected)))select.value=String(selected);
  };

  /* ---------- Add / edit pop-up ---------- */
  const openForm=(direction,debt)=>{
    const copy=COPY[direction];
    form.reset();
    form.elements.direction.value=direction;
    form.elements.debt_id.value=debt?debt.id:'';
    document.querySelector('#debt-form-eyebrow').textContent=copy.eyebrow;
    document.querySelector('#debt-form-title').textContent=debt?copy.edit:copy.create;
    document.querySelector('#debt-name-label').textContent=copy.who;
    form.querySelectorAll('[data-debt-field]').forEach(el=>el.classList.toggle('hidden',el.dataset.debtField!==direction));
    fillCategories(form.elements.category_id,debt?.category_id);
    fillAccounts(form.elements.account_id,debt?.account_id);
    form.elements.debt_on.max=localDate();
    form.elements.debt_on.value=debt?String(debt.debt_on||'').slice(0,10):localDate();
    if(debt){
      form.elements.name.value=debt.name||'';
      form.elements.amount.value=String(Math.round((Number(debt.amount_cents)||0)/100));
      formatMoneyInput(form.elements.amount);
      form.elements.note.value=debt.note||'';
    }
    dialog.showModal();
    form.elements.name.focus();
  };

  document.querySelector('#close-debt-form').onclick=document.querySelector('#cancel-debt-form').onclick=()=>dialog.close();

  form.onsubmit=async event=>{
    event.preventDefault();
    const button=form.querySelector('button[type=submit]');
    if(button.getAttribute('aria-busy')==='true')return;
    const direction=form.elements.direction.value,id=form.elements.debt_id.value;
    const data={
      direction,
      name:form.elements.name.value.trim(),
      amount:digitsOnly(form.elements.amount.value),
      note:form.elements.note.value.trim(),
      debt_on:form.elements.debt_on.value||localDate()
    };
    if(direction==='mine')data.category_id=form.elements.category_id.value;
    else data.account_id=form.elements.account_id.value;
    const missing=!data.name?[form.elements.name,COPY[direction].who+' wajib diisi']
      :!Number(data.amount)?[form.elements.amount,'Isi nominalnya']
      :direction==='mine'&&!data.category_id?[form.elements.category_id,'Pilih kategori pengeluaran']
      :direction==='theirs'&&!data.account_id?[form.elements.account_id,'Pilih akun sumber uangnya']:null;
    if(missing){missing[0].focus();toast(missing[1]);return}
    setBusy(button,true);
    try{
      await api(id?'/api/debts/'+id:'/api/debts',{method:id?'PUT':'POST',body:JSON.stringify(data)});
      dialog.close();
      await load();
      if(id)toast('Debt diperbarui');
      else if(direction==='mine')toast('My Debt dicatat');
      else{
        const account=(state.accounts||[]).find(a=>String(a.id)===String(data.account_id));
        toast(`Dicatat. Saldo ${account?account.name:'akun'} berkurang ${money(Number(data.amount)*100)}`);
      }
    }catch(error){toast(error.message)}
    finally{setBusy(button,false)}
  };

  /* ---------- Pay pop-up (ticking a My Debt) ---------- */
  const openPay=debt=>{
    payForm.reset();
    payForm.elements.debt_id.value=debt.id;
    document.querySelector('#debt-pay-title').textContent='Bayar utang ke '+debt.name;
    document.querySelector('#debt-pay-summary').innerHTML=`
      <div><small>Nominal</small><b>${money(debt.amount_cents)}</b></div>
      <div><small>Kategori pengeluaran</small><b>${h(debt.category||'-')}</b></div>`;
    fillAccounts(payForm.elements.account_id);
    payDialog.showModal();
    payForm.elements.account_id.focus();
  };

  document.querySelector('#close-debt-pay').onclick=document.querySelector('#cancel-debt-pay').onclick=()=>payDialog.close();

  payForm.onsubmit=async event=>{
    event.preventDefault();
    const button=payForm.querySelector('button[type=submit]');
    if(button.getAttribute('aria-busy')==='true')return;
    const debt=findDebt(payForm.elements.debt_id.value),accountId=payForm.elements.account_id.value;
    if(!debt)return payDialog.close();
    if(!accountId){payForm.elements.account_id.focus();toast('Pilih akun untuk membayar');return}
    const account=(state.accounts||[]).find(a=>String(a.id)===String(accountId));
    setBusy(button,true);
    busy.add(String(debt.id));
    try{
      await api('/api/debts/'+debt.id+'/settle',{method:'POST',body:JSON.stringify({account_id:accountId})});
      payDialog.close();
      await load();
      toast(`Lunas. Pengeluaran ${money(debt.amount_cents)} dicatat dari ${account?account.name:'akun'}`);
    }catch(error){toast(error.message)}
    finally{
      setBusy(button,false);
      busy.delete(String(debt.id));
      render();
    }
  };

  /* ---------- Tick, undo, edit, delete ---------- */
  const run=async(debt,path,options,message)=>{
    busy.add(String(debt.id));
    render();
    try{
      await api('/api/debts/'+debt.id+path,options);
      await load();
      toast(message);
    }catch(error){toast(error.message)}
    finally{
      busy.delete(String(debt.id));
      render();
    }
  };

  const unsettle=async debt=>{
    const ok=await askConfirm({
      eyebrow:'BATALKAN LUNAS',
      title:`Tandai "${debt.name}" belum lunas?`,
      message:debt.direction==='mine'
        ?`Transaksi pengeluaran ${money(debt.amount_cents)}${debt.account?' dari '+debt.account:''} akan dihapus dan saldonya kembali.`
        :`Saldo ${debt.account||'akun'} akan berkurang lagi ${money(debt.amount_cents)} sampai ditandai lunas.`,
      confirmLabel:'Batalkan lunas'
    });
    if(ok)await run(debt,'/unsettle',{method:'POST'},'Status lunas dibatalkan');
  };

  const remove=async debt=>{
    const message=debt.direction==='mine'
      ?(debt.settled?'Catatan dihapus. Transaksi pembayarannya tetap ada di Transaksi.':'Catatan utang ini akan dihapus.')
      :(debt.settled?'Catatan dihapus. Saldo akun tidak berubah.':`Catatan dihapus dan ${money(debt.amount_cents)} dikembalikan ke saldo ${debt.account||'akun'}, seolah tidak pernah dipinjamkan.`);
    const ok=await askConfirm({eyebrow:'HAPUS DEBT',title:`Hapus "${debt.name}"?`,message,confirmLabel:'Hapus',danger:true});
    if(ok)await run(debt,'',{method:'DELETE'},'Debt dihapus');
  };

  document.addEventListener('click',async event=>{
    const add=event.target.closest('[data-add-debt]');
    if(add){openForm(add.dataset.addDebt,null);return}

    const box=event.target.closest('[data-debt-toggle]');
    if(box){
      const debt=findDebt(box.dataset.debtToggle);
      if(!debt||busy.has(String(debt.id)))return;
      if(debt.settled)return unsettle(debt);
      if(debt.direction==='mine')return openPay(debt);
      return run(debt,'/settle',{method:'POST',body:'{}'},`Lunas. ${money(debt.amount_cents)} kembali ke ${debt.account||'akun'}`);
    }

    const action=event.target.closest('[data-debt-action]');
    if(!action)return;
    const debt=findDebt(action.dataset.debtId);
    if(!debt)return;
    const type=action.dataset.debtAction;
    if(type==='edit')openForm(debt.direction,debt);
    else if(type==='unsettle')unsettle(debt);
    else if(type==='delete')remove(debt);
  });

  window.addEventListener('dashboard:loaded',render);
  render();
})();
