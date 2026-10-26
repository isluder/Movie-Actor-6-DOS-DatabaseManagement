/* A browser-local workspace, independent of catalog records. */
function validateKnowledgeGraph(value) {
  if (!value || !Array.isArray(value.nodes) || !Array.isArray(value.edges) || value.nodes.length > 200 || value.edges.length > 500) {
    throw new Error('Use a graph with nodes and edges arrays, at most 200 nodes and 500 relationships.');
  }
  const ids = new Set();
  const text = (v, max) => typeof v === 'string' && v.trim().length > 0 && v.length <= max;
  const nodes = value.nodes.map(n => {
    if (!n || !text(n.id, 100) || ids.has(n.id) || !text(n.label, 100) || !text(n.kind, 50)) throw new Error('Each node needs a unique ID, name, and type.');
    ids.add(n.id);
    return {id:n.id, label:n.label, kind:n.kind, x:Number.isFinite(n.x) ? Math.max(-10000, Math.min(10000, n.x)) : 0, y:Number.isFinite(n.y) ? Math.max(-10000, Math.min(10000, n.y)) : 0};
  });
  const nodeIds = new Set(ids);
  const edges = value.edges.map(e => {
    if (!e || !text(e.id,100) || ids.has(e.id) || !text(e.label,100) || !nodeIds.has(e.from) || !nodeIds.has(e.to)) throw new Error('Each relationship needs a unique ID, label, and two existing nodes.');
    ids.add(e.id);
    return {id:e.id, from:e.from, to:e.to, label:e.label};
  });
  return {nodes,edges};
}
if (typeof module !== 'undefined') module.exports = {validateKnowledgeGraph};
if (typeof document !== 'undefined' && document.getElementById('knowledge-canvas')) {
  (() => {
    const $ = id => document.getElementById(id);
    const storageKey = 'film-reel-knowledge-graph-v1';
    const status = message => { $('kg-status').textContent = message; };
    const color = () => document.documentElement.dataset.theme === 'light' ? '#27344b' : '#eef2fa';
    const cy = cytoscape({container:$('knowledge-canvas'),elements:[],layout:{name:'preset'},
      style:[{selector:'node',style:{label:'data(label)', 'background-color':'#6597d4',color:color(),'text-valign':'bottom','text-margin-y':7,'font-size':13,'text-wrap':'wrap','text-max-width':130}},
        {selector:'edge',style:{label:'data(label)','curve-style':'bezier','target-arrow-shape':'triangle','line-color':'#8794ac','target-arrow-color':'#8794ac',color:color(),'font-size':11,'text-rotation':'autorotate','loop-direction':'-45deg','loop-sweep':'70deg'}},
        {selector:':selected',style:{'border-width':3,'border-color':'#f5ba53','line-color':'#f5ba53','target-arrow-color':'#f5ba53'}}]});
    const snapshot = () => ({nodes:cy.nodes().map(n=>({id:n.id(),label:n.data('label'),kind:n.data('kind'),x:n.position('x'),y:n.position('y')})),edges:cy.edges().map(e=>({id:e.id(),from:e.source().id(),to:e.target().id(),label:e.data('label')}))});
    let selected = null, previous = null, sequence = 0;
    const newId = () => 'g-' + Date.now().toString(36) + '-' + (++sequence) + '-' + Math.random().toString(36).slice(2,9);
    const remember = () => { previous = snapshot(); $('kg-undo').disabled = false; };
    function refresh() {
      for (const id of ['kg-from','kg-to']) {
        const select = $(id), prior = select.value;
        select.replaceChildren();
        cy.nodes().forEach(n=>{const option=document.createElement('option');option.value=n.id();option.textContent=n.data('label')+' · '+n.data('kind');select.append(option);});
        if ([...select.options].some(o=>o.value===prior)) select.value=prior;
      }
      $('kg-list').replaceChildren();
      cy.elements().forEach(item=>{
        const button=document.createElement('button');button.className='kg-list-item';button.type='button';
        button.textContent=item.isNode() ? item.data('label')+' ('+item.data('kind')+')' : item.source().data('label')+' → '+item.data('label')+' → '+item.target().data('label');
        button.addEventListener('click',()=>{cy.elements().unselect();item.select();cy.animate({center:{eles:item},duration:200});});
        $('kg-list').append(button);
      });
      try { localStorage.setItem(storageKey,JSON.stringify(snapshot())); status(`${cy.nodes().length} nodes · ${cy.edges().length} relationships · Saved in this browser`); }
      catch { status('Browser storage is unavailable. Export JSON to keep this graph.'); }
    }
    function replace(value) {
      const graph=validateKnowledgeGraph(value);
      cy.elements().remove();selected=null;$('kg-edit-form').hidden=true;
      cy.add(graph.nodes.map(n=>({group:'nodes',data:{id:n.id,label:n.label,kind:n.kind},position:{x:n.x,y:n.y}})));
      cy.add(graph.edges.map(e=>({group:'edges',data:{id:e.id,source:e.from,target:e.to,label:e.label}})));
      cy.fit(undefined,45);refresh();
    }
    cy.on('select', event=>{
      selected=event.target;
      $('kg-selected').textContent=selected.isNode() ? `${selected.data('label')} · ${selected.data('kind')}` : `${selected.source().data('label')} → ${selected.data('label')} → ${selected.target().data('label')}`;
      $('kg-edit-label').value=selected.data('label');$('kg-edit-form').hidden=false;
    });
    cy.on('unselect',()=>{selected=null;$('kg-edit-form').hidden=true;$('kg-selected').textContent='Select a node or relationship to inspect it.';});
    cy.on('dragfree','node',refresh);
    cy.on('grab','node',remember);
    $('kg-node-form').addEventListener('submit',event=>{
      event.preventDefault();
      if(cy.nodes().length>=200)return status('This canvas is limited to 200 nodes.');
      const label=$('kg-label').value.trim(),kind=$('kg-kind').value.trim();if(!label||!kind)return;
      remember();const extent=cy.extent();
      cy.add({data:{id:newId(),label,kind},position:{x:(extent.x1+extent.x2)/2+Math.random()*80-40,y:(extent.y1+extent.y2)/2+Math.random()*80-40}});
      $('kg-label').value='';$('kg-label').focus();refresh();
    });
    $('kg-edge-form').addEventListener('submit',event=>{
      event.preventDefault();
      if(cy.edges().length>=500)return status('This canvas is limited to 500 relationships.');
      const from=$('kg-from').value,to=$('kg-to').value,label=$('kg-relation').value.trim();if(!from||!to||!label)return;
      remember();cy.add({data:{id:newId(),source:from,target:to,label}});refresh();
    });
    $('kg-edit-form').addEventListener('submit',event=>{event.preventDefault();if(!selected)return;const label=$('kg-edit-label').value.trim();if(!label)return;remember();selected.data('label',label);refresh();$('kg-selected').textContent=label;});
    $('kg-delete').addEventListener('click',()=>{if(!selected)return;remember();selected.remove();selected=null;$('kg-edit-form').hidden=true;refresh();});
    $('kg-fit').addEventListener('click',()=>cy.fit(undefined,45));
    $('kg-undo').addEventListener('click',()=>{if(previous){const current=snapshot();replace(previous);previous=current;}});
    $('kg-clear').addEventListener('click',()=>{remember();replace({nodes:[],edges:[]});});
    $('kg-example').addEventListener('click',()=>{
      remember();replace({nodes:[{id:'person',label:'An actor',kind:'Person',x:0,y:0},{id:'movie',label:'A favorite movie',kind:'Movie',x:220,y:0},{id:'theme',label:'An idea worth exploring',kind:'Idea',x:110,y:180}],edges:[{id:'credit',from:'person',to:'movie',label:'acted in'},{id:'theme-link',from:'movie',to:'theme',label:'explores'}]});
    });
    $('kg-export').addEventListener('click',()=>{const url=URL.createObjectURL(new Blob([JSON.stringify(snapshot(),null,2)],{type:'application/json'}));const link=document.createElement('a');link.href=url;link.download='my-knowledge-graph.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
    $('kg-import').addEventListener('change',async event=>{
      try {const file=event.target.files[0];if(!file)return;if(file.size>1024*1024)throw new Error('Choose a JSON file smaller than 1 MB.');const value=validateKnowledgeGraph(JSON.parse(await file.text()));remember();replace(value);}
      catch(error){status('Import failed: '+error.message);}finally{event.target.value='';}
    });
    document.addEventListener('themechange',()=>cy.style().selector('node,edge').style('color',color()).update());
    try { const saved=localStorage.getItem(storageKey);if(saved)replace(JSON.parse(saved));else refresh(); }
    catch { status('The saved graph could not be loaded. Import a JSON copy or start a new canvas.'); }
  })();
}
