const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync(__dirname + '/template.html','utf8');
const script = html.match(/<script>\s*([\s\S]*?)<\/script>/)[1].replace('const META = __META__;','const META = {};');
new vm.Script(script);
const elements = new Map(), saved = new Map();
const context = vm.createContext({ console, structuredClone, crypto:require('node:crypto').webcrypto,
  $:id => { if (!elements.has(id)) elements.set(id,{setAttribute(){}}); return elements.get(id); },
  localStorage:{getItem:k=>saved.get(k),setItem:(k,v)=>saved.set(k,v)},
  map:{unproject:()=>({lng:145,lat:-35})}, D:{engineHash:'test'}, rtApplied:false, redraw(){},
});
const areaEditor = html.slice(html.indexOf('// ---- Runoff area editor'), html.indexOf('// ---- end runoff area editor'));
vm.runInContext(areaEditor + `let RT = null;` + html.slice(html.indexOf('// Drafts store only'),html.indexOf("$('routing-edit').onclick")),context);
const run = code => vm.runInContext(code,context);
run(`RT = {nodes:['a','b','c'].map((id,i)=>({id,lon:145+i,lat:-35,model:{id,basin:'basin',share:1/3,area:100,length:10,next:i<2?['b','c'][i]:'',outlet:i===2,river:true}})),links:[]};
RT.links = [{a:RT.nodes[0],b:RT.nodes[1],path:[[145,-35],[146,-35]],w:3},{a:RT.nodes[1],b:RT.nodes[2],path:[[146,-35],[147,-35]],w:3}];
rtBase = rtPack(RT); rtSystem = 'test'; rtSelected = 'b';`);
assert.equal(run("rtWouldCycle('c','a')"),true);
assert.equal(run("rtWouldCycle('a','c')"),false);
elements.get('rt-delete').onclick();
assert.equal(run('RT.nodes.length'),2);
assert.equal(run('RT.links[0].b.id'),'c');
elements.get('rt-undo').onclick();
assert.equal(run('RT.nodes.length'),3);
run("rtSelected='b'");
const previousNodes=run('RT.nodes'), previousLinks=run('RT.links');
elements.get('rt-move').onclick();
run("rtClick({x:10,y:20,coordinate:[149,-32]})");
assert.equal(run("RT.nodes.find(n=>n.id==='b').lon"),149);
assert.notEqual(run('RT.nodes'),previousNodes);
assert.notEqual(run('RT.links'),previousLinks); // redraw map geometry after edits
assert.equal(run('RT.links[0].path[1][0]'),149);
assert.equal(run('RT.links[1].path[0][0]'),149);
context.$('rt-share').value = '25';
elements.get('rt-add').onclick();run('rtClick({x:10,y:20,coordinate:[148,-33]})');
assert.equal(run('RT.nodes.length'),4);
assert.equal(run('RT.links.at(-1).b.id'),'b');
run("rtSelected='c'");elements.get('rt-connect').onclick();run("rtClick({layer:{id:'rt-nodes'},object:RT.nodes[0]})");
assert.equal(run('RT.links.length'),3); // cycle refused
run("rtSelected='a'");elements.get('rt-connect').onclick();run("rtClick({layer:{id:'rt-nodes'},object:RT.nodes[2]})");
assert.equal(run("RT.links.find(l=>l.a.id==='a').b.id"),'c');
assert.equal(saved.size,1);
run('RT=rtUnpack(JSON.parse(localStorage.getItem(rtKey())))');
assert.equal(run("RT.links.find(l=>l.a.id==='a').b === RT.nodes.find(n=>n.id==='c')"),true);
elements.get('rt-reset').onclick();assert.equal(run('RT.nodes.length'),3);
run("rtSelected='c'"); elements.get('rt-delete').onclick();
assert.equal(run('RT.nodes.length'),3); // nothing below the system outlet to take its flow
for(const id of ['a','b']) {run(`rtSelected='${id}'`);elements.get('rt-delete').onclick();}
assert.equal(run('RT.nodes.length'),1);
assert.ok(Math.abs(run('RT.nodes[0].model.share')-1)<1e-12);
elements.get('rt-undo').onclick();assert.equal(run('RT.nodes.length'),2);
console.log('Network editor: syntax, move, add, reconnect, cycle rejection, delete, undo, persistence and reset passed.');

