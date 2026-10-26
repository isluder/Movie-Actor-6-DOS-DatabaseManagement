const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const realCy=require('../src/static/vendor/cytoscape-3.33.0.min.js');
class Element {
  constructor(){this.value='';this.hidden=false;this.disabled=false;this.textContent='';this.children=[];this.handlers={};}
  addEventListener(name,fn){this.handlers[name]=fn;}
  replaceChildren(){this.children=[];}
  append(item){this.children.push(item);}
  click(){return this.trigger('click');}
  trigger(name){return this.handlers[name]?.({preventDefault(){},target:this});}
}
const elements={};for(const match of fs.readFileSync('src/templates/knowledge_graph.html','utf8').matchAll(/id="([^"]+)"/g))elements[match[1]]=new Element();
elements['kg-config'].textContent=JSON.stringify({version:'v1',sources:{movies:'The Movies Dataset',tmdb:'TMDB 5000'}});
const fields={kind:'movie',q:'Toy',source:'movies',edge:'both',role:'',genre_id:'',min_budget:'',max_budget:'',min_revenue:'',max_revenue:''};
let cy,calls=[],exported,fail=false,delayed=null,malformed=false;
const timers=new Map();let timerSequence=0;
async function runTimers(){const callbacks=[...timers.values()];timers.clear();for(const callback of callbacks)await callback();}
const movie={data:{id:'movie:862',kind:'movie',label:'Toy Story',values:[{source:'movies',title:'Toy Story',budget:30000000,revenue:373554033}]}};
const actor={data:{id:'actor:31',kind:'actor',label:'Tom Hanks'}};
const edge={data:{id:'cast:862:31',source:'actor:31',target:'movie:862',kind:'cast',label:'acted in',details:[{source:'movies',role:'Woody (voice)'}]}};
const document={body:{dataset:{movieDetails:'disabled'}},getElementById:id=>elements[id]??=new Element(),documentElement:{dataset:{theme:'dark'}},createElement:()=>new Element(),addEventListener(){}};
const fetch=async url=>{
  calls.push(url);if(delayed)await delayed;
  if(malformed)return {ok:false,json:async()=>{throw new SyntaxError('HTML');}};
  if(url.startsWith('/api/knowledge-graph/suggestions'))return {ok:true,json:async()=>({suggestions:[{value:'Toy Story',kind:'movie'}]})};
  if(fail)return {ok:false,json:async()=>({errors:{filter:'Invalid filters'}})};
  const params=new URL(url,'http://test').searchParams;
  const search=url.startsWith('/api/knowledge-graph/search');
  const expand=params.has('expand');
  return {ok:true,json:async()=>search?{results:[{id:'movie:862',label:'Toy Story',kind:'movie'}],has_more:false,next_offset:1,catalog_version:'v1'}:{nodes:expand?[movie,actor]:[movie],edges:expand?[edge]:[],catalog_version:'v1',has_more:false}};
};
const context={document,FormData:class{constructor(){return Object.entries(fields);}},URLSearchParams,fetch,
  cytoscape:options=>{cy=realCy({headless:true,styleEnabled:true,style:JSON.parse(JSON.stringify(options.style))});const add=cy.add.bind(cy);cy.add=items=>add(JSON.parse(JSON.stringify(items)));return cy;},
  URL:class extends URL{static createObjectURL(value){exported=value;return 'blob:test';}static revokeObjectURL(){}},Blob,setTimeout:callback=>{const id=++timerSequence;timers.set(id,callback);return id;},clearTimeout:id=>timers.delete(id),console};
