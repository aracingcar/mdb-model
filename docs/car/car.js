/* MDB Model's selectable terrain car. This file is copied into docs/car for GitHub Pages. */
window.createCarMechanics = function ({ deck, map, terrain, getRelief, setRelief, refresh, pickTerrain, isWet, playWhileDriving, getRivers, conditionsAt }) {
  const playerCar = { kind:'playerCar', pos:[0,0], placed:false, heading:0, speed:0, vel:[0,0], yawRate:0, steer:0, spin:false, nitro:1, nitroWait:0, nitroLocked:false, boosting:false, selected:false, jump:0, jumpV:0, pitch:0, roll:0, pitchV:0, rollV:0, accel:0, grade:0, bank:0, stalled:false, wet:0, slip:0, skids:[], offEdge:false, airZ:0, airV:0, falling:false, fallZ:0, fallV:0, fallTime:0, fallGravity:0 };
  const driveKeys = new Set(), driveCodes = new Set(['KeyW','KeyA','KeyS','KeyD','KeyQ','KeyE','Space','ShiftLeft','ShiftRight']);
  const ARROWS = { ArrowUp:'KeyW', ArrowLeft:'KeyA', ArrowDown:'KeyS', ArrowRight:'KeyD' }; // arrows drive exactly like WASD
  const driveCode = code => ARROWS[code] || code;
  // Keys typed into a text box stay there; anything else (play button, sliders, dropdowns) gives them to the car while driving.
  const typing = el => el?.matches?.('textarea,input:not([type=range]):not([type=checkbox]):not([type=radio]):not([type=button])');
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
  const detailToggle = document.getElementById('detail-toggle');
  if (detailToggle) tools.append(detailToggle);
  const sdlToggle = document.getElementById('sdl-toggle');
  if (sdlToggle) tools.append(sdlToggle);
  document.body.append(tools);
  const ghost = document.createElement('div');
  ghost.className = 'car-drag-ghost'; ghost.textContent = '🚗'; ghost.hidden = true;
  ghost.setAttribute('aria-hidden','true'); document.body.append(ghost);
  let dragging = null, choosing = false, suppressClick = false;

  function setHint(text) { hint.textContent = text; hint.hidden = !text; }
  function place(pos) {
    if (!pos || !onTerrain(pos[0],pos[1])) return false;
    exitChase();
    Object.assign(playerCar,{pos:pos.slice(0,2),placed:true,selected:true,heading:0,speed:0,vel:[0,0],yawRate:0,steer:0,spin:false,nitro:1,nitroWait:0,nitroLocked:false,boosting:false,jump:0,jumpV:0,pitch:0,roll:0,pitchV:0,rollV:0,accel:0,grade:0,bank:0,stalled:false,wet:0,slip:0,skids:[],lastSkid:null,offEdge:false,airZ:0,airV:0,falling:false,fallZ:0,fallV:0,fallTime:0,fallGravity:0}); hintText='';
    driveKeys.clear(); choosing = false; dock.classList.remove('choosing'); hideGhost();
    dock.classList.add('placed'); dock.blur();
    enterChase(); playWhileDriving?.(); // the climate scenario plays on while you drive
    hint.classList.add('active');
    setHint(HINT_DRIVE);
    refresh(); return true;
  }
  function reset() {
    exitChase(true);
    Object.assign(playerCar,{placed:false,selected:false,speed:0,vel:[0,0],yawRate:0,steer:0,spin:false,jump:0,jumpV:0,pitch:0,roll:0,pitchV:0,rollV:0,accel:0,grade:0,bank:0,stalled:false,wet:0,slip:0,skids:[],lastSkid:null,offEdge:false,airZ:0,airV:0,falling:false,fallZ:0,fallV:0,fallTime:0,fallGravity:0}); hintText='';
    driveKeys.clear(); choosing=false; endRain(); drawRadar(); drawHud();
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
    // Only within SNAP_PX of the cursor, so the green/red outline honestly says whether the car will land.
    const g=map.unproject([x,y]), g2=map.unproject([x+SNAP_PX,y]);
    return g?nearestTerrain(g.lng,g.lat,Math.ceil(Math.hypot(g2.lng-g.lng,g2.lat-g.lat)/terrain.step)):null;
  }
  const SNAP_PX=40;
  function nearestTerrain(lon,lat,reach=150) {
    const {x0,y0,step}=terrain, c0=Math.round((lon-x0)/step), r0=Math.round((y0-lat)/step);
    for(let k=0;k<=Math.min(150,reach);k++) for(let dr=-k;dr<=k;dr++) {
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
    showGhost(e);
  });
  // The ghost car follows the cursor while dragging or choosing; its outline (and the dock's) is green where it will drop, red where not.
  function showGhost(e) {
    const pos=dropPosition(e), ok=!!pos&&onTerrain(pos[0],pos[1]);
    ghost.hidden=false; ghost.style.left=e.clientX+'px'; ghost.style.top=e.clientY+'px';
    ghost.classList.toggle('valid',ok);
    dock.classList.toggle('drop-ok',ok); dock.classList.toggle('drop-no',!ok);
  }
  function hideGhost() { ghost.hidden=true; dock.classList.remove('drop-ok','drop-no'); }
  map.getContainer().addEventListener('pointermove',e=>{ if(choosing&&!dragging) showGhost(e); });
  map.getContainer().addEventListener('pointerleave',()=>{ if(choosing&&!dragging) hideGhost(); });
  function cancelDrag() { dragging=null; hideGhost(); refresh(); }
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
    choosing=!choosing; dock.classList.toggle('choosing',choosing); if(!choosing) hideGhost();
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
    // Fixed real-world size, so the car is the same size selected or not; the floor only keeps it findable when zoomed far out.
    const viewMpp=78271.5*Math.cos(playerCar.pos[1]*Math.PI/180)/Math.pow(2,map.getZoom());
    const scale=Math.max(1,CHASE.drawPx*chaseMpp()/4.5, saved?0:9*viewMpp/4.5);
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
    playerCar.selected=!playerCar.selected; Object.assign(playerCar,{speed:0,vel:[0,0],yawRate:0}); driveKeys.clear();
    if(playerCar.selected) enterChase(); else { exitChase(); endRain(); drawRadar(); drawHud(); }
    hintText=''; hint.classList.toggle('active',playerCar.selected);
    setHint(playerCar.selected?HINT_DRIVE:'Driving paused · click the car or press Esc to resume, or drag the dock icon to a new location');
    refresh();
  }

  function hover(info) {
    if(info.object?.kind!=='playerCar') return false;
    const tip=document.getElementById('tip');
    tip.innerHTML='<b>Terrain car</b>Click to select, then drive with WASD or the arrow keys';
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
    document.body.classList.add('car-driving'); map.resize?.(); // the page hides its side panel and gives the map the width
    map.setMaxPitch(85);
    handlers.forEach(h=>map[h]?.disable());
    rig=null; viewScale=1;
  }

  function exitChase(restoreView=false) {
    if(!saved) return;
    saved.enabled.forEach(h=>map[h]?.enable());
    document.body.classList.remove('car-driving'); map.resize?.();
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

  function updateTilt(dt,mpp) {
    const c=playerCar, t=groundTilt(mpp), airborne=c.jump>0||c.offEdge;
    const squat=airborne?0:Math.max(-.06,Math.min(.06,c.accel/CAR.gravity*.05)); // nose lifts when accelerating, dips when braking
    const target=airborne?{pitch:Math.max(-.35,Math.min(.35,c.jumpV/jumpSpeed(mpp)*.3)),roll:0}:{pitch:t.pitch+squat,roll:t.roll+Math.max(-.3,Math.min(.3,c.slip*.35))};
    const k=70, d=11;
    c.pitchV+=((target.pitch-c.pitch)*k-c.pitchV*d)*dt; c.pitch+=c.pitchV*dt;
    c.rollV+=((target.roll-c.roll)*k-c.rollV*d)*dt; c.roll+=c.rollV*dt;
    c.pitch=Math.max(-1.2,Math.min(1.2,c.pitch)); c.roll=Math.max(-.9,Math.min(.9,c.roll));
  }

  // Jumps are sized in screen terms: peak ~JUMP_PX pixels high, ~JUMP_AIR seconds in the air, at any zoom.
  const JUMP_PX=60, JUMP_AIR=.7;
  const jumpGravity=mpp=>8*JUMP_PX*mpp/(JUMP_AIR*JUMP_AIR), jumpSpeed=mpp=>4*JUMP_PX*mpp/JUMP_AIR;
  const CLIMB_DEG=22, SIN_CLIMB=Math.sin(CLIMB_DEG*Math.PI/180); // the normal engine just stalls at this slope; boost climbs steeper

  // Driving model: Marco Monster's "Car Physics for Games" (2003), as adapted to JavaScript by Mike Linkovich in carphysics2d
  // (https://github.com/spacejack/carphysics2d, MIT licence, copyright (c) 2015 Mike Linkovich; see car/LICENSE-carphysics2d).
  // CAR is that project's default "lightweight sports sedan" config, except airResist: raised from 2.5 so the top speed is
  // ~25 m/s (90 km/h) instead of ~57, which on this map was too fast to steer. The car is simulated in its own real-size
  // metres and drawn carScale() times larger on the map, so it handles like a 4 m car whatever the map scale.
  const CAR={ gravity:9.81, mass:1200, inertiaScale:1, cgToFrontAxle:1.25, cgToRearAxle:1.25, cgHeight:.55, length:4,
    tireGrip:2, lockGrip:.7, engineForce:8000, brakeForce:12000, weightTransfer:.2, maxSteer:.6,
    cornerStiffnessFront:5, cornerStiffnessRear:5.2, airResist:12.8, rollResist:8 };
  const WHEELBASE=CAR.cgToFrontAxle+CAR.cgToRearAxle, INERTIA=CAR.mass*CAR.inertiaScale;
  const carScale=()=>CHASE.drawPx*chaseMpp()/CAR.length; // map metres per car metre
  // Game additions on top of the source model:
  //  - Traction control on normal throttle: drive is held inside what the rear tyres can take, so plain driving never
  //    spins the wheels, even wet. Boost (Shift) switches it off.
  //  - Boost is extra engine force through the rear tyres plus, once rolling, a rocket push on the body for top speed (~2x).
  //    The wheel part is sized so dry tyres just hold it but wet ones spin up: that wheelspin is what makes donuts.
  //  - Wet tyres (river, rain) lose up to WET_LOSS of their grip.
  //  - Hills: gravity along and across the slope, scaled (HILL_G) so the normal engine just stalls at CLIMB_DEG.
  const BOOST_WHEEL=1.25, BOOST_ROCKET=3, WET_LOSS=.6, STEER_ASSIST=.7, WHEELSPIN=12, HILL_G=CAR.engineForce/(CAR.mass*SIN_CLIMB);
  const TOP_SPEED=Math.sqrt(CAR.engineForce/CAR.airResist); // ~25 m/s (90 km/h) unboosted on the flat
  const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));

  // Keep an absolute altitude after crossing the edge: outside-grid heights must not snap the car to zero.
  // Hold the camera at the cliff so the fall stays visible, then restore the overview and dock.
  function fallStep(dt) {
    const c=playerCar;
    c.fallTime+=dt;
    const S=carScale();
    c.pos[0]+=c.vel[0]*S*dt*metresToLon(c.pos[1]);
    c.pos[1]+=c.vel[1]*S*dt*metresToLat;
    c.fallZ+=c.fallV*dt-.5*c.fallGravity*dt*dt;
    c.fallV-=c.fallGravity*dt;
    c.vel=c.vel.map(v=>v*Math.exp(-.2*dt));
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

  function physicsStep(dt, input, mpp) {
    if(playerCar.falling) { fallStep(dt); return; }
    const c=playerCar, P=CAR, sin=Math.sin(c.heading), cos=Math.cos(c.heading);
    // Steering filter, from the source's applySmoothSteer: the wheel turns at 2/s and recentres at 1/s. Its applySafeSteer
    // (less lock at speed, "prevents oversteer at expense of more understeer") is made grip-aware here: the lock is held to
    // what a steady turn needs for STEER_ASSIST of the tyres' grip (bicycle model: tan δ = a_lat·L / v²), so the car corners
    // hard without snapping round. Boosting on wet tyres spins the rear wheels, so the tail still comes round: donuts.
    c.steer=input.steer ? clamp(c.steer+input.steer*dt*2,-1,1) : c.steer>0 ? Math.max(c.steer-dt,0) : Math.min(c.steer+dt,0);
    const absVel=Math.hypot(c.vel[0],c.vel[1]), grip=P.tireGrip*(1-WET_LOSS*c.wet);
    const lock=Math.min(P.maxSteer*(1-Math.min(absVel,250)/280), Math.atan(STEER_ASSIST*grip*P.gravity*WHEELBASE/Math.max(1e-6,absVel*absVel)));
    const steerAngle=c.steer*lock;
    // Velocity in car coordinates: x forward, y to the right (heading is clockwise from north, as is yawRate).
    const vx=sin*c.vel[0]+cos*c.vel[1], vy=cos*c.vel[0]-sin*c.vel[1];
    // Slope under the car, read over a span wider than any one terrain cell and low-passed, along and across the heading.
    const span=Math.max(150,.5*CHASE.carPx*mpp), lat=c.pos[1], at=(f,r)=>terrainHeightAt(c.pos[0]+(sin*f+cos*r)*metresToLon(lat), lat+(cos*f-sin*r)*metresToLat);
    const ease=1-Math.exp(-8*dt);
    c.grade+=((at(span,0)-at(-span,0))/(2*span)-c.grade)*ease;
    c.bank+=((at(0,span)-at(0,-span))/(2*span)-c.bank)*ease;
    const sinTheta=c.grade/Math.hypot(1,c.grade), sinBank=c.bank/Math.hypot(1,c.bank);
    const airborne=c.jump>0||c.offEdge, boost=input.boost&&input.throttle;
    // Wet tyres: soaked in a flowing river or by rain, drying over a few seconds.
    const soak=c.jump===0 ? Math.max(rain.level,isWet?clamp(+isWet(c.pos[0],c.pos[1])||0,0,1):0) : 0; // 0 dry … 1 flowing river
    c.wet=soak>c.wet ? Math.min(soak,c.wet+dt*4) : Math.max(0,c.wet-dt/2.5);
    let Fx=0, Fy=0, torque=0, spin=false, reversing=false;
    // Drag acts in the air too (source: rolling resistance + air resistance, per axis).
    Fx-=P.rollResist*vx+P.airResist*vx*Math.abs(vx);
    Fy-=P.rollResist*vy+P.airResist*vy*Math.abs(vy);
    if(!airborne) {
      // Axle loads, with weight shifting back under acceleration and forward under braking (source).
      const shift=P.weightTransfer*c.accel*P.cgHeight/WHEELBASE;
      const wFront=P.mass*(P.cgToRearAxle/WHEELBASE*P.gravity-shift), wRear=P.mass*(P.cgToFrontAxle/WHEELBASE*P.gravity+shift);
      // Slip angles: wheel velocity includes the body's rotation (source). The front angle is measured in the turned wheel's
      // own frame. The source's shortcut, atan2(v_lat,|v_x|) - sign(v_x)·δ, is the same for small angles but flips the
      // steering when v_x crosses zero, which is exactly what happens mid-donut with the car sliding sideways.
      const sgn=vx>0?1:vx<0?-1:0, vyFront=vy+P.cgToFrontAxle*c.yawRate, cd=Math.cos(steerAngle), sd=Math.sin(steerAngle);
      const slipFront=Math.atan2(vyFront*cd-vx*sd,Math.abs(vx*cd+vyFront*sd));
      const slipRear=Math.atan2(vy-P.cgToRearAxle*c.yawRate,Math.abs(vx));
      const latFront=clamp(-P.cornerStiffnessFront*slipFront,-grip,grip)*wFront;
      let latRear=clamp(-P.cornerStiffnessRear*slipRear,-grip,grip)*wRear;
      // Rear-wheel drive (source). Brake, then reverse once (almost) stopped.
      const uphill=Math.min(1,Math.max(0,sinTheta)/SIN_CLIMB);
      let drive=0, brake=0;
      if(input.throttle) drive=P.engineForce*(boost?BOOST_WHEEL:1);
      if(input.brake) { if(vx>1) brake=P.brakeForce; else if(!input.throttle) { drive=-.6*P.engineForce; reversing=true; } }
      // Traction circle on the driven (rear) tyres (Beckman, "The Physics of Racing", part 5): drive and cornering share one
      // grip budget. Ask for more and the wheels spin. A spinning tyre slides, so it gives sliding grip (the source's
      // lockGrip) directed against its contact patch's slip: the tread running WHEELSPIN m/s ahead of the ground, plus however
      // fast the axle slides sideways. Mostly drive, with sideways hold growing as the tail slides: on wet tyres, boost and
      // full lock swing the tail round and hold it there, a donut.
      const budget=grip*wRear;
      if(drive&&!boost) drive=Math.sign(drive)*Math.min(Math.abs(drive),.98*Math.sqrt(Math.max(0,budget*budget-latRear*latRear))); // traction control
      const demand=Math.hypot(drive,latRear);
      if(drive&&demand>budget) {
        const slideRear=vy-P.cgToRearAxle*c.yawRate, ahead=Math.sign(drive)*WHEELSPIN, k=P.lockGrip*budget/Math.hypot(ahead,slideRear);
        drive=ahead*k; latRear=-slideRear*k; spin=true;
      }
      Fx+=drive-brake*sgn;
      Fy+=Math.cos(steerAngle)*latFront+latRear;
      torque=latFront*P.cgToFrontAxle-latRear*P.cgToRearAxle;
      // Gravity along and across the slope (game addition).
      Fx-=P.mass*HILL_G*sinTheta; Fy-=P.mass*HILL_G*sinBank;
      // Boost rocket: only above 15 m/s (full by 30) so it never breaks a donut, and fades on climbs so it cannot fly up cliffs.
      if(boost) Fx+=P.engineForce*BOOST_ROCKET*clamp((vx-15)/15,0,1)*(1-.85*uphill);
      c.stalled=input.throttle&&P.mass*HILL_G*sinTheta>=P.engineForce*(boost?BOOST_WHEEL:1)*.98&&vx<1;
    } else c.stalled=false;
    c.spin=spin;
    const ax=Fx/P.mass, ay=Fy/P.mass;
    c.accel=ax;
    c.vel[0]+=(ax*sin+ay*cos)*dt; c.vel[1]+=(ax*cos-ay*sin)*dt;
    c.yawRate+=torque/INERTIA*dt;
    // The source stops the car outright when slow and coasting (the tyre model is unstable near zero). Here that also
    // parks it on any slope gentle enough to hold; steeper, it keeps rolling back.
    const speedNow=Math.hypot(c.vel[0],c.vel[1]);
    if(!airborne&&speedNow<.5&&!input.throttle&&!reversing&&Math.abs(sinTheta)<SIN_CLIMB*.55&&Math.abs(sinBank)<SIN_CLIMB*.55) { c.vel=[0,0]; c.yawRate=0; }
    c.heading=((c.heading+c.yawRate*dt)%(Math.PI*2)+Math.PI*2)%(Math.PI*2);
    // Steep faces: traction caps speed up them, falling to zero at ~1.6x the normal climb limit, however fast the car arrives;
    // a car held there rolls back no faster than 3 m/s while you work the pedals (game addition).
    const s2=Math.sin(c.heading), c2=Math.cos(c.heading);
    let fwd=s2*c.vel[0]+c2*c.vel[1];
    const dirSin=(fwd>=0?1:-1)*sinTheta;
    if(!airborne&&dirSin>0) {
      const cap=TOP_SPEED*Math.max(0,1-dirSin/(1.6*SIN_CLIMB));
      if(Math.abs(fwd)>cap) { const cut=Math.sign(fwd)*(Math.abs(fwd)-cap)*ease; c.vel[0]-=s2*cut; c.vel[1]-=c2*cut; fwd-=cut; }
    }
    if(!airborne&&fwd<-3&&c.stalled) { const cut=fwd+3; c.vel[0]-=s2*cut; c.vel[1]-=c2*cut; fwd=-3; }
    c.speed=fwd;
    const side=c2*c.vel[0]-s2*c.vel[1];
    c.slip=Math.hypot(fwd,side)>1 ? -Math.atan2(side,Math.abs(fwd)) : 0; // nose angle off the direction of travel, + when sliding left
    const S=carScale(), nLon=c.vel[0]*S*dt*metresToLon(c.pos[1]), nLat=c.vel[1]*S*dt*metresToLat;
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
    // Skid marks: two rear-wheel tracks laid down while the car is visibly sliding or spinning its wheels.
    if((Math.abs(c.slip)>.18||c.spin)&&c.jump===0&&!c.offEdge&&Math.hypot(c.vel[0],c.vel[1])>1) {
      const L=CHASE.drawPx*mpp, lat=c.pos[1], hs=Math.sin(c.heading), hc=Math.cos(c.heading), now=performance.now();
      const wheel=side=>{ const f=-.3*L, s2=side*.2*L;
        const lon2=c.pos[0]+(hs*f+hc*s2)*metresToLon(lat), lat2=lat+(hc*f-hs*s2)*metresToLat;
        return [lon2,lat2,terrainHeightAt(lon2,lat2)+L*.02]; };
      const pts=[wheel(-1),wheel(1)];
      if(c.lastSkid&&now-c.lastSkid.t<250) for(let i=0;i<2;i++) c.skids.push({a:c.lastSkid.p[i],b:pts[i],t:now});
      c.lastSkid={p:pts,t:now};
      if(c.skids.length>400) c.skids.splice(0,c.skids.length-400);
    } else c.lastSkid=null;
    updateTilt(dt,mpp);
    if(c.jumpV||c.jump) {
      c.jumpV-=jumpGravity(mpp)*dt; c.jump=Math.max(0,c.jump+c.jumpV*dt);
      if(c.jump===0) c.jumpV=0;
    }
  }

  // Random rain showers while driving: every 10-35 s of driving a shower of 5-12 s builds up, wets the tyres anywhere on the
  // map (like a rain cloud, less than a river) so the car drifts, then clears. A streak overlay shows it on screen.
  const rain={level:0, peak:0, left:0, wait:8+Math.random()*20};
  const rainVeil=document.createElement('div');
  rainVeil.className='car-rain'; rainVeil.hidden=true; rainVeil.setAttribute('aria-hidden','true');
  document.body.append(rainVeil);
  function rainStep(dt) {
    if(rain.left>0) rain.left=Math.max(0,rain.left-dt);
    else if((rain.wait-=dt)<=0) { rain.left=5+Math.random()*7; rain.peak=.35+Math.random()*.3; rain.wait=10+Math.random()*25; }
    const want=rain.left>0?rain.peak:0;
    rain.level+=(want-rain.level)*(1-Math.exp(-(want>rain.level?1.5:.8)*dt)); // showers build in and ease off
    if(rain.level<.01&&!want) rain.level=0;
    rainVeil.hidden=rain.level===0; rainVeil.style.opacity=Math.min(1,rain.level/.5).toFixed(2);
  }
  function endRain() { Object.assign(rain,{level:0,left:0}); rainVeil.hidden=true; }

  // GTA-style radar, bottom right while driving: heading-up, centred on the car, over a shaded height map of the whole terrain
  // with its rivers. The base image is drawn once per terrain grid (it changes when a system's detail loads).
  const radar=document.createElement('canvas'); radar.className='car-radar'; radar.hidden=true; radar.setAttribute('aria-hidden','true');
  document.body.append(radar);
  let radarBase=null, radarKey=null;
  function radarImage() {
    const rivers=getRivers?.()||[], key=[terrain.GZ,terrain.NC,rivers.length];
    if(radarBase&&radarKey.every((v,i)=>v===key[i])) return radarBase;
    const {x0,y0,step,GZ,NR,NC}=terrain, aspect=Math.cos((y0-NR*step/2)*Math.PI/180), k=Math.min(1,700/Math.max(NC*aspect,NR));
    const W=Math.round(NC*aspect*k), H=Math.round(NR*k), cv=document.createElement('canvas'); cv.width=W; cv.height=H;
    const g=cv.getContext('2d'), img=g.createImageData(W,H);
    let lo=Infinity, hi=-Infinity; for(let i=0;i<GZ.length;i++) { const z=GZ[i]; if(Number.isFinite(z)) { if(z<lo) lo=z; if(z>hi) hi=z; } }
    const zAt=(r,c)=>GZ[Math.max(0,Math.min(NR-1,r))*NC+Math.max(0,Math.min(NC-1,c))];
    for(let y=0;y<H;y++) for(let x=0;x<W;x++) {
      const r=Math.floor(y/k), c=Math.floor(x/k/aspect), z=zAt(r,c), o=(y*W+x)*4;
      if(!Number.isFinite(z)) continue;
      const t=Math.sqrt((z-lo)/Math.max(1,hi-lo)), dz=zAt(r,c+1)-zAt(r,c-1)-(zAt(r+1,c)-zAt(r-1,c)), shade=1+Math.max(-.25,Math.min(.25,(Number.isFinite(dz)?dz:0)*.004));
      img.data[o]=(236-60*t)*shade; img.data[o+1]=(224-80*t)*shade; img.data[o+2]=(200-100*t)*shade; img.data[o+3]=255;
    }
    g.putImageData(img,0,0);
    g.fillStyle='#3d7fbf';
    for(const ring of rivers) { g.beginPath(); ring.forEach((p,i)=>g[i?'lineTo':'moveTo']((p[0]-x0)/step*aspect*k,(y0-p[1])/step*k)); g.fill(); }
    radarBase={cv,toPx:(lon,lat)=>[(lon-x0)/step*aspect*k,(y0-lat)/step*k],span:Math.max(W,H)}; radarKey=key;
    return radarBase;
  }
  function drawRadar() {
    const on=playerCar.selected&&!!saved; radar.hidden=!on; if(!on) return;
    const size=radar.clientWidth||180, dpr=devicePixelRatio||1;
    if(radar.width!==size*dpr||radar.height!==size*dpr) radar.width=radar.height=size*dpr;
    const g=radar.getContext('2d'), b=radarImage(), [px,py]=b.toPx(playerCar.pos[0],playerCar.pos[1]), R=size/2, zoom=size/(.6*b.span);
    g.setTransform(dpr,0,0,dpr,0,0); g.clearRect(0,0,size,size);
    g.save(); g.beginPath(); g.arc(R,R,R-2,0,7); g.clip(); g.fillStyle='#1d2228'; g.fillRect(0,0,size,size);
    g.translate(R,R); g.rotate(-playerCar.heading); g.scale(zoom,zoom); g.translate(-px,-py);
    g.imageSmoothingEnabled=true; g.drawImage(b.cv,0,0); g.restore();
    const n=-playerCar.heading-Math.PI/2; // north marker on the rim, turning with the map
    g.fillStyle='#fff'; g.font='700 11px Arial,sans-serif'; g.textAlign='center'; g.textBaseline='middle';
    g.beginPath(); g.arc(R+Math.cos(n)*(R-11),R+Math.sin(n)*(R-11),8,0,7); g.fillStyle='rgba(29,34,40,.85)'; g.fill();
    g.fillStyle='#fff'; g.fillText('N',R+Math.cos(n)*(R-11),R+Math.sin(n)*(R-11));
    g.beginPath(); g.moveTo(R,R-9); g.lineTo(R+6,R+7); g.lineTo(R,R+3); g.lineTo(R-6,R+7); g.closePath(); // the car, always pointing up
    g.fillStyle='#e55735'; g.strokeStyle='#fff'; g.lineWidth=1.5; g.fill(); g.stroke();
    g.beginPath(); g.arc(R,R,R-1.5,0,7); g.strokeStyle='rgba(255,255,255,.9)'; g.lineWidth=3; g.stroke();
  }

  // Nitro: Shift burns a tank that lasts NITRO_BURN s and refills over NITRO_FILL s, starting NITRO_DELAY s after you let go.
  // Run it dry and it locks until a quarter has come back, so boost comes in bursts rather than flickering.
  const NITRO_BURN=4, NITRO_FILL=8, NITRO_DELAY=.75;
  function nitroStep(dt,want) {
    const c=playerCar;
    if(c.nitroLocked&&c.nitro>=.25) c.nitroLocked=false;
    c.boosting=want&&!c.nitroLocked&&c.nitro>0;
    if(c.boosting) { c.nitro=Math.max(0,c.nitro-dt/NITRO_BURN); c.nitroWait=NITRO_DELAY; if(c.nitro===0) c.nitroLocked=true; }
    else if((c.nitroWait-=dt)<=0) c.nitro=Math.min(1,c.nitro+dt/NITRO_FILL);
    return c.boosting;
  }

  // Driving HUD: speedometer and nitro gauge beside the radar, and a card with the conditions where the car is (the page
  // supplies them through conditionsAt), in place of the page's side panel while driving.
  const hud=document.createElement('div'); hud.className='car-hud'; hud.hidden=true;
  hud.innerHTML='<canvas class="car-speedo" aria-hidden="true"></canvas><div class="car-nitro"><span>NITRO</span><div class="car-nitro-bar"><i></i></div></div>'+
    '<div class="car-here" role="status" aria-live="off"></div>';
  document.body.append(hud);
  const speedo=hud.querySelector('.car-speedo'), nitroBox=hud.querySelector('.car-nitro'), nitroFill=hud.querySelector('.car-nitro-bar i'), here=hud.querySelector('.car-here');
  let hereAt=0;
  const esc=t=>String(t).replace(/[&<>"]/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[ch]));
  function drawHud() {
    const c=playerCar, on=c.selected&&!!saved; hud.hidden=!on; if(!on) return;
    // speedometer: 0-200 km/h over a 240° dial, digital readout in the middle
    const size=speedo.clientWidth||150, dpr=devicePixelRatio||1, R=size/2, kmh=Math.abs(c.speed)*3.6, MAX=200;
    if(speedo.width!==size*dpr||speedo.height!==size*dpr) speedo.width=speedo.height=size*dpr; // a fresh canvas is 300×150
    const g=speedo.getContext('2d'), a0=Math.PI*.75, sweep=Math.PI*1.5, ang=v=>a0+sweep*Math.min(1,v/MAX);
    g.setTransform(dpr,0,0,dpr,0,0); g.clearRect(0,0,size,size);
    g.beginPath(); g.arc(R,R,R-2,0,7); g.fillStyle='rgba(20,24,30,.82)'; g.fill();
    g.lineWidth=6; g.lineCap='round';
    g.beginPath(); g.arc(R,R,R-12,a0,a0+sweep); g.strokeStyle='rgba(255,255,255,.15)'; g.stroke();
    g.beginPath(); g.arc(R,R,R-12,a0,ang(kmh)); g.strokeStyle=c.boosting?'#4fc3ff':'#f2f4f5'; g.stroke();
    g.lineWidth=1.5; g.strokeStyle='rgba(255,255,255,.6)'; g.fillStyle='rgba(255,255,255,.75)'; g.font='600 9px Arial,sans-serif'; g.textAlign='center'; g.textBaseline='middle';
    for(let v=0;v<=MAX;v+=20) { const t=ang(v), x=Math.cos(t), y=Math.sin(t);
      g.beginPath(); g.moveTo(R+x*(R-20),R+y*(R-20)); g.lineTo(R+x*(R-26),R+y*(R-26)); g.stroke();
      if(v%40===0) g.fillText(v,R+x*(R-35),R+y*(R-35)); }
    const t=ang(kmh); g.beginPath(); g.moveTo(R,R); g.lineTo(R+Math.cos(t)*(R-18),R+Math.sin(t)*(R-18)); g.strokeStyle='#e55735'; g.lineWidth=2.5; g.stroke();
    g.beginPath(); g.arc(R,R,4,0,7); g.fillStyle='#e55735'; g.fill();
    g.fillStyle='#fff'; g.font='700 24px Arial,sans-serif'; g.fillText(Math.round(kmh),R,R+R*.42);
    g.fillStyle='rgba(255,255,255,.6)'; g.font='600 9px Arial,sans-serif'; g.fillText(c.speed<-.5?'km/h · R':'km/h',R,R+R*.62);
    nitroFill.style.width=(c.nitro*100).toFixed(1)+'%';
    nitroBox.classList.toggle('boosting',c.boosting); nitroBox.classList.toggle('locked',c.nitroLocked);
    const now=performance.now();
    if(conditionsAt&&now-hereAt>300) { hereAt=now;
      const k=conditionsAt(c.pos[0],c.pos[1]);
      here.hidden=!k;
      if(k) here.innerHTML=`<small>${esc(k.date)}</small><b>${esc(k.place)}</b><small>${esc(k.region)}</small><dl>${k.rows.map(([l,v])=>`<dt>${esc(l)}</dt><dd>${esc(v)}</dd>`).join('')}</dl>`;
    }
  }

  const HINT_DRIVE='Driving · W/↑ drive · A/D or ←/→ steer · S/↓ brake · Space jump · Q/E relief · Shift boost · Esc pause';
  let hintText='';
  function updateHint() {
    const deg=Math.round(Math.atan(playerCar.grade)*180/Math.PI);
    const base=rain.left>0?`${HINT_DRIVE} · Rain shower: wet tyres`:HINT_DRIVE;
    const text=playerCar.stalled?(playerCar.nitroLocked?`Too steep (${deg}°) · nitro recharging, reverse out`:`Too steep (${deg}°) · hold Shift to boost, or reverse out`):Math.abs(deg)>=3?`${base} · slope ${deg>0?'+':''}${deg}°`:base;
    if(text!==hintText) { hintText=text; setHint(text); }
  }

  function tick(dt) {
    if(!playerCar.selected) return false;
    dt=Math.min(.05,dt);
    const c=playerCar, old=[c.pos[0],c.pos[1],c.heading,c.speed,c.jump,c.pitch,c.roll];
    const mpp=metresPerPixel();
    const throttle=driveKeys.has('KeyW');
    const input={throttle, brake:driveKeys.has('KeyS'), steer:(driveKeys.has('KeyD')?1:0)-(driveKeys.has('KeyA')?1:0),
      boost:nitroStep(dt,throttle&&(driveKeys.has('ShiftLeft')||driveKeys.has('ShiftRight')))};
    rainStep(dt);
    const n=Math.ceil(dt/(1/120)); // fixed small substeps keep the result independent of frame rate
    for(let i=0;i<n&&c.selected;i++) physicsStep(dt/n,input,mpp);
    if(c.selected&&!c.falling) { chaseCamera(dt); updateHint(); }
    drawRadar(); drawHud();
    if(c.falling||!c.placed) return true;
    return Math.abs(c.pos[0]-old[0])+Math.abs(c.pos[1]-old[1])>0||c.heading!==old[2]||Math.abs(c.pitch-old[5])+Math.abs(c.roll-old[6])>1e-5||c.speed!==old[3]||c.jump!==old[4];
  }

  function keydown(e) {
    if(e.code==='Escape') { if(playerCar.falling) { reset(); return; } cancelDrag(); if(choosing) { choosing=false; dock.classList.remove('choosing'); hideGhost(); setHint(''); refresh(); } else if(playerCar.placed&&!e.repeat) toggleSelected(); return; }
    const code=driveCode(e.code);
    if(!playerCar.selected||playerCar.falling||!driveCodes.has(code)||typing(e.target)) return;
    e.preventDefault();
    if(code==='KeyQ'||code==='KeyE') { if(!e.repeat) setRelief(code==='KeyE'?.1:-.1); }
    else if(code==='Space') { if(!e.repeat&&playerCar.jump===0&&!playerCar.offEdge) playerCar.jumpV=jumpSpeed(metresPerPixel()); }
    else driveKeys.add(code);
  }
  function keyup(e) {
    const code=driveCode(e.code);
    driveKeys.delete(code);
    if(playerCar.selected&&driveCodes.has(code)&&!typing(e.target)) e.preventDefault(); // a focused button would click on Space keyup
  }
  // Mouse wheel zooms the chase camera (towns appear/disappear with the map zoom); the car itself is unaffected.
  map.getContainer().addEventListener('wheel',e=>{
    if(!saved) return;
    e.preventDefault();
    viewScale=Math.min(8,Math.max(.2,viewScale*Math.exp(e.deltaY*.0015)));
  },{passive:false});
  addEventListener('keydown',keydown);
  addEventListener('keyup',keyup);
  addEventListener('change',e=>{ if(playerCar.selected&&!typing(e.target)) e.target.blur?.(); },true);
  addEventListener('click',e=>{ const el=e.target.closest?.('button,label'); if(playerCar.selected&&el&&el!==dock) setTimeout(()=>{ if(!typing(document.activeElement)) document.activeElement?.blur?.(); }); },true);
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
