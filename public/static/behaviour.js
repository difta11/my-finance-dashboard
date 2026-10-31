(()=>{
  const money=cents=>new Intl.NumberFormat('id-ID',{style:'currency',currency:'IDR',maximumFractionDigits:0}).format((Number(cents)||0)/100);
  const renderCalendar=months=>{
    const calendar=document.querySelector('#spending-calendar');
    if(!months?.length){calendar.innerHTML='<p class="empty">Belum ada data kalender.</p>';return}
    const cells=months.flatMap(month=>month.days||[]),positive=cells.map(cell=>Number(cell.expense_cents)||0).filter(value=>value>0),max=Math.max(...positive,0);
    const monthGroups=months.map(month=>{
      const [year,monthNumber]=month.key.split('-').map(Number);
      const monthDate=new Date(Date.UTC(year,monthNumber-1,1));
      const label=new Intl.DateTimeFormat('id-ID',{month:'short'}).format(monthDate);
      const firstWeekday=(monthDate.getUTCDay()+6)%7;
      const weekCount=Math.ceil((firstWeekday+(month.days||[]).length)/7);
      const cells=(month.days||[]).map(cell=>{
        if(cell.expense_cents===null)return '';
        const amount=Number(cell.expense_cents)||0,level=amount>0&&max?Math.max(1,Math.ceil(amount/max*4)):0;
        const dayDate=new Date(cell.date+'T00:00:00Z'),weekday=(dayDate.getUTCDay()+6)%7,week=Math.floor((firstWeekday+cell.day-1)/7);
        const dateLabel=dayDate.toLocaleDateString('id-ID',{day:'numeric',month:'long',year:'numeric',timeZone:'UTC'});
        return `<span class="calendar-cell level-${level}" style="grid-column:${week+1};grid-row:${weekday+1}" title="${h(dateLabel)} - ${h(money(amount))}" aria-label="${h(dateLabel)}: ${h(money(amount))}"></span>`;
      }).join('');
      return `<div class="calendar-month-group"><div class="calendar-month-header" title="${h(monthDate.getUTCFullYear())}">${h(label)}</div><div class="calendar-month-days" style="grid-template-columns:repeat(${weekCount},9px)">${cells}</div></div>`;
    }).join('');
    calendar.innerHTML=`<div class="calendar-weekday-axis"><span></span><span>Sen</span><span></span><span>Rab</span><span></span><span>Jum</span><span></span><span></span></div><div class="calendar-month-groups">${monthGroups}</div>`;
  };
  const renderHours=(counts,busiest)=>{
    const chart=document.querySelector('#hour-chart'),values=Array.from({length:24},(_,hour)=>Number(counts?.[hour])||0),max=Math.max(...values,1);
    document.querySelector('#busiest-hour').textContent=busiest===null||busiest===undefined?'Belum ada transaksi pada tahun terpilih.':`Paling sering pada pukul ${String(busiest).padStart(2,'0')}.00 (${values[busiest]} transaksi)`;
    chart.innerHTML=values.map((count,hour)=>`<div class="hour-bar-item ${hour===busiest?'peak':''}" title="${String(hour).padStart(2,'0')}.00 - ${count} transaksi"><div class="hour-bar-track"><i style="height:${count?Math.max(4,count/max*100):0}%"></i></div><small>${String(hour).padStart(2,'0')}</small></div>`).join('');
  };
  const renderSpending=(spending,year)=>{
    const comparison=document.querySelector('#spending-comparison'),weekday=Number(spending.weekday_average_cents)||0,weekend=Number(spending.weekend_average_cents)||0,max=Math.max(weekday,weekend,1);
    const items=[{name:'Weekday (Senin-Jumat)',average:weekday,total:spending.weekday_total_cents},{name:'Weekend (Sabtu-Minggu)',average:weekend,total:spending.weekend_total_cents}];
    comparison.innerHTML=items.map(item=>`<div class="spending-compare-item"><div class="spending-compare-label"><span>${item.name}</span><b>${money(item.average)} / hari</b></div><div class="spending-compare-track"><i style="width:${Math.max(0,item.average/max*100)}%"></i></div><small>Total ${money(item.total)} selama periode</small></div>`).join('');
    document.querySelector('#daily-spending-average').textContent=money(spending.daily_average_cents);
    document.querySelector('#daily-spending-context').textContent=`Total ${money(spending.total_cents)} selama ${spending.period_days} hari pada ${year}.`;
  };
  const render=()=>{
    const summary=state.behavior;
    if(!summary)return;
    const yearSelect=document.querySelector('#behaviour-year'),years=summary.available_years||[summary.year];
    yearSelect.innerHTML=years.map(year=>`<option value="${year}">${year}</option>`).join('');
    yearSelect.value=String(summary.year);
    renderCalendar(summary.months||[]);
    renderHours(summary.hour_counts||[],summary.busiest_hour);
    renderSpending(summary.spending||{},summary.year);
  };
  window.addEventListener('dashboard:loaded',render);
  document.querySelector('#behaviour-year').onchange=()=>load();
  if(state.behavior)render();
})();