// Run the unchanged hydrology engine against an edited catchment network.
const hydrology = require('../docs/engine.js');
run('RT=rtUnpack(rtBase); rtSelected="b"');
const source = {nodes:run('rtPack(RT).nodes.map(n=>n.model)'),basins:[{id:'basin',area:300,next:''}],calibration:{loss_regions:null,target_outlet_m3s:null},scale:1,reachOutlet:{reach:'basin'},rivers:[],units:{unit:{outlet:'basin',ecology:null}}};
const days = Array.from({length:60},(_,i)=>new Date(Date.UTC(2027,0,i+1)).toISOString().slice(0,10));
source.P = Buffer.from(Uint16Array.from(days,(_,i)=>i<10?20:0).buffer).toString('base64');
source.PET = Buffer.from(Uint16Array.from(days,()=>2).buffer).toString('base64');
source.nodes.forEach(n=>n.length=10);
context.source = source;
const rr={algorithm:'gr4j',params:[350,0,90,1.7]}, routing={algorithm:'muskingum',params:{x:.2,velocity_km_day:86.4,delivery:{},target_scale:1,channel_width_m:10,pet_factor:1,seepage_ML_day_km:.02,misc_loss_per_km:.001}};
const baseline = hydrology.run(source,days,rr,routing);
const unchanged = run("rtEditedEngine('test',source)");
assert.deepEqual(hydrology.run(unchanged,days,rr,routing).sdl.unit.flow, baseline.sdl.unit.flow);
context.$('rt-share').value='25'; elements.get('rt-add').onclick();run('rtClick({x:0,y:0,coordinate:[148,-33]})');
const edited = run("rtEditedEngine('test',source)");
assert.equal(source.nodes.length,3);
assert.equal(edited.nodes.length,4);
assert.ok(Math.abs(edited.nodes.reduce((s,n)=>s+n.share,0)-1)<1e-12);
assert.equal(JSON.stringify(edited.calibration),JSON.stringify(source.calibration));
const result = hydrology.run(edited,days,rr,routing);
assert.ok(result.sdl.unit.flow.every(Number.isFinite));
assert.notDeepEqual(result.sdl.unit.flow,baseline.sdl.unit.flow);
console.log('Hydrology integration: tributary changes flows, preserves catchment shares and calibration, and leaves source inputs untouched.');

// Join channel: an entry wrongly routed far downstream joins the main channel at a dragged junction.
run(`RT = {nodes:[['e',145,-34.5,'x'],['x',146,-34.5,'o'],['m',145,-35,'n'],['n',146,-35,'o'],['o',147,-35,'']].map(([id,lon,lat,next])=>({id,lon,lat,model:{id,basin:'basin',share:.2,area:60,length:100,next,outlet:id==='o',river:true}})),links:[]};
const at = id => RT.nodes.find(n=>n.id===id);
RT.links = RT.nodes.filter(n=>n.model.next).map(n=>({a:n,b:at(n.model.next),path:[[n.lon,n.lat],[at(n.model.next).lon,at(n.model.next).lat]],w:3}));
rtBase = rtPack(RT); rtHistory = []; rtSelected = 'e';`);
context.joinSource = {...source, nodes:run('rtPack(RT).nodes.map(n=>n.model)')};
elements.get('rt-join').onclick();
assert.ok(run('rtGhost.lon > 145 && rtGhost.lat === -34.5')); // starts just below the entry, on its old connection
run("rtClick({coordinate:[145.5,-35.01]})");
const junction = run("RT.nodes.find(n=>n.id.startsWith('junction-'))");
assert.ok(junction && Math.abs(junction.lon-145.5)<1e-9 && junction.lat===-35); // snapped onto the main channel
assert.equal(run("RT.links.find(l=>l.a.id==='e').b.id"),junction.id);
assert.equal(run("RT.links.find(l=>l.a.id==='m').b.id"),junction.id);
assert.equal(run("RT.links.find(l=>l.a.id===RT.nodes.find(n=>n.id.startsWith('junction-')).id).b.id"),'n');
assert.equal(run("RT.nodes.some(n=>n.id==='x')"),false); // left with no inflow: removed
assert.equal(run("RT.redirects.x"),'n'); // its runoff kept by the nearest node in its basin
assert.ok(Math.abs(run('RT.nodes.reduce((s,n)=>s+n.model.share,0)')-1)<1e-12);
assert.ok(Math.abs(run("RT.links.find(l=>l.a.id==='m').km")+run("RT.links.find(l=>l.a.id===RT.nodes.find(n=>n.id.startsWith('junction-')).id).km")-100)<1e-9); // the split reach keeps its length
const joined = run("rtEditedEngine('test',joinSource)");
assert.ok(hydrology.run(joined,days,rr,routing).sdl.unit.flow.every(Number.isFinite));
run("rtSelected='m'"); elements.get('rt-join').onclick(); run("rtClick({coordinate:[146.5,-34]})");
assert.equal(run("RT.links.find(l=>l.a.id==='m').b.id"),junction.id); // a drop far from any channel is refused
elements.get('rt-undo').onclick();
assert.equal(run("RT.nodes.some(n=>n.id==='x')"),true);
console.log('Join channel: junction snaps onto the channel, splits its reach, removes stranded nodes and keeps runoff and flows valid.');

