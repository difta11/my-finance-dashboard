(()=>{
  const money=cents=>new Intl.NumberFormat('id-ID',{style:'currency',currency:'IDR',maximumFractionDigits:0}).format((Number(cents)||0)/100);
  const shortDate=iso=>new Date(iso+'T00:00:00').toLocaleDateString('id-ID',{day:'numeric',month:'short',year:'numeric'});
  const DAY_LABELS=['Sen','Sel','Rab','Kam','Jum','Sab','Min'];
  const tooltip=document.querySelector('#calendar-tooltip');
  let hourMode='count';

  /* ---------- Spending calendar ---------- */
  const renderCalendar=months=>{
    const calendar=document.querySelector('#spending-calendar');
    if(!months?.length){calendar.innerHTML='<p class="empty">Belum ada data kalender.</p>';return}
    const amounts=months.flatMap(month=>month.days||[]).map(cell=>Number(cell.expense_cents)||0).filter(value=>value>0),max=Math.max(...amounts,0);
    const monthGroups=months.map(month=>{
      const [year,monthNumber]=month.key.split('-').map(Number);
      const label=new Intl.DateTimeFormat('id-ID',{month:'short'}).format(new Date(year,monthNumber-1,1));
      const cells=(month.days||[]).map(cell=>{
        const future=cell.expense_cents===null,amount=future?0:(Number(cell.expense_cents)||0),level=amount>0&&max?Math.max(1,Math.ceil(amount/max*4)):0;
        const dayState=future?'future':!cell.tracked?'untracked':'tracked';
        const cellClass=future?'level-empty':!cell.tracked&&!amount?'level-untracked':`level-${level}`;
        const description=future?'belum terjadi':`${money(amount)}, ${Number(cell.expense_count)||0} transaksi`;
        // Rows come from the server's weekday (Mon=0), columns from the week-of-month index.
        return `<span class="calendar-cell ${cellClass}" style="grid-row:${cell.weekday+1};grid-column:${cell.week+1}" data-date="${cell.date}" data-amount="${amount}" data-count="${Number(cell.expense_count)||0}" data-state="${dayState}" aria-label="${h(shortDate(cell.date))}: ${h(description)}"></span>`;
      }).join('');
      return `<div class="calendar-month-group"><div class="calendar-month-header" title="${h(year)}">${h(label)}</div><div class="calendar-month-days">${cells}</div></div>`;
    }).join('');
    calendar.innerHTML=`<div class="calendar-weekday-axis" aria-hidden="true"><span></span>${DAY_LABELS.map(d=>`<span>${d}</span>`).join('')}</div><div class="calendar-month-groups">${monthGroups}</div>`;
  };

  const showTooltip=cell=>{
    const date=new Date(cell.dataset.date+'T00:00:00'),
          dayLabel=date.toLocaleDateString('id-ID',{weekday:'long',day:'numeric',month:'long',year:'numeric'}),
          count=Number(cell.dataset.count)||0,
          dayState=cell.dataset.state;
    let body;
    if(dayState==='future')body='<span class="muted">Belum terjadi</span>';
    else if(dayState==='untracked'&&!count)body='<span class="muted">Sebelum pencatatan dimulai</span>';
    else body=`<span>Pengeluaran <b>${money(cell.dataset.amount)}</b></span><span>${count} transaksi</span>`;
    tooltip.innerHTML=`<strong>${h(dayLabel)}</strong>${body}`;
    tooltip.hidden=false;
    const rect=cell.getBoundingClientRect(),tip=tooltip.getBoundingClientRect(),margin=8;
    let left=rect.left+rect.width/2-tip.width/2,top=rect.top-tip.height-margin;
    left=Math.max(margin,Math.min(left,window.innerWidth-tip.width-margin));
    if(top<margin)top=rect.bottom+margin;
    tooltip.style.left=left+'px';
    tooltip.style.top=top+'px';
  };
  const hideTooltip=()=>{tooltip.hidden=true};

  const calendarRoot=document.querySelector('#spending-calendar');
  calendarRoot.addEventListener('pointerover',e=>{
    const cell=e.target.closest('.calendar-cell');
    if(cell)showTooltip(cell);
  });
  calendarRoot.addEventListener('pointerout',e=>{
    if(e.target.closest('.calendar-cell')&&!e.relatedTarget?.closest?.('.calendar-cell'))hideTooltip();
  });
  // Touch devices: tap a day to show its details.
  calendarRoot.addEventListener('click',e=>{
    const cell=e.target.closest('.calendar-cell');
    if(cell)showTooltip(cell);
  });
  document.querySelector('.behaviour-calendar-scroll')?.addEventListener('scroll',hideTooltip,{passive:true});
  window.addEventListener('scroll',hideTooltip,{passive:true});
  document.addEventListener('pointerdown',e=>{if(!e.target.closest('.calendar-cell'))hideTooltip()});

  /* ---------- Hour distribution (expense only, by occurred_at) ---------- */
  const renderHours=summary=>{
    const chart=document.querySelector('#hour-chart'),
          isAmount=hourMode==='amount',
          source=isAmount?summary.hour_totals:summary.hour_counts,
          values=Array.from({length:24},(_,hour)=>Number(source?.[hour])||0),
          max=Math.max(...values,1),
          peak=isAmount?summary.busiest_amount_hour:summary.busiest_hour,
          hh=hour=>String(hour).padStart(2,'0');
    const caption=document.querySelector('#busiest-hour');
    if(peak===null||peak===undefined)caption.textContent=`Belum ada transaksi pengeluaran pada ${summary.year}.`;
    else caption.textContent=isAmount
      ?`Nominal terbesar pada pukul ${hh(peak)}.00 (${money(values[peak])})`
      :`Paling sering pada pukul ${hh(peak)}.00 (${values[peak]} transaksi)`;
    chart.innerHTML=values.map((value,hour)=>{
      const label=isAmount?money(value):`${value} transaksi`;
      return `<div class="hour-bar-item ${hour===peak?'peak':''}" title="${hh(hour)}.00–${hh(hour)}.59 · ${label}"><div class="hour-bar-track"><i style="height:${value?Math.max(4,value/max*100):0}%"></i></div><small class="${hour%3?'minor':''}">${hh(hour)}</small></div>`;
    }).join('');
    chart.setAttribute('aria-label',`Grafik ${isAmount?'total nominal':'jumlah transaksi'} pengeluaran per jam pada ${summary.year}`);
    chart.setAttribute('role','img');
    document.querySelectorAll('[data-hour-mode]').forEach(b=>{
      const selected=b.dataset.hourMode===hourMode;
      b.classList.toggle('selected',selected);
      b.setAttribute('aria-pressed',String(selected));
    });
  };

  /* ---------- Weekday vs weekend & daily average ---------- */
  const renderSpending=(summary)=>{
    const spending=summary.spending||{},year=summary.year;
    const comparison=document.querySelector('#spending-comparison'),weekday=Number(spending.weekday_average_cents)||0,weekend=Number(spending.weekend_average_cents)||0,max=Math.max(weekday,weekend,1);
    // Two bars told apart by colour (categorical slots 1 & 2); the legend names them and carries the totals.
    const items=[
      {key:'weekday',name:'Weekday',hint:'Senin–Jumat',average:weekday,total:spending.weekday_total_cents,days:spending.weekday_days},
      {key:'weekend',name:'Weekend',hint:'Sabtu–Minggu',average:weekend,total:spending.weekend_total_cents,days:spending.weekend_days}
    ];
    comparison.innerHTML=`
      <div class="spending-bars">
        ${items.map(item=>`<div class="spending-bar-row" title="${item.name} (${item.hint}): ${money(item.average)} / hari · total ${money(item.total)} selama ${Number(item.days)||0} hari">
          <div class="spending-compare-track"><i class="${item.key}" style="width:${Math.max(0,item.average/max*100)}%"></i></div>
          <b>${money(item.average)} / hari</b>
        </div>`).join('')}
      </div>
      <ul class="spending-legend">
        ${items.map(item=>`<li><i class="${item.key}"></i><b>${item.name}</b><span>${item.hint} · total ${money(item.total)} (${Number(item.days)||0} hari)</span></li>`).join('')}
      </ul>`;
    document.querySelector('#daily-spending-average').textContent=money(spending.daily_average_cents);
    document.querySelector('#daily-spending-context').textContent=summary.has_data
      ?`Total ${money(spending.total_cents)} selama ${spending.period_days} hari aktif (${shortDate(summary.period_start)} – ${shortDate(summary.period_end)}).`
      :`Belum ada transaksi pada ${year}.`;
  };

  const render=()=>{
    const summary=state.behavior;
    if(!summary)return;
    const yearSelect=document.querySelector('#behaviour-year'),years=summary.available_years||[summary.year];
    yearSelect.innerHTML=years.map(year=>`<option value="${year}">${year}</option>`).join('');
    yearSelect.value=String(summary.year);
    hideTooltip();
    renderCalendar(summary.months||[]);
    renderHours(summary);
    renderSpending(summary);
  };

  document.querySelectorAll('[data-hour-mode]').forEach(button=>button.addEventListener('click',()=>{
    hourMode=button.dataset.hourMode;
    if(state.behavior)renderHours(state.behavior);
  }));
  window.addEventListener('dashboard:loaded',render);
  document.querySelector('#behaviour-year').onchange=()=>load().catch(e=>toast(e.message));
  if(state.behavior)render();
})();
