'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class Element {
  constructor(){this.events={};this.children=[];this.value='';this.style={};this.textContent='';}
  addEventListener(name,fn){this.events[name]=fn;}
  dispatchEvent(event){this.events[event.type]?.(event);}
  append(...children){this.children.push(...children);}
  replaceChildren(...children){this.children=children;}
  setAttribute(){}
}
const ids=['start','source','distance-status','distance-chart','distance-source','dashboard-data','farthest-connection'];
const e=Object.fromEntries(ids.map(id=>[id,new Element()]));
e['dashboard-data'].textContent=JSON.stringify({page:'degrees',metrics:[],defaults:[]});
e.source.value='both';
const requests=[];
vm.runInNewContext(fs.readFileSync('src/static/distances.js','utf8'),{
  document:{getElementById:id=>e[id],createElement:()=>new Element()},
  CustomEvent:class {constructor(type,options){this.type=type;this.detail=options.detail;}},
  URLSearchParams,AbortController,Intl,
  fetch:(url,options)=>new Promise(resolve=>requests.push({url,options,resolve}))
});
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const complete={status:'complete',actor_name:'Actor A',source:'both',connected:2,disconnected:1,
  maximum:7,farthest_count:1,farthest_path:[{kind:'actor',entity_id:1,label:'Actor A'},{kind:'movie',entity_id:9,label:'Movie Z'},{kind:'actor',entity_id:9,label:'Farthest Actor'}],
  distribution:[{degrees:1,actors:1},{degrees:7,actors:1}],dashboard:{page:'degrees',metrics:[]}};
const respond=(index,data)=>requests[index].resolve({ok:true,json:async()=>data});
(async()=>{
  assert.equal(requests.length,0);
  e.start.value='1';e.start.events.change();
  assert.match(requests[0].url,/start=1/);
  e.start.value='2';e.start.events.change();assert.equal(requests[0].options.signal.aborted,true);
  respond(1,{...complete,actor_name:'Actor B'});await flush();
  assert.match(e['distance-status'].textContent,/Actor B: 2 connected actors and 1 not connected/);
  assert.match(e['farthest-connection'].children[0].textContent,/7 degrees · Farthest Actor/);
  const table=e['distance-chart'].children[0];
  assert.equal(table.children[2].children.length,2);
  assert.match(table.children[2].children[1].children[1].children[0].className,/beyond-six/);
  respond(0,complete);await flush();assert.match(e['distance-status'].textContent,/Actor B/);
  // Source changes recalculate; interrupted work must not claim disconnection.
  e.source.value='tmdb';e.source.events.change();assert.match(requests[2].url,/source=tmdb/);
  respond(2,{status:'interrupted'});await flush();
  assert.match(e['distance-status'].textContent,/Connectivity is unknown/);
  assert.equal(e['distance-chart'].children.length,0);
  e.start.value='';e.start.events.change();assert.match(e['distance-status'].textContent,/Select a From actor/);
  // Isolated actors have no histogram bars or misleading average.
  e.start.value='3';e.start.events.change();
  respond(3,{...complete,connected:0,disconnected:3,distribution:[]});await flush();
  assert.match(e['distance-chart'].children[0].textContent,/No other actors/);
  console.log('Distance UI: automatic selection/source refresh, exact bins, stale-response protection, interrupted and isolated states passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
