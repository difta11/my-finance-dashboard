(()=>{
  const money=cents=>new Intl.NumberFormat('id-ID',{style:'currency',currency:'IDR',maximumFractionDigits:0}).format((Number(cents)||0)/100);
  const renderCalendar=months=>{
    const calendar=document.querySelector('#spending-calendar');
    if(!months?.length){calendar.innerHTML='<p class="empty">Belum ada data kalender.</p>';return}
    const cells=months.flatMap(month=>month.days||[]),positive=cells.map(cell=>Number(cell.expense_cents)||0).filter(value=>value>0),max=Math.max(...positive,0);
    const monthHeaders=months.map(month=>{
      const [year,monthNumber]=month.key.split('-').map(Number);
      const label=new Intl.DateTimeFormat('id-ID',{month:'short',year:'2-digit'}).format(new Date(Date.UTC(year,monthNumber-1,1)));
      return `<div class="calendar-month-header">${h(label)}</div>`;
    }).join('');
    let rows='';
    for(let dayNumber=1;dayNumber<=31;dayNumber++){
      rows+=`<div class="calendar-day-label">${dayNumber}</div>`;
      for(const month of months){
        const cell=(month.days||[]).find(item=>item.day===dayNumber);
        if(!cell||cell.expense_cents===null){rows+='<span class="calendar-cell level-empty" aria-hidden="true"></span>';continue}
        const amount=Number(cell.expense_cents)||0,level=amount>0&&max?Math.max(1,Math.ceil(amount/max*4)):0;
        const label=new Date(cell.date+'T00:00:00').toLocaleDateString('id-ID',{day:'numeric',month:'long',year:'numeric'});
        rows+=`<span class="calendar-cell level-${level}" title="${h(label)} - ${h(money(amount))}" aria-label="${h(label)}: ${h(money(amount))}"></span>`;
      }
    }
    calendar.innerHTML=`<div class="calendar-corner">Hari</div>${monthHeaders}${rows}`;
  };
  const renderHours=(counts,busiest)=>{
    const chart=document.querySelector('#hour-chart'),values=Array.from({length:24},(_,hour)=>Number(counts?.[hour])||0),max=Math.max(...values,1);
    document.querySelector('#busiest-hour').textContent=busiest===null||busiest===undefined?'Belum ada transaksi dalam 12 bulan terakhir.':`Paling sering pada pukul ${String(busiest).padStart(2,'0')}.00 (${values[busiest]} transaksi)`;
    chart.innerHTML=values.map((count,hour)=>`<div class="hour-bar-item ${hour===busiest?'peak':''}" title="${String(hour).padStart(2,'0')}.00 - ${count} transaksi"><div class="hour-bar-track"><i style="height:${count?Math.max(4,count/max*100):0}%"></i></div><small>${String(hour).padStart(2,'0')}</small></div>`).join('');
  };
  const renderSpending=spending=>{
    const comparison=document.querySelector('#spending-comparison'),weekday=Number(spending.weekday_average_cents)||0,weekend=Number(spending.weekend_average_cents)||0,max=Math.max(weekday,weekend,1);
    const items=[{name:'Weekday (Senin-Jumat)',average:weekday,total:spending.weekday_total_cents},{name:'Weekend (Sabtu-Minggu)',average:weekend,total:spending.weekend_total_cents}];
    comparison.innerHTML=items.map(item=>`<div class="spending-compare-item"><div class="spending-compare-label"><span>${item.name}</span><b>${money(item.average)} / hari</b></div><div class="spending-compare-track"><i style="width:${Math.max(0,item.average/max*100)}%"></i></div><small>Total ${money(item.total)} selama periode</small></div>`).join('');
    document.querySelector('#daily-spending-average').textContent=money(spending.daily_average_cents);
    document.querySelector('#daily-spending-context').textContent=`Total ${money(spending.total_cents)} selama ${spending.period_days} hari.`;
  };
  const render=()=>{
    const summary=state.behavior;
    if(!summary)return;
    renderCalendar(summary.months||[]);
    renderHours(summary.hour_counts||[],summary.busiest_hour);
    renderSpending(summary.spending||{});
  };
  window.addEventListener('dashboard:loaded',render);
  if(state.behavior)render();
})();
