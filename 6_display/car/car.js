/* MDB Model's selectable terrain car. This file is copied into docs/car for GitHub Pages. */
window.createCarMechanics = function ({ deck, map, terrain, getRelief, setRelief, pausePlayback, refresh, pickTerrain, isWet }) {
  const playerCar = { kind:'playerCar', pos:[0,0], placed:false, heading:0, speed:0, selected:false, jump:0, jumpV:0, pitch:0, roll:0, pitchV:0, rollV:0, accel:0, grade:0, stalled:false, wet:0, course:0, slip:0, skids:[], offEdge:false, airZ:0, airV:0, falling:false, fallZ:0, fallV:0, fallTime:0, fallGravity:0 };
  const driveKeys = new Set(), driveCodes = new Set(['KeyW','KeyA','KeyS','KeyD','KeyQ','KeyE','Space','ShiftLeft','ShiftRight']);
  const hint = document.createElement('div');
  hint.id = 'driveHint';
  hint.className = 'car-drive-hint';
  hint.setAttribute('role','status');
  hint.setAttribute('aria-live','polite');
  hint.hidden = true;
  document.body.append(hint);
  const tools = document.createElement('div');
  tools.id = 'map-tools';
  const dock = document.createElement('button');
  dock.id = 'car-dock'; dock.type = 'button';
  dock.textContent = '🚗';
  dock.title = 'Drag the car onto the map to drive';
  dock.setAttribute('aria-label', 'Place car: drag onto the map, or click then click a location');
  const towns = document.getElementById('towns-toggle');
  tools.append(dock);
  if (towns) tools.append(towns);
  document.body.append(tools);
  const ghost = document.createElement('div');
  ghost.className = 'car-drag-ghost'; ghost.textContent = '🚗'; ghost.hidden = true;
  ghost.setAttribute('aria-hidden','true'); document.body.append(ghost);
  let dragging = null, choosing = false, suppressClick = false;

  function setHint(text) { hint.textContent = text; hint.hidden = !text; }
  function place(pos) {
    if (!pos || !onTerrain(pos[0],pos[1])) return false;
    exitChase();
    Object.assign(playerCar,{pos:pos.slice(0,2),placed:true,selected:true,heading:0,speed:0,jump:0,jumpV:0,pitch:0,roll:0,pitchV:0,rollV:0,accel:0,grade:0,stalled:false,wet:0,course:0,slip:0,skids:[],lastSkid:null,offEdge:false,airZ:0,airV:0,falling:false,fallZ:0,fallV:0,fallTime:0,fallGravity:0}); hintText='';
    driveKeys.clear(); choosing = false; dock.classList.remove('choosing');
    dock.classList.add('placed'); dock.blur();
    pausePlayback(); enterChase();
    hint.classList.add('active');
    setHint('Driving · W drive · A/D steer · S brake · Space jump · Q/E relief · Shift boost · Esc pause');
    refresh(); return true;
  }
  function reset() {
    exitChase(true);
    Object.assign(playerCar,{placed:false,selected:false,speed:0,jump:0,jumpV:0,pitch:0,roll:0,pitchV:0,rollV:0,accel:0,grade:0,stalled:false,wet:0,course:0,slip:0,skids:[],lastSkid:null,offEdge:false,airZ:0,airV:0,falling:false,fallZ:0,fallV:0,fallTime:0,fallGravity:0}); hintText='';
    driveKeys.clear(); choosing=false;
    dock.classList.remove('placed','choosing'); hint.classList.remove('active');
    setHint('Drag the car onto the map to drive again.'); refresh();
  }
  function dropPosition(e) {
    const box=map.getContainer().getBoundingClientRect(), x=e.clientX-box.left, y=e.clientY-box.top;
    if(x<0||y<0||x>=box.width||y>=box.height) return null;
    const hit=pickTerrain(x,y);
    if(hit&&onTerrain(hit[0],hit[1])) return hit;
    // Missed the surface (ridge in the way, valley rim, or the void just beyond it): snap to the nearest drivable
    // ground nearest to where the cursor points on the map, so a drop near the valley still lands.
    const g=map.unproject([x,y]);
    return g?nearestTerrain(g.lng,g.lat):null;
  }
  function nearestTerrain(lon,lat) {
    const {x0,y0,step}=terrain, c0=Math.round((lon-x0)/step), r0=Math.round((y0-lat)/step);
    for(let k=0;k<=150;k++) for(let dr=-k;dr<=k;dr++) {
      const step2=Math.abs(dr)===k?1:2*k||1; // only the ring's perimeter
      for(let dc=-k;dc<=k;dc+=step2) {
        const cl=x0+(c0+dc)*step, lt=y0-(r0+dr)*step;
        if(onTerrain(cl,lt)) return [cl,lt];
      }
    }
    return null;
  }
  dock.addEventListener('pointerdown',e=>{
    if(e.button!==0) return;
    dragging={id:e.pointerId,x:e.clientX,y:e.clientY,moved:false};
    dock.setPointerCapture(e.pointerId); refresh();
  });
  dock.addEventListener('pointermove',e=>{
    if(!dragging||e.pointerId!==dragging.id) return;
    if(Math.hypot(e.clientX-dragging.x,e.clientY-dragging.y)>5) dragging.moved=true;
    if(!dragging.moved) return;
    ghost.hidden=false; ghost.style.left=e.clientX+'px'; ghost.style.top=e.clientY+'px';
    const pos=dropPosition(e);
    ghost.classList.toggle('valid',!!pos&&onTerrain(pos[0],pos[1]));
  });
  function cancelDrag() { dragging=null; ghost.hidden=true; refresh(); }
  dock.addEventListener('pointerup',e=>{
    if(!dragging||e.pointerId!==dragging.id) return;
    const moved=dragging.moved, pos=moved?dropPosition(e):null; cancelDrag();
    if(moved) {
      suppressClick=true; setTimeout(()=>{suppressClick=false;},0);
      if(!place(pos)) setHint('Drop the car on the coloured terrain.');
    }
  });
  dock.addEventListener('pointercancel',cancelDrag);
  dock.addEventListener('lostpointercapture',cancelDrag);
  dock.addEventListener('click',()=>{
    if(suppressClick) return;
    if(playerCar.selected) reset();
    choosing=!choosing; dock.classList.toggle('choosing',choosing);
    setHint(choosing?'Click a location on the terrain to place the car.':''); refresh();
  });
  map.getContainer().addEventListener('click',e=>{
    if(choosing&&!place(dropPosition(e))) setHint('Choose a location on the coloured terrain.');
  });

  // Low-poly car in metres: x right, y forward (north at heading 0), z up. Per-vertex colours.
  const carMesh = (function () {
    const pos=[], nor=[], col=[], idx=[];
    function box(x0,x1,y0,y1,z0,z1,color) {
      const faces=[[[1,0,0],[x1,y0,z0],[x1,y1,z0],[x1,y1,z1],[x1,y0,z1]],[[-1,0,0],[x0,y1,z0],[x0,y0,z0],[x0,y0,z1],[x0,y1,z1]],
        [[0,1,0],[x1,y1,z0],[x0,y1,z0],[x0,y1,z1],[x1,y1,z1]],[[0,-1,0],[x0,y0,z0],[x1,y0,z0],[x1,y0,z1],[x0,y0,z1]],
        [[0,0,1],[x0,y0,z1],[x1,y0,z1],[x1,y1,z1],[x0,y1,z1]],[[0,0,-1],[x0,y1,z0],[x1,y1,z0],[x1,y0,z0],[x0,y0,z0]]];
      for(const [n,...v] of faces) {
        const base=pos.length/3;
        for(const p of v) { pos.push(...p); nor.push(...n); col.push(...color); }
        idx.push(base,base+1,base+2,base,base+2,base+3);
      }
    }
    const red=[229,87,53,255], glass=[170,215,225,255], dark=[28,34,40,255], lamp=[255,236,170,255], tail=[200,30,30,255];
    box(-1,1,-2.2,2.2,.45,1.05,red);          // body
    box(-.85,.85,-1.3,.9,1.05,1.6,glass);     // cabin
    box(-.8,.8,-1.2,.8,1.58,1.66,red);        // roof
    box(-.9,-.45,2.2,2.24,.7,.95,lamp); box(.45,.9,2.2,2.24,.7,.95,lamp);
    box(-.9,-.45,-2.24,-2.2,.7,.95,tail); box(.45,.9,-2.24,-2.2,.7,.95,tail);
    for(const sx of [-1,1]) for(const y of [-1.35,1.35]) box(sx>0?.92:-1.22,sx>0?1.22:-.92,y-.42,y+.42,0,.84,dark);
    return { attributes:{ POSITION:{value:new Float32Array(pos),size:3}, NORMAL:{value:new Float32Array(nor),size:3}, COLOR_0:{value:new Float32Array(col.map(v=>v/255)),size:4} }, indices:{value:new Uint32Array(idx),size:1} };
  })();

  // Metres-per-pixel at the car's latitude for the current zoom; used to keep the car legible and drivable at any zoom.
  function metresPerPixel() { return saved ? chaseMpp() : 78271.5*Math.cos(playerCar.pos[1]*Math.PI/180)/Math.pow(2,map.getZoom()); }

  function terrainHeightAt(lon,lat) {
    const {x0,y0,step,GZ,NR,NC} = terrain, exaggeration = terrain.getExaggeration();
    const x=(lon-x0)/step, y=(y0-lat)/step, c=Math.floor(x), r=Math.floor(y), fx=x-c, fy=y-r;
    if(r>=0&&c>=0&&r<NR-1&&c<NC-1) {
      const a=GZ[r*NC+c], b=GZ[r*NC+c+1], d=GZ[(r+1)*NC+c], e=GZ[(r+1)*NC+c+1];
      if([a,b,d,e].every(Number.isFinite)) return (fx+fy<=1 ? a*(1-fx-fy)+b*fx+d*fy : b*(1-fy)+d*(1-fx)+e*(fx+fy-1))*exaggeration;
    }
    let best=Infinity, value=0;
    for(let dr=-2;dr<=2;dr++) for(let dc=-2;dc<=2;dc++) {
      const rr=Math.round(y)+dr, cc=Math.round(x)+dc;
      if(rr<0||cc<0||rr>=NR||cc>=NC) continue;
      const z=GZ[rr*NC+cc], distance=dr*dr+dc*dc;
      if(Number.isFinite(z)&&distance<best) { best=distance; value=z; }
    }
    return value*exaggeration;
  }

  function layer() {
    const scale=Math.max(1,(saved?CHASE.drawPx:34)*metresPerPixel()/4.5)*(playerCar.selected&&!saved?1.3:1);
    const car=new deck.SimpleMeshLayer({
      id:'player-car', data:playerCar.placed?[playerCar]:[], mesh:carMesh, sizeScale:scale,
      getPosition:d=>[d.pos[0],d.pos[1],(d.falling?d.fallZ:d.offEdge?d.airZ:terrainHeightAt(d.pos[0],d.pos[1])+d.jump)+scale*1.2],
      getOrientation:d=>[-d.roll*180/Math.PI,-d.heading*180/Math.PI,d.pitch*180/Math.PI], // deck: [about forward axis, yaw, about side axis]
      getColor:[255,255,255,255], _useMeshColors:true, pickable:true,
      material:{ambient:.55,diffuse:.7,shininess:30,specularColor:[80,80,80]},
      updateTriggers:{getPosition:[playerCar.pos[0],playerCar.pos[1],getRelief(),playerCar.jump,playerCar.falling,playerCar.fallZ,playerCar.airZ,playerCar.offEdge],getOrientation:[playerCar.heading,playerCar.pitch,playerCar.roll]}
    });
    return car;
  }

  function skidLayer() {
    const now=performance.now(), skids=playerCar.skids.filter(k=>now-k.t<2500);
    return new deck.LineLayer({ id:'car-skids', data:skids, getSourcePosition:k=>k.a, getTargetPosition:k=>k.b,
      getColor:k=>[24,24,28,Math.round(80*(1-(now-k.t)/2500))], getWidth:5, widthUnits:'pixels', pickable:false,
      updateTriggers:{getColor:now} });
  }

  const layers=()=>[skidLayer(),layer()];

  function click(info) {
    if(info.object?.kind!=='playerCar') return;
    toggleSelected();
  }

  // Clicking the car and pressing Escape do the same thing: pause driving (back to the overview) or resume it.
  function toggleSelected() {
    if(!playerCar.placed||playerCar.falling) return;
    playerCar.selected=!playerCar.selected; playerCar.speed=0; driveKeys.clear();
    if(playerCar.selected) { pausePlayback(); enterChase(); } else exitChase();
    hintText=''; hint.classList.toggle('active',playerCar.selected);
    setHint(playerCar.selected?HINT_DRIVE:'Paused · click the car or press Esc to resume, or drag the dock icon to a new location');
    refresh();
  }

  function hover(info) {
    if(info.object?.kind!=='playerCar') return false;
    const tip=document.getElementById('tip');
    tip.innerHTML='<b>Terrain car</b>Click to select, then drive with WASD';
    tip.style.display='block'; tip.style.left=Math.min(info.x+14,innerWidth-230)+'px'; tip.style.top=(info.y+14)+'px';
    return true;
  }

  // Third-person chase camera. The terrain is heavily exaggerated, so a ground-level map centre would sit far from the
  // elevated car; instead the camera is placed in 3D (free camera) behind and above the car, smoothed, and kept above the
  // ground. Distance is tied to the reference zoom so the car stays the same size on screen.
  const CHASE={ zoom:10.5, elevation:24*Math.PI/180, follow:7, turn:3, carPx:100, drawPx:55 } // carPx drives interactions; drawPx is only how big the model is drawn;
  let saved=null, rig=null, viewScale=1; // viewScale only moves the camera; car size, speed and jumps stay tied to CHASE.zoom
  const handlers=['dragPan','dragRotate','touchZoomRotate','touchPitch','keyboard','doubleClickZoom','scrollZoom'];
  const chaseMpp=()=>78271.5*Math.cos(playerCar.pos[1]*Math.PI/180)/Math.pow(2,CHASE.zoom);

  function enterChase() {
    saved={ center:map.getCenter(), enabled:handlers.filter(h=>map[h]?.isEnabled()), pitch:map.getPitch(), bearing:map.getBearing(), zoom:map.getZoom(), padding:map.getPadding(), maxPitch:map.getMaxPitch() };
    map.setMaxPitch(85);
    handlers.forEach(h=>map[h]?.disable());
    rig=null; viewScale=1;
  }

  function exitChase(restoreView=false) {
    if(!saved) return;
    saved.enabled.forEach(h=>map[h]?.enable());
    map.setMaxPitch(saved.maxPitch);
    map.jumpTo({ center:restoreView?saved.center:playerCar.pos, zoom:saved.zoom, pitch:saved.pitch, bearing:saved.bearing, padding:saved.padding });
    saved=null; rig=null;
  }

  function chaseCamera(dt) {
    if(!saved) return;
    const c=playerCar, lat=c.pos[1], mpp=chaseMpp(), d=1.5*map.getContainer().clientHeight*mpp*viewScale, k=r=>1-Math.exp(-r*dt);
    const wantH=c.heading;
    if(!rig) rig={ h:wantH };
    rig.h+=(((wantH-rig.h+3*Math.PI)%(2*Math.PI))-Math.PI)*k(CHASE.turn);
    const sin=Math.sin(rig.h), cos=Math.cos(rig.h), back=d*Math.cos(CHASE.elevation), up=d*Math.sin(CHASE.elevation);
    const carZ=c.offEdge?c.airZ:terrainHeightAt(c.pos[0],lat)+c.jump*.2; // camera only partly follows a jump so the car visibly leaves the ground
    const tx=c.pos[0]+sin*d*.45*metresToLon(lat), ty=lat+cos*d*.45*metresToLat;
    let cx=c.pos[0]-sin*back*metresToLon(lat), cy=lat-cos*back*metresToLat;
    let alt=Math.max(carZ+up, terrainHeightAt(cx,cy)+.25*d);
    if(!rig.alt) Object.assign(rig,{x:cx,y:cy,alt,tx,ty,tz:carZ});
    const f=k(CHASE.follow);
    rig.x+=(cx-rig.x)*f; rig.y+=(cy-rig.y)*f; rig.alt+=(alt-rig.alt)*f; rig.tx+=(tx-rig.tx)*f; rig.ty+=(ty-rig.ty)*f; rig.tz+=(carZ-rig.tz)*f;
    // lookAtPoint only takes ground-level points, so extend the camera→target ray down to z=0.
    const s=rig.alt/Math.max(1,rig.alt-rig.tz), gx=rig.x+(rig.tx-rig.x)*s, gy=rig.y+(rig.ty-rig.y)*s;
    // MapLibre has no free camera, so express the 3D camera as centre/zoom/pitch/bearing: centre = where the ray hits z=0.
    const hx=(gx-rig.x)/metresToLon(lat), hy=(gy-rig.y)/metresToLat, horiz=Math.hypot(hx,hy), dist=Math.hypot(horiz,rig.alt);
    const camMpp=dist/(1.5*map.getContainer().clientHeight);
    map.jumpTo({ center:[gx,gy], bearing:Math.atan2(hx,hy)*180/Math.PI, pitch:Math.atan2(horiz,rig.alt)*180/Math.PI,
      zoom:Math.log2(78271.5*Math.cos(gy*Math.PI/180)/camMpp), padding:{top:0,bottom:0,left:0,right:0} });
  }

  function onTerrain(lon,lat) {
    if(terrain.outline && !terrain.outline.some(ring=>{
      let inside=false;
      for(let i=0,j=ring.length-1;i<ring.length;j=i++) {
        const a=ring[i], b=ring[j];
        if((a[1]>lat)!==(b[1]>lat) && lon<(b[0]-a[0])*(lat-a[1])/(b[1]-a[1])+a[0]) inside=!inside;
      }
      return inside;
    })) return false;
    const {x0,y0,step,GZ,NR,NC} = terrain, x=(lon-x0)/step, y=(y0-lat)/step, c=Math.floor(x), r=Math.floor(y);
    if(r<0||c<0||r>=NR-1||c>=NC-1) return false;
    return Number.isFinite(GZ[r*NC+c])&&Number.isFinite(GZ[r*NC+c+1])&&Number.isFinite(GZ[(r+1)*NC+c])&&Number.isFinite(GZ[(r+1)*NC+c+1]);
  }

  const metresToLon=lat=>1/(111320*Math.max(.2,Math.cos(lat*Math.PI/180))), metresToLat=1/111320;

  // Ride the terrain: sample ground under the car's nose/tail/sides, tilt toward that plane, and let a damped spring
  // chase the target so slopes roll in smoothly with a little squat and dive from accel/brake, and bounce on landing.
  function groundTilt(mpp) {
    const c=playerCar, half=17*mpp, wide=half*.45, sin=Math.sin(c.heading), cos=Math.cos(c.heading), lat=c.pos[1];
    const at=(f,s)=>terrainHeightAt(c.pos[0]+(sin*f+cos*s)*metresToLon(lat), lat+(cos*f-sin*s)*metresToLat);
    const rise=(at(half,0)-at(-half,0))/(2*half), lean=(at(0,wide)-at(0,-wide))/(2*wide);
    return { pitch:Math.atan(rise), roll:Math.atan(lean) };
  }

  function updateTilt(dt,mpp,vmax) {
    const c=playerCar, t=groundTilt(mpp), airborne=c.jump>0||c.offEdge;
    const squat=airborne?0:Math.max(-.06,Math.min(.06,c.accel/(vmax/1.5)*.05)); // nose lifts when accelerating, dips when braking
    const target=airborne?{pitch:Math.max(-.35,Math.min(.35,c.jumpV/jumpSpeed(mpp)*.3)),roll:0}:{pitch:t.pitch+squat,roll:t.roll+Math.max(-.3,Math.min(.3,c.slip*.35))};
    const k=70, d=11;
    c.pitchV+=((target.pitch-c.pitch)*k-c.pitchV*d)*dt; c.pitch+=c.pitchV*dt;
    c.rollV+=((target.roll-c.roll)*k-c.rollV*d)*dt; c.roll+=c.rollV*dt;
    c.pitch=Math.max(-1.2,Math.min(1.2,c.pitch)); c.roll=Math.max(-.9,Math.min(.9,c.roll));
  }

  // Speeds are tied to the view: top speed crosses the screen in ~5 s, so the car moves across the map at any zoom.
  // Jumps are sized in screen terms: peak ~JUMP_PX pixels high, ~JUMP_AIR seconds in the air, at any zoom.
  const JUMP_PX=60, JUMP_AIR=.7;
  const jumpGravity=mpp=>8*JUMP_PX*mpp/(JUMP_AIR*JUMP_AIR), jumpSpeed=mpp=>4*JUMP_PX*mpp/JUMP_AIR;
  const CLIMB_DEG=38, SIN_CLIMB=Math.sin(CLIMB_DEG*Math.PI/180); // the normal engine just stalls at this slope; boost climbs steeper

  // Keep an absolute altitude after crossing the edge: outside-grid heights must not snap the car to zero.
  // Hold the camera at the cliff so the fall stays visible, then restore the overview and dock.
  function fallStep(dt) {
    const c=playerCar;
    c.fallTime+=dt;
    c.pos[0]+=Math.sin(c.heading)*c.speed*dt*metresToLon(c.pos[1]);
    c.pos[1]+=Math.cos(c.heading)*c.speed*dt*metresToLat;
    c.fallZ+=c.fallV*dt-.5*c.fallGravity*dt*dt;
    c.fallV-=c.fallGravity*dt;
    c.speed*=Math.exp(-.2*dt);
    c.pitch-=.9*dt; c.roll+=.6*dt;
    if(c.fallTime>=2.6) reset();
  }

  // Lowest point of the platform: once an airborne car sinks below this it can no longer get back on.
  let minGZ=Infinity;
  for(let i=0;i<terrain.GZ.length;i++) { const z=terrain.GZ[i]; if(Number.isFinite(z)&&z<minGZ) minGZ=z; }
  const minPlatformZ=()=>(Number.isFinite(minGZ)?minGZ:0)*terrain.getExaggeration();

  function startFall(mpp) {
    const c=playerCar;
    c.falling=true; c.fallZ=c.airZ; c.fallV=c.airV; c.fallTime=0; c.fallGravity=Math.max(900,mpp*50);
    c.offEdge=false; c.stalled=false; driveKeys.clear();
    setHint('Off the edge! Returning the car to its dock…');
  }

  function physicsStep(dt, input, mpp, vmax0) {
    if(playerCar.falling) { fallStep(dt); return; }
    const boost=input.boost&&input.throttle, vmax=vmax0*(boost?4:1); // Shift: higher top speed and a much harder push
    const c=playerCar, engine=vmax0/1.5*(boost?7:1), sin=Math.sin(c.heading), cos=Math.cos(c.heading);
    // Hill mechanics, built on a few standard vehicle-game rules:
    //  - Slope is read over the car's wheelbase (half a car length either side) and low-passed, so rough cells never jolt it.
    //  - Gravity is a real force along the slope (sin of the angle) set so the normal engine just stalls at CLIMB_DEG.
    //    Climbing therefore costs speed smoothly, and momentum carries you: arriving fast gets you up further than creeping.
    //  - Boost multiplies engine force but not gravity, so it is the answer to a steep face.
    //  - No hard wall: on a face the engine cannot hold the car just runs out of speed, then rolls back slowly (capped), and
    //    reversing out or turning always works. A gentler slope the car can hold stays parked when you let go.
    const span=Math.max(150,.5*CHASE.carPx*mpp), dLon=sin*span*metresToLon(c.pos[1]), dLat=cos*span*metresToLat;
    const raw=(terrainHeightAt(c.pos[0]+dLon,c.pos[1]+dLat)-terrainHeightAt(c.pos[0]-dLon,c.pos[1]-dLat))/(2*span);
    c.grade+=(raw-c.grade)*(1-Math.exp(-8*dt));
    const grade=c.grade, airborne=c.jump>0||c.offEdge;
    const sinTheta=grade/Math.hypot(1,grade), baseEngine=vmax0/1.5, G=baseEngine/SIN_CLIMB; // gravity scale: engine == G·sin(θ) at CLIMB_DEG
    const pull=G*sinTheta;                                          // along-heading gravity (positive = holding you back when facing uphill)
    let a=0;
    if(!airborne) {
      if(input.throttle) a+=engine*Math.max(-1,1-Math.max(0,c.speed)/vmax);
      if(input.brake) a+=c.speed>.02*vmax ? -baseEngine*2.2 : -baseEngine*1.1; // brake, then reverse
      if(!input.throttle) a-=c.speed*.35+Math.sign(c.speed)*baseEngine*.12;   // coasting: rolling resistance plus a little friction
      a-=pull;
    }
    c.accel=a;
    let v=c.speed+a*dt;
    const cantHold=pull>=baseEngine*.98;                              // even full normal throttle can't push up this
    c.stalled=!airborne&&input.throttle&&!boost&&cantHold&&v<.05*vmax;
    if(!airborne&&cantHold&&v<0&&(input.throttle||input.brake)) v=Math.max(v,-.12*vmax); // rolls back, but never runs away
    if(!input.throttle&&!input.brake&&Math.abs(v)<.01*vmax&&Math.abs(sinTheta)<SIN_CLIMB*.55) v=0; // parked on a slope it can hold
    c.speed=Math.max(-.4*vmax,Math.min(vmax*1.15,v));
    // Steering: yaw rate follows speed (no turning on the spot), limited by lateral grip; reversing flips it like a real car.
    const radius=60*mpp, grip=Math.PI*.55, rate=Math.max(-1.6,Math.min(1.6,c.speed/radius))*input.steer*(1+2*c.wet);
    c.heading=((c.heading+Math.max(-grip,Math.min(grip,rate))*dt)%(Math.PI*2)+Math.PI*2)%(Math.PI*2);
    // Carry momentum over the edge and fall before returning to the dock.
    // Wet tyres (in a flowing river, drying over a few seconds) lose grip: the car keeps travelling along its old course
    // while the nose swings round, so it drifts. Dry, the course follows the heading exactly.
    const soak=isWet&&c.jump===0 ? Math.max(0,Math.min(1,+isWet(c.pos[0],c.pos[1])||0)) : 0; // 0 dry … 1 flowing river
    c.wet=soak>c.wet ? Math.min(soak,c.wet+dt*4) : Math.max(0,c.wet-dt/2.5);
    const gripRate=c.wet>.02 ? (.3+Math.pow(1-c.wet,2)*14)+Math.max(0,1-Math.abs(c.speed)/(.12*vmax))*30 : Infinity;
    if(gripRate===Infinity) { c.course=c.heading; c.slip=0; }
    else {
      const slip=((c.heading-c.course+3*Math.PI)%(2*Math.PI))-Math.PI;
      c.course+=slip*(1-Math.exp(-gripRate*dt));
      c.speed*=Math.exp(-dt*.35*Math.min(1,Math.abs(slip)));
      const s2=Math.max(-1.15,Math.min(1.15,((c.heading-c.course+3*Math.PI)%(2*Math.PI))-Math.PI)); c.course=c.heading-s2; c.slip=s2; // slide angle capped near 57°
    }
    const dist=c.speed*dt, nLon=Math.sin(c.course)*dist*metresToLon(c.pos[1]), nLat=Math.cos(c.course)*dist*metresToLat;
    const nextOn=onTerrain(c.pos[0]+nLon,c.pos[1]+nLat);
    if(!nextOn&&!c.offEdge) { // leaving the platform: carry on as a projectile from the current altitude
      c.offEdge=true; c.airZ=terrainHeightAt(c.pos[0],c.pos[1])+c.jump; c.airV=c.jumpV; c.jump=0; c.jumpV=0; c.lastSkid=null;
    }
    if(c.offEdge) {
      c.airV-=jumpGravity(mpp)*dt; c.airZ+=c.airV*dt;
      if(nextOn) {
        const ground=terrainHeightAt(c.pos[0]+nLon,c.pos[1]+nLat);
        if(c.airZ>=ground) { c.offEdge=false; c.jump=c.airZ-ground; c.jumpV=c.airV; } // back over the platform: land or keep flying
        else { startFall(mpp); fallStep(dt); return; }                                  // came back in below the surface: hit the cliff
      } else if(c.airZ<minPlatformZ()) { startFall(mpp); fallStep(dt); return; }        // dropped below the platform's lowest point
    }
    c.pos[0]+=nLon; c.pos[1]+=nLat;
    // Skid marks: two rear-wheel tracks laid down while the car is visibly sliding.
    if(Math.abs(c.slip)>.18&&c.jump===0&&!c.offEdge&&Math.abs(c.speed)>.05*vmax) {
      const L=CHASE.drawPx*mpp, lat=c.pos[1], hs=Math.sin(c.heading), hc=Math.cos(c.heading), now=performance.now();
      const wheel=side=>{ const f=-.3*L, s2=side*.2*L;
        const lon2=c.pos[0]+(hs*f+hc*s2)*metresToLon(lat), lat2=lat+(hc*f-hs*s2)*metresToLat;
        return [lon2,lat2,terrainHeightAt(lon2,lat2)+L*.02]; };
      const pts=[wheel(-1),wheel(1)];
      if(c.lastSkid&&now-c.lastSkid.t<250) for(let i=0;i<2;i++) c.skids.push({a:c.lastSkid.p[i],b:pts[i],t:now});
      c.lastSkid={p:pts,t:now};
      if(c.skids.length>400) c.skids.splice(0,c.skids.length-400);
    } else c.lastSkid=null;
    updateTilt(dt,mpp,vmax);
    if(c.jumpV||c.jump) {
      c.jumpV-=jumpGravity(mpp)*dt; c.jump=Math.max(0,c.jump+c.jumpV*dt);
      if(c.jump===0) c.jumpV=0;
    }
  }

  const HINT_DRIVE='Driving · W drive · A/D steer · S brake · Space jump · Q/E relief · Shift boost · Esc pause';
  let hintText='';
  function updateHint() {
    const deg=Math.round(Math.atan(playerCar.grade)*180/Math.PI);
    const text=playerCar.stalled?`Too steep (${deg}°) · hold Shift to boost, or reverse out`:Math.abs(deg)>=3?`${HINT_DRIVE} · slope ${deg>0?'+':''}${deg}°`:HINT_DRIVE;
    if(text!==hintText) { hintText=text; setHint(text); }
  }

  function tick(dt) {
    if(!playerCar.selected) return false;
    dt=Math.min(.05,dt);
    const c=playerCar, old=[c.pos[0],c.pos[1],c.heading,c.speed,c.jump,c.pitch,c.roll];
    const mpp=metresPerPixel(), vmax=map.getContainer().clientWidth*mpp/3.3;
    const input={throttle:driveKeys.has('KeyW'), brake:driveKeys.has('KeyS'), steer:(driveKeys.has('KeyD')?1:0)-(driveKeys.has('KeyA')?1:0), boost:driveKeys.has('ShiftLeft')||driveKeys.has('ShiftRight')};
    const n=Math.ceil(dt/(1/120)); // fixed small substeps keep the result independent of frame rate
    for(let i=0;i<n&&c.selected;i++) physicsStep(dt/n,input,mpp,vmax);
    if(c.selected&&!c.falling) { chaseCamera(dt); updateHint(); }
    if(c.falling||!c.placed) return true;
    return Math.abs(c.pos[0]-old[0])+Math.abs(c.pos[1]-old[1])>0||c.heading!==old[2]||Math.abs(c.pitch-old[5])+Math.abs(c.roll-old[6])>1e-5||c.speed!==old[3]||c.jump!==old[4];
  }

  function keydown(e) {
    if(e.code==='Escape') { if(playerCar.falling) { reset(); return; } cancelDrag(); if(choosing) { choosing=false; dock.classList.remove('choosing'); setHint(''); refresh(); } else if(playerCar.placed&&!e.repeat) toggleSelected(); return; }
    if(!playerCar.selected||playerCar.falling||!driveCodes.has(e.code)||e.target.matches?.('input,button,a')) return;
    e.preventDefault();
    if(e.code==='KeyQ'||e.code==='KeyE') { if(!e.repeat) setRelief(e.code==='KeyE'?.1:-.1); }
    else if(e.code==='Space') { if(!e.repeat&&playerCar.jump===0&&!playerCar.offEdge) playerCar.jumpV=jumpSpeed(metresPerPixel()); }
    else driveKeys.add(e.code);
  }
  // Mouse wheel zooms the chase camera (towns appear/disappear with the map zoom); the car itself is unaffected.
  map.getContainer().addEventListener('wheel',e=>{
    if(!saved) return;
    e.preventDefault();
    viewScale=Math.min(8,Math.max(.2,viewScale*Math.exp(e.deltaY*.0015)));
  },{passive:false});
  addEventListener('keydown',keydown);
  addEventListener('keyup',e=>driveKeys.delete(e.code));
  addEventListener('blur',()=>driveKeys.clear());

  function start(redraw) {
    let zoomQueued=false;
    map.on('zoom',()=>{ if(zoomQueued) return; zoomQueued=true; requestAnimationFrame(()=>{ zoomQueued=false; redraw(); }); });
    let last=performance.now();
    function frame(now) {
      const dt=Math.min(.05,(now-last)/1000); last=now;
      if(playerCar.selected&&tick(dt)) redraw();
      requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  }

  return { layer, layers, click, hover, start, tick, state: playerCar, driveKeys, place, reset, isPlacing:()=>!!dragging||choosing };
};