vm.runInNewContext(fs.readFileSync('src/static/knowledge_graph.js','utf8'),context);
const flush=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
  elements['kg-query'].value='T';fields.q='T';elements['kg-query'].trigger('input');await runTimers();assert.equal(calls.length,0);
  elements['kg-query'].value='To';fields.q='To';elements['kg-query'].trigger('input');
  elements['kg-query'].value='Toy';fields.q='Toy';elements['kg-query'].trigger('input');await runTimers();
  assert.equal(calls.length,1);assert.match(calls[0],/suggestions/);assert.match(calls[0],/q=Toy/);assert.equal(elements['kg-query-suggestions'].children[0].value,'Toy Story');
  elements['kg-role'].value='Wo';fields.role='Wo';elements['kg-role'].trigger('input');await runTimers();assert.match(calls.at(-1),/field=role/);
  fields.role='';elements['kg-role'].value='';
  let releaseSuggestion;delayed=new Promise(resolve=>releaseSuggestion=resolve);elements['kg-query'].trigger('input');const pending=runTimers();
  elements['kg-query'].value='';elements['kg-query'].trigger('input');releaseSuggestion();await pending;delayed=null;assert.equal(elements['kg-query-suggestions'].children.length,0);
  malformed=true;await elements['kg-search-form'].trigger('submit');assert.match(elements['kg-status'].textContent,/Restart Flask/);malformed=false;
  calls=[];
  await elements['kg-search-form'].trigger('submit');
  assert.match(calls[0],/q=Toy/);assert.equal(elements['kg-results'].children.length,2);
  await elements['kg-results'].children[1].click();assert.equal(cy.nodes().length,1);
  cy.getElementById('movie:862').emit('dbltap');await flush();await flush();
  assert.match(calls.at(-1),/expand=movie%3A862/);assert.equal(cy.nodes().length,2);assert.equal(cy.edges().length,1);
  cy.getElementById('cast:862:31').select();assert.equal(elements['kg-expand'].disabled,true);
  assert.match(elements['kg-selected'].children.at(-1).textContent,/Woody/);
  cy.elements().unselect();cy.getElementById('movie:862').select();
  assert.equal(elements['kg-expand'].disabled,false);
  assert.match(elements['kg-selected'].children[1].textContent,/30,000,000/);
  assert.ok(elements['kg-selected'].children.every(child=>!child.href));
  elements['kg-text-size'].value='22';elements['kg-text-size'].trigger('input');assert.equal(cy.nodes().first().style('font-size'),'22px');
  fields.role='voice';fields.min_revenue='1000000';fields.edge='cast';
  await elements['kg-search-form'].trigger('submit');assert.match(calls.at(-1),/role=voice/);assert.match(calls.at(-1),/min_revenue=1000000/);assert.match(calls.at(-1),/edge=cast/);
  await elements['kg-export'].click();const output=JSON.parse(await exported.text());assert.equal(output.nodes[0].data.id,'movie:862');assert.equal(output.filters.role,'voice');
  cy.elements().unselect();cy.nodes().first().select();elements['kg-remove'].click();assert.equal(cy.nodes().length,0);
  fail=true;await elements['kg-search-form'].trigger('submit');assert.match(elements['kg-status'].textContent,/Invalid filters/);fail=false;
  await elements['kg-search-form'].trigger('submit');
  await elements['kg-results'].children[1].click();assert.equal(cy.nodes().length,1);
  let release;delayed=new Promise(resolve=>release=resolve);cy.nodes().first().emit('dbltap');
  elements['kg-clear'].click();release();await flush();await flush();assert.equal(cy.nodes().length,0);
  assert.ok(calls.every(url=>url.startsWith('/api/knowledge-graph/')));
  cy.destroy();delayed=null;calls=[];fields.min_revenue='';fields.role='';
  context.location={hash:'#source=both&catalog_version=v1&node=movie%3A862&focus=movie%3A862'};
  vm.runInNewContext(fs.readFileSync('src/static/knowledge_graph.js','utf8'),context);
  await flush();await flush();assert.equal(cy.nodes().length,1);
  assert.match(calls[0],/source=both/);assert.match(calls[0],/node=movie%3A862/);
  assert.equal(elements['kg-source'].value,'both');assert.equal(cy.nodes().first().selected(),true);
  cy.destroy();calls=[];context.location.hash='#source=both&catalog_version=old&node=movie%3A862';
  vm.runInNewContext(fs.readFileSync('src/static/knowledge_graph.js','utf8'),context);
  assert.equal(calls.length,0);assert.match(elements['kg-status'].textContent,/catalog changed/);
  cy.destroy();console.log('Catalog graph UI: search, add, double-click expansion, source data, role/financial/edge filters, text size, export, remove, errors, autocomplete debounce, stale suggestions, and stale responses passed.');
})().catch(error=>{cy.destroy();console.error(error);process.exitCode=1;});
