// Run with: node 6_display/car/car.test.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
function element() {
  const listeners = {}, classes = new Set();
  return {
    listeners, style:{}, hidden:false, clientWidth:800, clientHeight:600,
    classList:{add:(...xs)=>xs.forEach(x=>classes.add(x)),remove:(...xs)=>xs.forEach(x=>classes.delete(x)),toggle:(x,on)=>on?classes.add(x):classes.delete(x)},
    addEventListener:(name,fn)=>listeners[name]=fn, append(){}, setAttribute(){}, setPointerCapture(){}, blur(){},
    getBoundingClientRect:()=>({left:100,top:50,width:800,height:600})
  };
}
const elements=[], container=element(), events={};
const map={getZoom:()=>6.5,getPitch:()=>52,getBearing:()=>-8,getPadding:()=>({}),getMaxPitch:()=>60,
  getCenter:()=>({lng:1,lat:1}),getContainer:()=>container,setMaxPitch(){},jumpTo(view){this.lastView=view;},on(){}};
for(const h of ['dragPan','dragRotate','touchZoomRotate','touchPitch','keyboard','doubleClickZoom','scrollZoom']) {
  map[h]={enabled:h!=='keyboard',isEnabled(){return this.enabled;},enable(){this.enabled=true;},disable(){this.enabled=false;}};
}
let picked=[1.5,1.5,20], redraws=0;
const context=vm.createContext({window:{}, document:{createElement:()=>{const e=element();elements.push(e);return e;},body:element(),getElementById:()=>element()},
  addEventListener:(name,fn)=>events[name]=fn,performance:{now:()=>0},requestAnimationFrame(){},setTimeout(){},innerWidth:1000});
vm.runInContext(fs.readFileSync(__dirname+'/car.js','utf8'),context);
const car=context.window.createCarMechanics({deck:{SimpleMeshLayer:class{constructor(props){Object.assign(this,props);}}},map,
  terrain:{x0:0,y0:3,step:1,NR:4,NC:4,GZ:new Float32Array(16).fill(10),outline:[[[.1,.1],[2.9,.1],[2.9,2.9],[.1,2.9],[.1,.1]]],getExaggeration:()=>1},
  getRelief:()=>1,setRelief(){},refresh:()=>redraws++,pickTerrain:()=>picked});
const dock=elements.find(e=>e.id==='car-dock');
assert.equal(car.layer().data.length,0,'no automatic spawn');
assert.equal(car.place([0,0]),false,'outside outline rejected even with terrain grid');
assert.equal(car.place([9,9]),false,'outside grid rejected');
const pointer=(x,y)=>({button:0,pointerId:1,clientX:x,clientY:y});
dock.listeners.pointerdown(pointer(920,700));
assert.equal(car.isPlacing(),true);
dock.listeners.pointermove(pointer(400,300));
dock.listeners.pointerup(pointer(400,300));
assert.equal(car.state.placed,true); assert.equal(car.state.selected,true);
assert.deepEqual(Array.from(car.state.pos),[1.5,1.5]);
assert.equal(car.isPlacing(),false); assert.equal(map.dragPan.enabled,false);
car.state.pos=[1.5,2.89999]; car.state.speed=100000;
car.tick(.05);
assert.equal(car.state.placed,true,'car remains visible after crossing boundary');
assert.equal(car.state.falling,true);
assert.equal(car.layer().data.length,1);
const edgeZ=car.layer().getPosition(car.state)[2], edgeY=car.state.pos[1], cameraAtEdge=map.lastView;
car.tick(.05);
assert(car.layer().getPosition(car.state)[2]<edgeZ,'car falls below its edge altitude');
assert(car.state.pos[1]>edgeY,'forward momentum continues during fall');
assert.equal(map.lastView,cameraAtEdge,'camera holds at edge instead of following underground');
assert.equal(car.state.selected,true);
car.click({object:car.state}); assert.equal(car.state.selected,true,'click cannot strand a falling car');
for(let i=0;i<60;i++) car.tick(.05);
assert.equal(car.state.placed,false,'completed fall returns car to dock');
assert.equal(car.state.falling,false);
assert.equal(car.layer().data.length,0); assert.equal(car.driveKeys.size,0);
assert.equal(map.dragPan.enabled,true); assert.equal(map.keyboard.enabled,false,'original disabled handlers stay disabled');
assert.equal(map.lastView.center.lng,1,'overview restored');
dock.listeners.pointerdown(pointer(920,700)); dock.listeners.pointermove(pointer(950,720)); dock.listeners.pointerup(pointer(950,720));
assert.equal(car.state.placed,false,'drop outside map rejected');
dock.listeners.pointerdown(pointer(920,700)); dock.listeners.pointercancel(); assert.equal(car.isPlacing(),false);
assert.equal(car.place([1.2,1.2]),true,'can place again after reset');
const key=(code,target={})=>({code,target,preventDefault(){this.prevented=true;}});
const up=key('ArrowUp',{matches:()=>false}); events.keydown(up);
assert.equal(car.driveKeys.has('KeyW'),true,'ArrowUp drives like W'); assert.equal(up.prevented,true);
events.keyup(key('ArrowUp')); assert.equal(car.driveKeys.has('KeyW'),false);
events.keydown(key('ArrowLeft',{matches:()=>true})); assert.equal(car.driveKeys.size,0,'keys typed into a text box are left alone');
events.keydown({code:'Escape'}); assert.equal(car.state.placed,true); assert.equal(car.state.selected,false,'Escape still pauses normal driving');
events.keydown({code:'Escape'}); assert.equal(car.state.selected,true);
car.state.pos=[1.5,2.89999]; car.state.speed=100000; car.tick(.05);
assert.equal(car.state.falling,true);
events.keydown({code:'Escape'}); assert.equal(car.state.placed,false,'Escape can skip the fall');
assert(redraws>0);
console.log('Car placement, drag cancellation, invalid drops, animated fall, delayed reset, camera restoration and reuse passed.');
