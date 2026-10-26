/* All nodes and edges come from read-only catalog APIs. */
(() => {
  if (typeof document === 'undefined' || !document.getElementById('knowledge-canvas')) return;
  const $=id=>document.getElementById(id), form=$('kg-search-form');
  const config=JSON.parse($('kg-config').textContent);
  const status=message=>{$('kg-status').textContent=message;};
  const color=()=>document.documentElement.dataset.theme==='light'?'#27344b':'#eef2fa';
  let selected=null, busy=false, epoch=0, searchSequence=0, active=new URLSearchParams(new FormData(form)), nextOffset=0;
  const cy=cytoscape({container:$('knowledge-canvas'),elements:[],layout:{name:'preset'},
    style:[{selector:'node',style:{label:'data(label)','background-color':'#6597d4',color:color(),'text-valign':'bottom','text-margin-y':7,'font-size':13,'text-wrap':'wrap','text-max-width':150}},
      {selector:'node[kind="movie"]',style:{shape:'diamond','background-color':'#e9b75f'}},
      {selector:'node[kind="genre"]',style:{shape:'hexagon','background-color':'#7cbb97'}},
      {selector:'edge',style:{label:'data(label)','curve-style':'bezier','target-arrow-shape':'triangle','line-color':'#8794ac','target-arrow-color':'#8794ac',color:color(),'font-size':11,'text-rotation':'autorotate'}},
      {selector:'edge[kind="genre"]',style:{'line-style':'dashed','line-color':'#7cbb97','target-arrow-color':'#7cbb97'}},
      {selector:':selected',style:{'border-width':3,'border-color':'#f5ba53','line-color':'#f5ba53','target-arrow-color':'#f5ba53'}}]});
  function resetSelection(){selected=null;$('kg-expand').disabled=true;$('kg-remove').disabled=true;$('kg-selected').textContent='Click a node or relationship to inspect its data.';}
  function inspect(item){
    selected=item;$('kg-selected').replaceChildren();
    const p=document.createElement('p'),data=item.data();
    p.textContent=item.isNode()?`${data.kind}: ${data.label} · ${data.id}`:`${item.source().data('label')} → ${data.label} → ${item.target().data('label')}`;
    $('kg-selected').append(p);
    if(data.kind==='movie'){
      for(const v of data.values||[]){const p=document.createElement('p');const money=n=>n>0?'$'+n.toLocaleString():'Unknown';p.textContent=`${config.sources[v.source]||v.source}: ${v.title} · Budget ${money(v.budget)} · Revenue ${money(v.revenue)} · Rating ${v.vote_average??'Unknown'}`;$('kg-selected').append(p);}
      if(document.body?.dataset.movieDetails!=='disabled'){const link=document.createElement('a');link.href='/movie/'+data.id.split(':')[1];link.textContent='Open movie details →';$('kg-selected').append(link);}
    }
    for(const record of data.details||[]){const p=document.createElement('p');p.textContent=(config.sources[record.source]||record.source)+(record.role?': '+record.role:': movie genre');$('kg-selected').append(p);}
    $('kg-expand').disabled=!item.isNode()||busy;$('kg-remove').disabled=busy;
  }
  function refreshList(){
    $('kg-list').replaceChildren();
    cy.elements().forEach(item=>{const b=document.createElement('button');b.type='button';b.className='kg-list-item';b.textContent=item.isNode()?`${item.data('kind')}: ${item.data('label')}`:`${item.source().data('label')} → ${item.data('label')} → ${item.target().data('label')}`;b.addEventListener('click',()=>{cy.elements().unselect();item.select();inspect(item);});$('kg-list').append(b);});
  }
  async function json(url,params){
    const response=await fetch(url+'?'+params);let data;
    try{data=await response.json();}catch{throw new Error('The server returned an unexpected response. Restart Flask and refresh the page.');}
    if(!response.ok)throw new Error(Object.values(data.errors||{error:'Request failed. Restart Flask and try again.'}).join(' '));return data;
  }
  const suggestionControls=[];
  function autocomplete(field,inputId,listId,hintId){
    const input=$(inputId),list=$(listId),hint=$(hintId);let timer,sequence=0;
    function update(){
      clearTimeout(timer);const current=++sequence;list.replaceChildren();hint.textContent='';
      if(input.value.trim().length<2)return;
      timer=setTimeout(async()=>{
        const params=new URLSearchParams(new FormData(form));params.set('field',field);
        try{const data=await json('/api/knowledge-graph/suggestions',params);if(current!==sequence)return;
          for(const item of data.suggestions){const option=document.createElement('option');option.value=item.value;option.label=item.kind;list.append(option);}
          hint.textContent=data.suggestions.length?'Choose a suggestion or keep typing your own terms.':'No suggestions. You can still search your own terms.';
        }catch(error){if(current===sequence)hint.textContent=error.message;}
      },250);
    }
    input.addEventListener('input',update);suggestionControls.push(update);
  }
  autocomplete('q','kg-query','kg-query-suggestions','kg-query-hint');
  autocomplete('role','kg-role','kg-role-suggestions','kg-role-hint');
  for(const id of ['kg-kind','kg-source','kg-genre','kg-edge','kg-min-budget','kg-max-budget','kg-min-revenue','kg-max-revenue']){
    $(id).addEventListener('change',()=>suggestionControls.forEach(update=>update()));
  }

  async function loadGraph(extra=[],expand=null,params=active){
    if(busy)return;
    busy=true;const current=epoch;
    const query=new URLSearchParams(params);query.set('catalog_version',config.version);
    const ids=new Set([...cy.nodes().map(n=>n.id()),...extra]);
    if(ids.size>300){busy=false;return status('Canvas limit: remove some nodes before adding more.');}
    ids.forEach(id=>query.append('node',id));if(expand)query.set('expand',expand);
    $('kg-expand').disabled=true;status(expand?'Expanding catalog connections…':'Loading catalog records…');
    try{
      const data=await json('/api/knowledge-graph/view',query);
      if(current!==epoch)return;
      const keep=new Set(data.nodes.map(n=>n.data.id));
      cy.nodes().filter(n=>!keep.has(n.id())).remove();cy.edges().remove();
      const anchor=expand&&cy.getElementById(expand), center=anchor&&anchor.nonempty()?anchor.position():{x:0,y:0};
      let added=0;
      for(const node of data.nodes){const old=cy.getElementById(node.data.id);if(old.nonempty()){old.data(node.data);continue;}const angle=added*2.4,radius=100+35*Math.sqrt(added);node.position={x:center.x+Math.cos(angle)*radius,y:center.y+Math.sin(angle)*radius};cy.add(node);added++;}
      cy.add(data.edges);if(ids.size===extra.length)cy.fit(undefined,45);
      refreshList();if(selected&&!selected.removed())inspect(selected);else resetSelection();
      status(`Added ${added} nodes. ${cy.nodes().length}/300 nodes · ${cy.edges().length} relationships. `+(data.has_more?(cy.nodes().length>=300?'Canvas limit reached. Remove nodes to explore more. ':'Double-click again for more neighbors. '):expand?'All matching neighbors are visible. ':'')+(data.truncated?'Relationship display capped at 1,000.':''));
    }catch(error){if(current===epoch)status(error.message);}finally{busy=false;if(selected&&!selected.removed())inspect(selected);}
  }
  async function search(append=false){
    const sequence=++searchSequence, query=new URLSearchParams(active);query.set('offset',append?nextOffset:0);
    if(!append){$('kg-results').replaceChildren();$('kg-more').hidden=true;}
    status('Searching the catalog…');
    try{const data=await json('/api/knowledge-graph/search',query);if(sequence!==searchSequence)return;
      if(!append)$('kg-results').replaceChildren();nextOffset=data.next_offset;$('kg-more').hidden=!data.has_more;
      if(!data.results.length&&!append)$('kg-results').textContent='No matching catalog records.';
      if(data.results.length){const all=document.createElement('button');all.type='button';all.className='btn btn-secondary';all.textContent='Add these '+data.results.length+' records';all.addEventListener('click',()=>loadGraph(data.results.map(r=>r.id)));$('kg-results').append(all);}
      for(const record of data.results){const b=document.createElement('button');b.type='button';b.className='kg-list-item';b.textContent='+ '+record.label+' · '+record.id;b.addEventListener('click',()=>loadGraph([record.id]));$('kg-results').append(b);}
      status(data.results.length+' matching records shown'+(data.has_more?' · More results available.':'.'));return true;
    }catch(error){if(sequence===searchSequence)status(error.message);return false;}
  }
  form.addEventListener('submit',async event=>{event.preventDefault();if(busy)return status('Wait for the current expansion before applying filters.');const next=new URLSearchParams(new FormData(form));if(next.get('source')!==active.get('source')){epoch++;cy.elements().remove();resetSelection();refreshList();}active=next;const found=await search();if(found&&cy.nodes().length)await loadGraph();});
  $('kg-more').addEventListener('click',()=>search(true));
  cy.on('select',event=>inspect(event.target));cy.on('unselect',resetSelection);
  cy.on('dbltap','node',event=>loadGraph([],event.target.id()));
  $('kg-expand').addEventListener('click',()=>{if(selected?.isNode())loadGraph([],selected.id());});
  $('kg-remove').addEventListener('click',()=>{if(selected&&!busy){selected.remove();resetSelection();refreshList();status('Removed from this canvas. The catalog is unchanged.');}});
  $('kg-clear').addEventListener('click',()=>{epoch++;cy.elements().remove();resetSelection();refreshList();status('Canvas cleared. Search the catalog to start again.');});
  $('kg-fit').addEventListener('click',()=>cy.fit(undefined,45));
  $('kg-layout').addEventListener('click',()=>cy.layout({name:'cose',animate:false,randomize:false}).run());
  $('kg-text-size').addEventListener('input',()=>{const size=Number($('kg-text-size').value);$('kg-text-value').textContent=size;cy.style().selector('node').style('font-size',size).selector('edge').style('font-size',Math.max(8,size-2)).update();});
  document.addEventListener('themechange',()=>cy.style().selector('node,edge').style('color',color()).update());
  $('kg-export').addEventListener('click',()=>{const payload={catalog_version:config.version,filters:Object.fromEntries(active),nodes:cy.nodes().map(n=>({data:n.data(),position:n.position()})),edges:cy.edges().map(e=>({data:e.data()}))};const url=URL.createObjectURL(new Blob([JSON.stringify(payload,null,2)],{type:'application/json'}));const link=document.createElement('a');link.href=url;link.download='catalog-knowledge-graph.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
  const handoff=new URLSearchParams(typeof location!=='undefined'?location.hash.slice(1):'');
  const seed=handoff.getAll('node');
  if(seed.length){
    if(handoff.get('catalog_version')&&handoff.get('catalog_version')!==config.version){status('The catalog changed since Six Degrees was opened. Run that search again before transferring the graph.');return;}
    const source=handoff.get('source')||'both';
    if(!['both',...Object.keys(config.sources)].includes(source)){status('The transferred graph has an invalid source.');return;}
    $('kg-source').value=source;active.set('source',source);
    loadGraph(seed).then(()=>{const focus=cy.getElementById(handoff.get('focus')||'');if(focus.nonempty()){focus.select();inspect(focus);}});
  }
})();
