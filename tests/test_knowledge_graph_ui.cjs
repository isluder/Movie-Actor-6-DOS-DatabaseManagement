const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const realCy = require('../src/static/vendor/cytoscape-3.33.0.min.js');
const {validateKnowledgeGraph} = require('../src/static/knowledge_graph.js');
assert.throws(()=>validateKnowledgeGraph({nodes:[{id:'x',label:'X',kind:'Idea'}],edges:[{id:'e',from:'x',to:'missing',label:'broken'}]}));
assert.throws(()=>validateKnowledgeGraph({nodes:[{id:'x',label:'X',kind:'Idea'},{id:'x',label:'Y',kind:'Idea'}],edges:[]}));
assert.throws(()=>validateKnowledgeGraph({nodes:Array(201).fill({}),edges:[]}));
assert.throws(()=>validateKnowledgeGraph({nodes:[],edges:[{id:'bad'}]}));
assert.equal(validateKnowledgeGraph({nodes:[{id:'x',label:'<script>text</script>',kind:'Idea',x:Infinity}],edges:[]}).nodes[0].x,0);
class Element {
  constructor(){this.value='';this.hidden=false;this.disabled=false;this.textContent='';this.options=[];this.handlers={};this.files=[];}
  addEventListener(name,fn){this.handlers[name]=fn;}
  replaceChildren(){this.options=[];}
  append(item){this.options.push(item);if(!this.value)this.value=item.value;}
  focus(){}
  click(){this.clicked=true;}
  async trigger(name){return this.handlers[name]?.({preventDefault(){},target:this});}
}
const elements = {};
for (const match of fs.readFileSync('src/templates/knowledge_graph.html','utf8').matchAll(/id="([^"]+)"/g)) elements[match[1]]=new Element();
let cy, stored;
const document = {getElementById:id=>elements[id]??=new Element(),documentElement:{dataset:{theme:'dark'}},createElement:()=>new Element(),addEventListener(){}};
vm.runInNewContext(fs.readFileSync('src/static/knowledge_graph.js','utf8'),{document,cytoscape:options=>{cy=realCy({headless:true,styleEnabled:true,style:JSON.parse(JSON.stringify(options.style))});const add=cy.add.bind(cy);cy.add=items=>add(JSON.parse(JSON.stringify(items)));return cy;},localStorage:{getItem:()=>null,setItem:(key,value)=>stored=value},URL:{createObjectURL:()=>'',revokeObjectURL(){}},Blob, Object, Array, Map, Set, Date, Math, JSON, Number, String, setTimeout:()=>{},console});
(async()=>{
  await elements['kg-example'].trigger('click');
  assert.equal(cy.nodes().length,3);assert.equal(cy.edges().length,2);
  assert.equal(JSON.parse(stored).nodes.length,3);
  elements['kg-label'].value='My new idea';elements['kg-kind'].value='Idea';
  await elements['kg-node-form'].trigger('submit');assert.equal(cy.nodes().length,4);
  const node=cy.nodes().last();cy.elements().unselect();node.select();
  elements['kg-edit-label'].value='Renamed';await elements['kg-edit-form'].trigger('submit');assert.equal(node.data('label'),'Renamed');
  elements['kg-from'].value=node.id();elements['kg-to'].value='movie';elements['kg-relation'].value='inspired by';
  await elements['kg-edge-form'].trigger('submit');assert.equal(cy.edges().length,3);
  await elements['kg-delete'].trigger('click');assert.equal(cy.nodes().length,3);assert.equal(cy.edges().length,2);
  await elements['kg-undo'].trigger('click');assert.equal(cy.nodes().length,4);assert.equal(cy.edges().length,3);
  await elements['kg-clear'].trigger('click');assert.equal(cy.nodes().length,0);
  await elements['kg-undo'].trigger('click');assert.equal(cy.nodes().length,4);
  const prior=JSON.stringify(JSON.parse(stored));
  elements['kg-import'].files=[{size:10,text:async()=>'{"nodes":[],"edges":[{}]}'}];
  await elements['kg-import'].trigger('change');assert.match(elements['kg-status'].textContent,/Import failed/);assert.equal(stored,prior);
  elements['kg-import'].files=[{size:10,text:async()=>'{}'}];await elements['kg-import'].trigger('change');assert.equal(cy.nodes().length,4);
  elements['kg-import'].files=[{size:10,text:async()=>'{"nodes":[],"edges":[]}'}];await elements['kg-import'].trigger('change');assert.equal(cy.nodes().length,0);
  cy.destroy();console.log('Knowledge graph validation, add, connect, rename, delete, undo, save, and import checks passed.');
})().catch(error=>{cy.destroy();console.error(error);process.exitCode=1;});
