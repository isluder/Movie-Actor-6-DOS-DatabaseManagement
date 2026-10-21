/* Exercise real Cytoscape events headlessly; no server or browser is started. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const realCytoscape = require('../src/static/vendor/cytoscape-3.33.0.min.js');
class Element {
  constructor() {this.children=[];this.events={};this.value='';this.textContent='';}
  append(...children) {this.children.push(...children);}
  replaceChildren(...children) {this.children=children;}
  addEventListener(name,fn) {this.events[name]=fn;}
}
const actor=(id,onPath=false)=>({data:{id:`actor:${id}`,kind:'actor',label:`Actor ${id}`,on_path:onPath,details:{actor_id:id,movie_count:2}}});
const movie=(id,onPath=false)=>({data:{id:`movie:${id}`,kind:'movie',label:`Movie ${id}`,on_path:onPath,details:{movie_id:id,sources:[]}}});
const edge=(mid,aid,onPath=false)=>({data:{id:`cast:${mid}:${aid}`,source:`actor:${aid}`,target:`movie:${mid}`,on_path:onPath,details:[]}});
const base={status:'found',source:'both',catalog_version:'version1',degrees:1,depth:0,
  nodes:[actor(1,true),movie(10,true),actor(2,true)],edges:[edge(10,1,true),edge(10,2,true)],
  path:[{id:'actor:1',kind:'actor',label:'Actor 1',entity_id:1},{id:'movie:10',kind:'movie',label:'Movie 10',entity_id:10},{id:'actor:2',kind:'actor',label:'Actor 2',entity_id:2}]};
const elements = Object.fromEntries(['graph-data','depth','degrees-form','graph-status','text-path','graph-details','graph-reset','graph-path-only','depth-value','graph'].map(key=>[key,new Element()]));
elements['graph-data'].textContent=JSON.stringify(base);elements.depth.value='0';
elements['degrees-form'].elements={start:{value:'1'},end:{value:'2'},source:{value:'both'}};
let cy, calls=[], nextResponse, resolvePending;
const context={document:{getElementById:id=>elements[id],createElement:()=>new Element(),querySelector:()=>null},
  window:{cytoscape:true},cytoscape:opts=>(cy=realCytoscape({headless:true,elements:JSON.parse(JSON.stringify(opts.elements)),layout:{name:'preset'}})),
  URLSearchParams,AbortController,setTimeout,clearTimeout,
  FormData:class {constructor(form){this.items=Object.entries(form.elements).map(([k,v])=>[k,v.value]);}*[Symbol.iterator](){yield* this.items;}},
  history:{replaceState(){}},fetch:async url=>{calls.push(new URL(url,'http://local').searchParams);return nextResponse();}};
vm.runInNewContext(fs.readFileSync('src/static/graph.js','utf8'),context);
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const response=data=>({ok:true,json:async()=>data});
(async()=>{
  assert.equal(cy.nodes().length,3);
  const position={...cy.$id('actor:1').position()};
  nextResponse=async()=>response({catalog_version:'version1',nodes:[actor(1),movie(10),movie(11)],edges:[edge(10,1),edge(11,1)],next_offset:2,total:3,has_more:true});
  cy.$id('actor:1').emit('dbltap');await flush();
  assert.equal(cy.nodes().length,4);assert.equal(calls[0].get('offset'),'0');
  assert.equal(cy.$id('actor:1').data('on_path'),true);assert.equal(cy.$id('cast:10:1').data('on_path'),true);
  assert.deepEqual(cy.$id('actor:1').position(),position);
  nextResponse=async()=>response({catalog_version:'version1',nodes:[actor(1),movie(12)],edges:[edge(12,1)],next_offset:3,total:3,has_more:false});
  cy.$id('actor:1').emit('dbltap');await flush();
  assert.equal(calls[1].get('offset'),'2');assert.equal(cy.nodes().length,5);
  cy.$id('actor:1').emit('dbltap');await flush();assert.equal(calls.length,2);
  // Expand a movie to its cast through the same interaction.
  nextResponse=async()=>response({catalog_version:'version1',nodes:[movie(11),actor(3)],edges:[edge(11,3)],next_offset:1,total:1,has_more:false});
  cy.$id('movie:11').emit('dbltap');await flush();assert.equal(cy.nodes().length,6);
  // A pending expansion must not append nodes to a newly reset path.
  nextResponse=()=>new Promise(resolve=>{resolvePending=resolve;});
  cy.$id('actor:2').emit('dbltap');await flush();
  elements['graph-path-only'].events.click();assert.equal(cy.nodes().length,3);
  resolvePending(response({catalog_version:'version1',nodes:[movie(99)],edges:[],next_offset:1,total:1,has_more:false}));await flush();
  assert.equal(cy.$id('movie:99').length,0);
  // A stale catalog response is rejected without changing the graph.
  nextResponse=async()=>response({catalog_version:'old',nodes:[movie(99)],edges:[],next_offset:1,total:1,has_more:false});
  cy.$id('actor:1').emit('dbltap');await flush();assert.equal(cy.nodes().length,3);
  assert.match(elements['graph-status'].textContent,/catalog changed/);
  cy.destroy();console.log('Graph UI: double-click actor/movie expansion, paging, duplicate/path preservation, stable positions, reset and stale-response checks passed.');
})().catch(error=>{cy?.destroy();console.error(error);process.exitCode=1;});
