'use strict';
(() => {
  const dataElement = document.getElementById('graph-data'); if (!dataElement) return;
  const slider = document.getElementById('depth'), form = document.getElementById('degrees-form');
  const status = document.getElementById('graph-status'), path = document.getElementById('text-path');
  const details = document.getElementById('graph-details');
  let cy, activeData, pinned = false, sequence = 0, controller, expansionController, timer;
  let expanding = false;
  const pages = new Map();
  const sourceNames = {movies:'The Movies Dataset',tmdb:'TMDB 5000',demo:'Demo',manual:'Manual entries'};

  function detail(data) {
    details.replaceChildren();
    const h = document.createElement('h2'); h.textContent = data.label || 'Cast connection'; details.append(h);
    const text = document.createElement('p');
    const value = data.details;
    if (data.kind === 'actor') text.textContent = `Actor ID ${value.actor_id} · ${value.movie_count} movies in this network`;
    else if (data.kind === 'movie') {
      text.textContent = `Movie ID ${value.movie_id}\n` + value.sources.map(record =>
        `${sourceNames[record.source] || record.source}: ${record.title}\nRating ${record.vote_average ?? 'unknown'} · ${record.vote_count ?? 'unknown'} votes\nBudget ${record.budget || 'unknown'} · Revenue ${record.revenue || 'unknown'}`).join('\n\n');
    } else text.textContent = value.map(role => `${sourceNames[role.source] || role.source}: ${role.role}`).join('\n');
    details.append(text);
    if (data.kind) {
      const progress = pages.get(data.id);
      const button = document.createElement('button');button.type = 'button';button.className = 'btn btn-secondary';
      button.textContent = progress && !progress.has_more ? 'All neighbors loaded' : `Show ${progress ? 'more' : 'up to 15'} ${data.kind === 'actor' ? 'movies' : 'cast members'}`;
      button.disabled = expanding || Boolean(progress && !progress.has_more);
      button.addEventListener('click',()=>expand(data.id));details.append(button);
      if (progress) {
        const hint = document.createElement('p');hint.className='hint';
        hint.textContent=`${progress.next_offset} of ${progress.total} neighbors checked. Already visible neighbors are not duplicated.`;
        details.append(hint);
      }
    }
  }

  async function expand(id) {
    if (!cy || expanding || !activeData) return;
    const progress=pages.get(id);
    if (progress && !progress.has_more) {status.textContent='All neighbors of this node are already loaded.';return;}
    const room=Math.min(15,300-cy.nodes().length,1000-cy.edges().length);
    if (room<=0) {status.textContent='Display limit reached. Choose Path only to start a smaller exploration.';return;}
    const epoch=sequence, graph=cy, anchor=cy.getElementById(id);
    if (anchor.empty()) return;
    expanding=true;pinned=true;expansionController=new AbortController();detail(anchor.data());
    status.textContent=`Loading neighbors of ${anchor.data('label')}…`;
    const params=new URLSearchParams({node:id,source:activeData.source,catalog_version:activeData.catalog_version,
      offset:progress?.next_offset || 0,limit:room});
    try {
      const response=await fetch('/api/expand-node?'+params,{signal:expansionController.signal});
      const data=await response.json();
      if (epoch!==sequence || graph!==cy) return;
      if (!response.ok) {status.textContent=Object.values(data.errors||{}).join(' ');return;}
      if (data.catalog_version!==activeData.catalog_version) {status.textContent='The catalog changed. Find the connection again.';return;}
      const origin=anchor.position(), added=[];let inserted=0;
      cy.batch(()=>{
        for (const node of data.nodes) {
          if (cy.getElementById(node.data.id).nonempty()) continue;
          const angle=2*Math.PI*inserted/Math.min(room,8),radius=120+Math.floor(inserted/8)*80;
          node.position={x:origin.x+Math.cos(angle)*radius,y:origin.y+Math.sin(angle)*radius};
          added.push(...cy.add(node));inserted++;
        }
        for (const edge of data.edges) if (cy.getElementById(edge.data.id).empty()) cy.add(edge);
      });
      pages.set(id,data);
      status.textContent=`Added ${inserted} nodes around ${anchor.data('label')}. ${data.has_more ? 'Double-click again for more.' : 'All neighbors checked.'} ${cy.nodes().length}/300 nodes shown.`;
      if (added.length) {
        cy.collection(added).addClass('just-added');
        setTimeout(()=>{if (!graph.destroyed()) graph.collection(added).removeClass('just-added');},1500);
      }
    } catch(error) {
      if (epoch===sequence && error.name!=='AbortError') status.textContent='Expansion failed. Double-click to try again.';
    } finally {
      if (epoch===sequence) {expanding=false;if (graph===cy && anchor.nonempty()) detail(anchor.data());}
    }
  }

  document.addEventListener?.('themechange', () => {
    if (cy && !cy.destroyed()) {
      cy.style().selector('node').style('color', document.documentElement.dataset.theme === 'light' ? '#243249' : '#edf1fa').update();
    }
  });

  function render(data) {
    if (!data) return;
    expansionController?.abort();expanding=false;pages.clear();activeData=data;
    const messages = {found:`Shortest path: ${data.degrees} degree${data.degrees === 1 ? '' : 's'}.`,same_actor:'The same actor is selected: zero degrees.',no_path:'No connection found within six degrees in the selected imported network.',interrupted:'Search interrupted by its time limit. This does not establish that no connection exists.'};
    status.textContent = (messages[data.status] || data.status) + (data.cast_complete === false ? ' This catalog was imported with incomplete cast coverage.' : '') + (data.truncated ? ' Neighborhood trimmed to the display limits; the complete shortest path is retained.' : ' Double-click a node to explore its neighbors.');
    path.replaceChildren();
    for (const item of data.path) {
      const li = document.createElement('li');
      if (item.kind === 'movie' && document.body?.dataset.movieDetails !== 'disabled') {const a=document.createElement('a');a.href=`/movie/${item.entity_id}`;a.textContent=item.label;li.append(a);}
      else li.textContent=item.label;
      path.append(li);
    }
    cy?.destroy();
    if (!window.cytoscape) {status.textContent+=' Graph library unavailable; the textual path remains usable.';return;}
    cy=cytoscape({container:document.getElementById('graph'),elements:[...data.nodes,...data.edges],
      style:[{selector:'node',style:{label:'','font-size':11,color:document.documentElement?.dataset.theme === 'light' ? '#243249' : '#edf1fa','text-wrap':'wrap','text-max-width':110,'background-color':'#76a4e7',width:30,height:30,'text-valign':'bottom','text-margin-y':7}},
        {selector:'node[kind="movie"]',style:{shape:'diamond','background-color':'#a887cf',width:35,height:35}},
        {selector:'edge',style:{width:1,'line-color':'#566581','curve-style':'haystack'}},
        {selector:'edge[?on_path]',style:{'line-color':'#efc367',width:4}},
        {selector:'node[?on_path]',style:{'background-color':'#efc367',width:36,height:36,'border-width':2,'border-color':'#fff0c4'}},
        {selector:'node[?on_path],node:selected,node.hovered',style:{label:'data(label)'}},
        {selector:'node.just-added',style:{'border-width':3,'border-color':'#83d6c7'}}],
      layout:{name:'cose',animate:false,randomize:false,nodeRepulsion:7000,idealEdgeLength:100,numIter:500},wheelSensitivity:.2});
    pinned=false;
    details.replaceChildren();const hint=document.createElement('p');hint.textContent='Hover for details. Click to pin; double-click a node to expand it.';details.append(hint);
    cy.on('mouseover','node,edge',event=>{event.target.addClass('hovered');if(!pinned)detail(event.target.data());});
    cy.on('mouseout','node,edge',event=>event.target.removeClass('hovered'));
    cy.on('tap','node,edge',event=>{pinned=true;detail(event.target.data());});
    cy.on('dbltap','node',event=>expand(event.target.id()));
    cy.on('tap',event=>{if(event.target===cy)pinned=false;});
    const saveSpec=document.querySelector('input[name=spec]');
    if(saveSpec){const spec=JSON.parse(saveSpec.value);spec.depth=Number(slider.value);spec.start=Number(form.elements.start.value);spec.end=Number(form.elements.end.value);spec.source=form.elements.source.value;saveSpec.value=JSON.stringify(spec);}
  }

  const builderLink=document.getElementById('graph-explore-builder');
  builderLink?.addEventListener('click',event=>{
    if(!cy||!activeData||!cy.nodes().length){event.preventDefault();status.textContent='Find a connection before opening the builder.';return;}
    const params=new URLSearchParams({source:activeData.source,catalog_version:activeData.catalog_version});
    cy.nodes().forEach(node=>params.append('node',node.id()));
    const selected=cy.nodes(':selected').first();
    if(selected.nonempty())params.set('focus',selected.id());
    builderLink.href='/knowledge-graph#'+params;
  });

  document.getElementById('graph-reset').addEventListener('click',()=>cy?.fit(undefined,30));
  document.getElementById('graph-path-only').addEventListener('click',()=>{
    if(!activeData)return;
    ++sequence;clearTimeout(timer);controller?.abort();expansionController?.abort();
    slider.value=0;document.getElementById('depth-value').value=0;
    const ids=new Set(activeData.path.map(item=>item.id));
    const base={...activeData,depth:0,truncated:false,nodes:activeData.nodes.filter(node=>ids.has(node.data.id)),edges:activeData.edges.filter(edge=>edge.data.on_path)};
    render(base);
    history.replaceState(null,'','/six-degrees?'+new URLSearchParams(new FormData(form)));
  });
  slider.addEventListener('input',()=>{
    document.getElementById('depth-value').value=slider.value;
    clearTimeout(timer);controller?.abort();expansionController?.abort();expanding=false;const seq=++sequence;
    timer=setTimeout(async()=>{
      const params=new URLSearchParams(new FormData(form));
      if(!params.get('start')||!params.get('end'))return;
      controller=new AbortController();status.textContent='Loading neighborhood…';
      try{
        const response=await fetch('/api/neighborhood?'+params,{signal:controller.signal});
        const data=await response.json();if(seq!==sequence)return;
        if(!response.ok){status.textContent=Object.values(data.errors||{}).join(' ');return;}
        history.replaceState(null,'','/six-degrees?'+params);render(data);
      }catch(error){if(seq===sequence && error.name!=='AbortError')status.textContent='Connection request failed. Please try again.';}
    },250);
  });
  render(JSON.parse(dataElement.textContent));
})();