// Basin outlets: shown by their river role, and deletable, their basin's flow then read at the node below.
run(`RT = {nodes:[['a1',145,-35,'a2','A',.5],['t',145,-34.5,'a2','A',.2],['a2',146,-35,'b1','A',.3],['b1',147,-35,'b2','B',.5],['b2',148,-35,'','B',.5]].map(([id,lon,lat,next,basin,share])=>({id,lon,lat,model:{id,basin,share,area:100*share,length:50,next,outlet:id==='a2'||id==='b2',river:true}})),links:[],redirects:{}};
RT.links = RT.nodes.filter(n=>n.model.next).map(n=>({a:n,b:at(n.model.next),path:[[n.lon,n.lat],[at(n.model.next).lon,at(n.model.next).lat]],w:3}));
rtBase = rtPack(RT); rtHistory = [];`);
assert.equal(run("rtRole(at('a2'))"),'junction'); // a basin outlet where branches meet shows as a junction
assert.equal(run("rtRole(at('b1'))"),'reach');
run("at('b1').link = true"); assert.equal(run("rtRole(at('b1'))"),'link'); assert.ok(run("rtProtected(at('b1'))")); run("at('b1').link = false");
const twoBasins = {...source, nodes:run('rtPack(RT).nodes.map(n=>n.model)'), basins:[{id:'A',area:100,next:'B'},{id:'B',area:100,next:''}], reachOutlet:{ra:'A',rb:'B'}, units:{unit:{outlet:'B',ecology:null}}};
twoBasins.P = Buffer.from(Uint16Array.from([...days,...days],(_,i)=>i%60<10?20:0).buffer).toString('base64');
twoBasins.PET = Buffer.from(Uint16Array.from([...days,...days],()=>2).buffer).toString('base64');
context.twoBasins = twoBasins;
const before = hydrology.run(run("rtEditedEngine('test',twoBasins)"),days,rr,routing);
run("rtSelected='a2'"); elements.get('rt-delete').onclick();
assert.equal(run("RT.nodes.some(n=>n.id==='a2')"),false);
assert.equal(run("JSON.stringify(at('b1').model.reports)"),'["A"]'); // basin A's flow is now read at b1
const editedTwo = run("rtEditedEngine('test',twoBasins)");
const folded = editedTwo.nodes.find(n=>n.id==='a2');
assert.ok(folded && folded.basin==='A' && folded.next==='b1' && !folded.river && folded.share===.3); // its runoff joins b1 directly, still basin A's
const after = hydrology.run(editedTwo,days,rr,routing);
assert.ok(after.reachFlow.ra.every(Number.isFinite) && after.reachFlow.ra.some((v,t)=>v!==before.reachFlow.ra[t])); // read further down, so it changes
run("rtSelected='a1'"); elements.get('rt-delete').onclick(); // a1 now drains into b1 too, and its share stays with basin A
assert.ok(Math.abs(run("rtEditedEngine('test',twoBasins)").nodes.filter(n=>n.basin==='A').reduce((s,n)=>s+n.share,0)-1)<1e-12);
console.log('Basin outlets: shown by their river role, deletable, with basin reporting and runoff moved to the node below.');

