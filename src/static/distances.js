'use strict';
(() => {
  const start = document.getElementById('start');
  const source = document.getElementById('source');
  const status = document.getElementById('distance-status');
  const chart = document.getElementById('distance-chart');
  if (!start || !source || !status || !chart) return;
  const farthest = document.getElementById('farthest-connection');
  const dashboard = document.getElementById('dashboard-data');
  const emptyDashboard = dashboard ? JSON.parse(dashboard.textContent) : null;
  const number = new Intl.NumberFormat();
  const sources = {both:'Combined sources',movies:'The Movies Dataset',tmdb:'TMDB 5000',demo:'Demo',local:'Local additions'};
  let sequence = 0, controller;

  function updateCards(data) {
    if (dashboard && data) dashboard.dispatchEvent(new CustomEvent('statistics-update', {detail:data}));
  }
  function render(data) {
    if (data.status !== 'complete') {
      status.textContent = 'The calculation reached its time limit. Connectivity is unknown; this does not mean the remaining actors are disconnected. Select the actor again to retry.';
      updateCards(emptyDashboard);
      return;
    }
    updateCards(data.dashboard);
    status.textContent = `${data.actor_name}: ${number.format(data.connected)} connected actors and ${number.format(data.disconnected)} not connected in ${sources[data.source]}.` +
      (data.cast_complete === false ? ' Imported cast coverage is incomplete; missing connections can affect these results.' : '');
    if (!data.connected) {
      const p = document.createElement('p');p.textContent = 'No other actors are reachable in this cast network.';chart.append(p);return;
    }
    const table = document.createElement('table');table.className = 'distance-table';
    const caption = document.createElement('caption');caption.textContent = `Shortest distances from ${data.actor_name} · % of reachable actors`;table.append(caption);
    const head = document.createElement('thead'), heading = document.createElement('tr');
    for (const label of ['Degrees','Reachable actors','Count · Share']) {const th=document.createElement('th');th.scope='col';th.textContent=label;heading.append(th);}
    head.append(heading);table.append(head);
    const body = document.createElement('tbody');
    const largest = Math.max(...data.distribution.map(bin => bin.actors));
    for (const bin of data.distribution) {
      const row = document.createElement('tr');
      const label = document.createElement('th');label.scope='row';label.textContent=`${bin.degrees} ${bin.degrees===1 ? 'degree' : 'degrees'}`;
      const plot = document.createElement('td'), bar = document.createElement('span');
      bar.className='distance-bar' + (bin.degrees>6 ? ' beyond-six' : '');
      bar.style.width=`${100*bin.actors/largest}%`;bar.setAttribute('aria-hidden','true');plot.append(bar);
      const count = document.createElement('td');count.textContent=`${number.format(bin.actors)} · ${100*bin.actors/data.connected < .05 ? '<0.1' : (100*bin.actors/data.connected).toFixed(1)}%`;
      row.append(label,plot,count);body.append(row);
    }
    table.append(body);chart.append(table);
    const route = data.farthest_path || [];
    if (farthest && route.length) {
      const heading=document.createElement('h3');heading.textContent=`Longest shortest connection: ${data.maximum} degrees · ${route[route.length-1].label}`;
      const explanation=document.createElement('p');
      explanation.className='hint';
      explanation.textContent=`${number.format(data.farthest_count)} actors are tied at this distance. Showing one deterministic shortest route; this is not the longest possible walk through the network.`;
      const list=document.createElement('ol');list.className='text-path';
      for (const item of route) {
        const li=document.createElement('li');
        const link=document.createElement(item.kind==='movie' && document.body?.dataset.movieDetails==='disabled' ? 'span' : 'a');
        if(item.kind!=='movie'||document.body?.dataset.movieDetails!=='disabled')link.href=item.kind==='movie' ? `/movie/${item.entity_id}` : '/six-degrees?'+new URLSearchParams({start:item.entity_id,source:data.source});
        link.textContent=item.label;li.append(link);list.append(li);
      }
      farthest.append(heading,explanation,list);
    }
  }
  async function load() {
    controller?.abort();const epoch=++sequence;chart.replaceChildren();farthest?.replaceChildren();updateCards(emptyDashboard);
    document.getElementById('distance-source').textContent=sources[source.value] || source.value;
    if (!start.value) {status.textContent='Select a From actor to see their reach across the catalog.';return;}
    controller=new AbortController();status.textContent='Calculating shortest distances across the selected cast network…';
    try {
      const response=await fetch('/api/actor-statistics?'+new URLSearchParams({start:start.value,source:source.value}), {signal:controller.signal});
      const data=await response.json();if (epoch!==sequence) return;
      if (!response.ok) {status.textContent=Object.values(data.errors || {}).join(' ') || 'Statistics unavailable. Please try again.';return;}
      render(data);
    } catch (error) {
      if (epoch===sequence && error.name!=='AbortError') status.textContent='Statistics unavailable. Select the actor again to retry.';
    }
  }
  start.addEventListener('change',load);source.addEventListener('change',load);
  load();
})();
