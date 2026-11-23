/* Smart Entry: an AI chat inside Catat Transaksi that turns a sentence or a receipt photo
   into a draft. The draft can be saved straight away ("Catat") or opened in the manual form
   ("Edit"). A receipt photo used here is attached to the saved transaction (stored in
   Google Drive when Drive is set up in .env and connected). */
(()=>{
  const q=s=>document.querySelector(s);
  const maxUploadMb=Number(document.body.dataset.maxUploadMb)||4;
  const form=q('#tx-form');
  const txReceipt=form.elements.receipt; // hidden: carries the Smart Entry photo into the save
  const money=n=>new Intl.NumberFormat('id-ID',{style:'currency',currency:'IDR',maximumFractionDigits:0}).format(Number(n)||0);
  const tooBig=file=>Boolean(file)&&file.size>maxUploadMb*1024*1024;
  const setFile=(input,file)=>{ const dt=new DataTransfer(); dt.items.add(file); input.files=dt.files; input.dispatchEvent(new Event('change',{bubbles:true})); };
  const features=()=>state.features||{};

  window.resetTxReceipt=()=>{ txReceipt.value=''; form.elements.receipt_file.value=''; };

  /* ---------- Receipt photos ---------- */
  // Any receipt photo (webcam frame or a phone camera shot) is redrawn as a JPEG of at most
  // 2000px, so a 12+ MP phone photo still fits the upload limit.
  const toJpeg=async(source,width,height)=>{
    const scale=Math.min(1,2000/Math.max(width,height)), canvas=document.createElement('canvas');
    canvas.width=Math.round(width*scale);
    canvas.height=Math.round(height*scale);
    canvas.getContext('2d').drawImage(source,0,0,canvas.width,canvas.height);
    const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/jpeg',0.88));
    return blob&&new File([blob],'struk-'+Date.now()+'.jpg',{type:'image/jpeg'});
  };
  const shrinkPhoto=async file=>{
    const url=URL.createObjectURL(file), img=new Image();
    try{
      img.src=url;
      await img.decode();
      return await toJpeg(img,img.naturalWidth,img.naturalHeight)||file;
    }catch{
      return file; // the browser can't decode it: send it as is (the size check still applies)
    }finally{
      URL.revokeObjectURL(url);
    }
  };

  /* ---------- Smart Entry chat ---------- */
  const txDialog=q('#tx-dialog');
  const manual=q('#tx-manual'), smart=q('#smart-entry'), toggle=q('#smart-entry-toggle'), messages=q('#smart-messages');
  const input=q('#smart-input'), smartFile=q('#smart-file'), sendButton=q('#smart-send');
  const attachment=q('#smart-attachment'), attachmentName=q('#smart-attachment-name');
  const KIND={expense:'Pengeluaran',income:'Pemasukan',transfer:'Transfer'};
  const EXAMPLES=['Makan siang 32rb pakai GoPay','Gaji masuk 8,5 juta ke Mandiri','Transfer 500rb dari BCA ke Jago'];
  const ENV_HINT='<p class="smart-env">Isi <code>GEMINI_API_KEY</code> (atau <code>OPENAI_API_KEY</code>) di file <code>.env</code>, lalu jalankan ulang aplikasi.</p>';
  let sending=false;

  window.setSmartEntry=on=>{
    manual.hidden=on;
    smart.hidden=!on;
    toggle.setAttribute('aria-pressed',String(on));
    toggle.classList.toggle('active',on);
    q('#smart-entry-sub').textContent=on?'Klik untuk kembali ke input manual':'Ketik atau foto struk, AI mengisi transaksi untuk Anda';
    if(on){
      if(!messages.children.length) welcome();
      input.focus();
    }else{
      stopCamera(); // leaving Smart Entry releases the webcam
    }
  };
  toggle.onclick=()=>window.setSmartEntry(smart.hidden);

  const scrollDown=()=>{ messages.scrollTop=messages.scrollHeight; };
  const bubble=(who,html)=>{
    const el=document.createElement('div');
    el.className='smart-msg '+who;
    el.innerHTML=html;
    messages.append(el);
    scrollDown();
    return el;
  };
  function welcome(){
    if(!features().ai){
      // AI is optional: explain what is missing instead of failing on the first message.
      bubble('ai warn',`<p><b>AI belum diatur.</b> Smart Entry membutuhkan API key Gemini atau OpenAI. Sementara itu, catat transaksi lewat input manual.</p>${ENV_HINT}`);
      return;
    }
    bubble('ai',`<p>Halo! Ceritakan transaksinya dengan bahasa sehari-hari, atau lampirkan foto struk. Saya siapkan draft yang bisa langsung dicatat atau diedit dulu.</p>
      <div class="smart-chips">${EXAMPLES.map(e=>`<button type="button" data-smart-example="${h(e)}">${h(e)}</button>`).join('')}</div>`);
  }
  messages.addEventListener('click',e=>{
    const ex=e.target.closest('[data-smart-example]');
    if(ex){ input.value=ex.dataset.smartExample; autoGrow(); input.focus(); }
  });

  const showAttachment=()=>{
    const file=smartFile.files[0];
    attachment.hidden=!file;
    // Drive is optional too: the photo can still be read by AI, it just won't be stored.
    const f=features();
    attachmentName.innerHTML=!file?'':f.drive_connected?h(file.name)
      :f.drive_configured?`${h(file.name)} · tidak disimpan karena Google Drive belum terhubung. <a href="/auth/google-drive/connect">Hubungkan Google Drive</a>`
      :`${h(file.name)} · hanya dibaca AI, tidak disimpan (Google Drive belum diatur)`;
  };
  smartFile.addEventListener('change',()=>{
    if(tooBig(smartFile.files[0])){ toast(`Ukuran foto maksimal ${maxUploadMb} MB`); smartFile.value=''; }
    showAttachment();
  });
  q('#smart-attachment-clear').onclick=()=>{ smartFile.value=''; showAttachment(); };

  /* ---------- Camera: opens straight away, no pop-up ---------- */
  // Phones and tablets: the phone's own camera app (file input with capture). Desktops have no
  // camera app a page can open, so the webcam shows right inside the Smart Entry panel.
  const nativeCamera=matchMedia('(pointer: coarse)').matches;
  const cameraButton=q('#smart-camera'), cameraFile=q('#smart-camera-file');
  const cameraView=q('#smart-camera-view'), cameraVideo=q('#smart-camera-video'), shutter=q('#smart-camera-shutter');
  let cameraStream=null, cameraStarting=false;

  cameraFile.addEventListener('change',async()=>{
    const file=cameraFile.files[0];
    cameraFile.value=''; // the same button can take the next photo
    if(file) setFile(smartFile,await shrinkPhoto(file));
  });

  function stopCamera(){
    cameraStream?.getTracks().forEach(track=>track.stop());
    cameraStream=null;
    cameraVideo.srcObject=null;
    cameraView.hidden=true;
  }
  async function openCamera(){
    if(nativeCamera){ cameraFile.click(); return; }
    if(!navigator.mediaDevices?.getUserMedia){ smartFile.click(); return; } // e.g. plain-HTTP LAN: use the file picker
    if(cameraStream||cameraStarting) return;
    cameraStarting=true;
    try{
      const stream=await navigator.mediaDevices.getUserMedia({video:{facingMode:{ideal:'environment'}},audio:false});
      // Closed, or switched to the manual form, while the browser was asking for permission.
      if(!txDialog.open||smart.hidden){ stream.getTracks().forEach(track=>track.stop()); return; }
      cameraStream=stream;
      cameraVideo.srcObject=stream;
      cameraView.hidden=false;
      cameraVideo.play().catch(()=>{});
      shutter.focus(); // Enter or Space takes the photo
    }catch{
      toast('Kamera tidak dapat dibuka. Izinkan akses kamera atau pilih foto dari perangkat.');
    }finally{
      cameraStarting=false;
    }
  }
  cameraButton.onclick=openCamera;
  q('#smart-camera-close').onclick=()=>{ stopCamera(); cameraButton.focus(); };
  shutter.onclick=async()=>{
    if(!cameraVideo.videoWidth){ toast('Kamera belum siap. Coba lagi sebentar.'); return; }
    const file=await toJpeg(cameraVideo,cameraVideo.videoWidth,cameraVideo.videoHeight);
    if(!file){ toast('Foto gagal dibuat. Coba lagi.'); return; }
    stopCamera();
    setFile(smartFile,file);
    input.focus();
  };
  // Esc while the webcam is on closes only the webcam, not the whole Catat Transaksi pop-up.
  txDialog.addEventListener('cancel',e=>{
    if(!cameraStream) return;
    e.preventDefault();
    stopCamera();
    cameraButton.focus();
  });

  const autoGrow=()=>{ input.style.height='auto'; input.style.height=Math.min(input.scrollHeight,140)+'px'; };
  input.addEventListener('input',autoGrow);
  input.addEventListener('keydown',e=>{
    if(e.key==='Enter'&&!e.shiftKey){ e.preventDefault(); send(); } // Shift+Enter = new line
  });
  sendButton.onclick=()=>send();

  // /api/parse may answer with non-JSON (e.g. 413 from a proxy); turn that into a readable message.
  const readJson=async response=>{
    const text=await response.text();
    try{ return JSON.parse(text); }
    catch{ return {error:response.status===413?`Gambar terlalu besar. Maksimal ${maxUploadMb} MB.`:`Respons server bukan JSON (HTTP ${response.status}). Coba muat ulang halaman.`}; }
  };
  const parse=async fd=>{
    let r=await fetch('/api/parse',{method:'POST',headers:{'X-CSRF-Token':sessionStorage.csrf},body:fd}), out=await readJson(r);
    if(r.status===403&&out.csrf){
      sessionStorage.csrf=out.csrf;
      r=await fetch('/api/parse',{method:'POST',headers:{'X-CSRF-Token':out.csrf},body:fd});
      out=await readJson(r);
    }
    if(r.status===401){ location.href='/login'; throw Error('Silakan login'); }
    if(!r.ok||out.error||!out.draft){
      const err=Error(out.error||'AI tidak mengembalikan draft. Coba lagi.');
      err.needsSetup=out.needs_setup;
      throw err;
    }
    return out.draft;
  };

  const draftHtml=d=>{
    const rows=[
      ['Jenis',KIND[d.type]||'Pengeluaran'],
      ['Nominal',d.amount?money(d.amount):'Belum terbaca'],
      d.type!=='transfer'?['Kategori',d.category||'Perlu dipilih']:null,
      [d.type==='income'?'Akun tujuan':'Akun sumber',d.account||'Perlu dipilih'],
      d.type==='transfer'?['Akun tujuan',d.destination_account||'Perlu dipilih']:null,
      ['Deskripsi',d.description||d.merchant||'—'],
      ['Tanggal',d.occurred_at?new Date(d.occurred_at).toLocaleString('id-ID',{dateStyle:'medium',timeStyle:'short'}):'Sekarang'],
      d.payment_method?['Metode',d.payment_method]:null,
    ].filter(Boolean);
    return `<p>Ini draft transaksinya:</p>
      <dl class="smart-draft">${rows.map(([k,v])=>`<dt>${h(k)}</dt><dd>${h(v)}</dd>`).join('')}</dl>
      ${d.date_warning?`<p class="smart-warn">⚠️ ${h(d.date_warning)}</p>`:''}
      ${d.question?`<p class="smart-warn">${h(d.question)}</p>`:''}
      <div class="smart-actions">
        <button type="button" class="secondary compact" data-draft-action="edit"><span class="material-symbols-outlined text-[16px]" aria-hidden="true">edit</span><span>Edit</span></button>
        <button type="button" class="primary compact" data-draft-action="save"><span class="material-symbols-outlined text-[16px]" aria-hidden="true">check</span><span>Catat</span></button>
      </div>`;
  };

  async function send(){
    if(sending)return;
    const text=input.value.trim(), file=smartFile.files[0];
    if(!text&&!file){ input.focus(); return; }
    sending=true;
    sendButton.disabled=true;
    bubble('user',`${text?`<p>${h(text)}</p>`:''}${file?`<p class="smart-file">📷 ${h(file.name)}</p>`:''}`);
    input.value=''; autoGrow();
    smartFile.value=''; showAttachment();
    const typing=bubble('ai typing','<span class="dot"></span><span class="dot"></span><span class="dot"></span>');
    const fd=new FormData();
    if(text) fd.append('text',text);
    if(file) fd.append('receipt',file);
    try{
      const draft=await parse(fd);
      typing.remove();
      const reply=bubble('ai',draftHtml(draft));
      reply.querySelector('[data-draft-action="edit"]').onclick=()=>editDraft(draft,file,text);
      reply.querySelector('[data-draft-action="save"]').onclick=()=>saveDraft(draft,file,text);
    }catch(err){
      typing.remove();
      bubble('ai error',`<p>${h(err.message)}</p>${err.needsSetup==='ai'?ENV_HINT:''}`);
    }finally{
      sending=false;
      sendButton.disabled=false;
      input.focus();
    }
  }

  // Put the draft into the manual form fields (without leaving Smart Entry).
  function fillFromDraft(d,file,text){
    const k=['income','expense','transfer'].includes(d.type)?d.type:'expense';
    [...document.querySelectorAll('.type-tabs button')].find(b=>b.dataset.kind===k)?.click();
    form.amount.value=d.amount||'';
    formatMoneyInput(form.amount);
    form.description.value=d.description||d.merchant||'';
    form.payment_method.value=d.payment_method||'';
    form.occurred_at.value=localDateTime(d.occurred_at||'');
    form.original_input.value=text||(file?'Foto struk: '+file.name:'');
    const pick=(select,name)=>{
      const option=[...select.options].find(o=>o.text.trim().toLowerCase()===String(name||'').trim().toLowerCase());
      if(option){ select.value=option.value; return true; }
      return false;
    };
    const missing=[];
    if(!d.amount) missing.push('nominal');
    if(!pick(form.account_id,d.account)) missing.push(k==='income'?'akun tujuan':'akun sumber');
    if(k==='transfer'){
      if(!pick(form.destination_id,d.destination_account)||form.destination_id.value===form.account_id.value) missing.push('akun tujuan');
    }else if(!pick(form.category_id,d.category)){
      missing.push('kategori');
    }
    if(file&&k!=='transfer') setFile(txReceipt,file); else window.resetTxReceipt();
    return missing;
  }

  // "Edit": open the manual form with every field already filled in.
  function editDraft(d,file,text){
    fillFromDraft(d,file,text);
    window.setSmartEntry(false);
    form.amount.focus();
  }

  // "Catat": save straight away. If AI could not fill a required field, fall back to the form.
  function saveDraft(d,file,text){
    const missing=fillFromDraft(d,file,text);
    if(missing.length){
      window.setSmartEntry(false);
      toast(`Lengkapi dulu: ${missing.join(', ')}`);
      return;
    }
    form.requestSubmit(); // same path as the manual save: date check, no duplicates, receipt upload
  }

  // Each opening of the dialog starts with an empty conversation. openTxDialog calls this
  // directly, because the dialog's async "close" event can fire after a quick reopen.
  window.resetSmartEntry=()=>{
    stopCamera();
    messages.innerHTML='';
    input.value=''; autoGrow();
    smartFile.value=''; showAttachment();
  };
  txDialog.addEventListener('close',()=>{ if(!txDialog.open) window.resetSmartEntry(); });

  // Return from the Google Drive OAuth flow (started from the photo note above).
  const driveResult=new URLSearchParams(location.search).get('drive');
  if(driveResult){
    toast({
      connected:'Google Drive berhasil dihubungkan',
      denied:'Izin Google Drive tidak diberikan',
      state_error:'Koneksi Google Drive gagal. Coba hubungkan lagi.',
      connection_error:'Google Drive gagal dihubungkan. Periksa GOOGLE_DRIVE_CLIENT_ID, GOOGLE_DRIVE_CLIENT_SECRET, dan GOOGLE_DRIVE_REDIRECT_URI di file .env.',
      token_missing:'Google tidak memberikan refresh token. Coba hubungkan ulang Google Drive.',
      not_configured:'Google Drive belum diatur. Isi pengaturannya di file .env terlebih dahulu.'
    }[driveResult]||'Status koneksi Google Drive diperbarui');
    history.replaceState({},'',location.pathname);
  }
})();