// Moving straightens a node's reaches; dragging a reach reshapes it and its drawn length is what the routing uses.
run(`RT = {nodes:['a','b','c'].map((id,i)=>({id,lon:145+i,lat:-35,model:{id,basin:'basin',share:1/3,area:100,length:10,next:i<2?['b','c'][i]:'',outlet:i===2,river:true}})),links:[]};
RT.links = [{a:RT.nodes[0],b:RT.nodes[1],path:[[145,-35],[146,-35]],w:3},{a:RT.nodes[1],b:RT.nodes[2],path:[[146,-35],[147,-35]],w:3}]; rtHistory = [];
RT.links[0].path = [[145,-35],[145.3,-35.2],[145.6,-34.8],[145.9,-35.1],[146,-35]]; RT.links[0].km = 99;`);
run("rtMoveNode(at('b'),146.5,-35.5)");
assert.equal(run("JSON.stringify(RT.links.map(l=>l.path))"),'[[[145,-35],[146.5,-35.5]],[[146.5,-35.5],[147,-35]]]');
assert.equal(run("RT.links[0].km"),undefined); // its stored length is dropped: the straight line's counts
const straightKm = run("rtLength(RT.links[1].path)");
const vertex = run("rtGrabLink(RT.links[1],146.75,-35.25,1)");
assert.equal(vertex,1); // a new bend added where the line was grabbed
run(`RT.links[1].path[${vertex}] = [146.75,-34.5]`);
const drawnKm = run("rtLength(RT.links[1].path)");
assert.ok(drawnKm > straightKm + 50);
assert.equal(run("rtGrabLink(RT.links[1],146.751,-34.501,1)"),1); // grabbing near an existing bend takes that bend
assert.ok(Math.abs(run("rtEditedEngine('test',source)").nodes.find(n=>n.id==='b').length - drawnKm) < 1e-9);
console.log('Reshaping: moved nodes straighten their reaches; dragged reaches route over their drawn length.');

// Detach inflow: a reach becomes a runoff entry, a junction a reach; the detached reach runs on to the node below.
run(`RT = {nodes:[['x',145,-34.5,'j'],['y',145,-35.5,'j'],['j',146,-35,'z'],['z',147,-35,'']].map(([id,lon,lat,next])=>({id,lon,lat,model:{id,basin:'basin',share:.25,area:50,length:10,next,outlet:id==='z',river:true}})),links:[],redirects:{}};
RT.links = RT.nodes.filter(n=>n.model.next).map(n=>({a:n,b:at(n.model.next),path:[[n.lon,n.lat],[at(n.model.next).lon,at(n.model.next).lat]],w:3}));
rtBase = rtPack(RT); rtHistory = []; rtSelected = 'j';`);
assert.equal(run("rtRole(at('j'))"),'junction');
elements.get('rt-detach').onclick(); // two inflows: choose one
run("rtClick({layer:{id:'rt-nodes'},object:at('x')})");
assert.equal(run("RT.links.find(l=>l.a.id==='x').b.id"),'z');
assert.equal(run("RT.links.find(l=>l.a.id==='x').km"),20); // its own reach plus the one it now runs down
assert.equal(run("RT.links.find(l=>l.a.id==='x').path.length"),3);
assert.equal(run("rtRole(at('j'))"),'reach');
elements.get('rt-detach').onclick(); // one inflow left: detached at once
assert.equal(run("RT.links.find(l=>l.a.id==='y').b.id"),'z');
assert.equal(run("rtRole(at('j'))"),'entry');
assert.equal(run("$('rt-detach').disabled"),true); // nothing left to detach
assert.ok(Math.abs(run("rtEditedEngine('test',{...source,nodes:rtPack(rtUnpack(rtBase)).nodes.map(n=>n.model)})").nodes.find(n=>n.id==='x').length-20)<1e-9);
elements.get('rt-undo').onclick(); assert.equal(run("RT.links.find(l=>l.a.id==='y').b.id"),'j');
console.log('Detach inflow: reaches become runoff entries, junctions become reaches, detached reaches keep their length.');
