/* MDB Model's selectable terrain car. This file is copied into docs/car for GitHub Pages. */
window.createCarMechanics = function ({ deck, map, terrain, getRelief, setRelief, pausePlayback, refresh, pickTerrain }) {
  const playerCar = { kind:'playerCar', pos:[0,0], placed:false, heading:0, speed:0, selected:false, jump:0, jumpV:0, pitch:0, roll:0, pitchV:0, rollV:0, accel:0, grade:0, stalled:false, falling:false, fallZ:0, fallV:0, fallTime:0, fallGravity:0 };
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
    Object.assign(playerCar,{pos:pos.slice(0,2),placed:true,selected:true,heading:0,speed:0,jump:0,jumpV:0,pitch:0,roll:0,pitchV:0,rollV:0,accel:0,grade:0,stalled:false,falling:false,fallZ:0,fallV:0,fallTime:0,fallGravity:0}); hintText='';
    driveKeys.clear(); choosing = false; dock.classList.remove('choosing');
    dock.classList.add('placed'); dock.blur();
    pausePlayback(); enterChase();
    hint.classList.add('active');
    setHint('Driving · W drive · A/D steer · S brake · Space jump · Q/E relief · Shift boost · Esc pause');
    refresh(); return true;
  }
  function reset() {
    exitChase(true);
    Object.assign(playerCar,{placed:false,selected:false,speed:0,jump:0,jumpV:0,pitch:0,roll:0,pitchV:0,rollV:0,accel:0,grade:0,stalled:false,falling:false,fallZ:0,fallV:0,fallTime:0,fallGravity:0}); hintText='';
    driveKeys.clear(); choosing=false;
    dock.classList.remove('placed','choosing'); hint.classList.remove('active');
    setHint('Drag the car onto the map to drive again.'); refresh();
  }
  function dropPosition(e) {
    const box=map.getContainer().getBoundingClientRect(), x=e.clientX-box.left, y=e.clientY-box.top;
    if(x<0||y<0||x>=box.width||y>=box.height) return null;
    return pickTerrain(x,y);
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
    const scale=Math.max(1,(saved?CHASE.carPx:34)*metresPerPixel()/4.5)*(playerCar.selected&&!saved?1.3:1);
    return new deck.SimpleMeshLayer({
      id:'player-car', data:playerCar.placed?[playerCar]:[], mesh:carMesh, sizeScale:scale,
      getPosition:d=>[d.pos[0],d.pos[1],(d.falling?d.fallZ:terrainHeightAt(d.pos[0],d.pos[1])+d.jump)+scale*1.2],
      getOrientation:d=>[-d.roll*180/Math.PI,-d.heading*180/Math.PI,d.pitch*180/Math.PI], // deck: [about forward axis, yaw, about side axis]
      getColor:[255,255,255,255], _useMeshColors:true, pickable:true,
      material:{ambient:.55,diffuse:.7,shininess:30,specularColor:[80,80,80]},
      updateTriggers:{getPosition:[playerCar.pos[0],playerCar.pos[1],getRelief(),playerCar.jump,playerCar.falling,playerCar.fallZ],getOrientation:[playerCar.heading,playerCar.pitch,playerCar.roll]}
    });
  }

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
  const CHASE={ zoom:10.5, elevation:24*Math.PI/180, follow:7, turn:3, carPx:100 };
  let saved=null, rig=null;
  const handlers=['dragPan','dragRotate','touchZoomRotate','touchPitch','keyboard','doubleClickZoom','scrollZoom'];
  const chaseMpp=()=>78271.5*Math.cos(playerCar.pos[1]*Math.PI/180)/Math.pow(2,CHASE.zoom);

  function enterChase() {
    saved={ center:map.getCenter(), enabled:handlers.filter(h=>map[h]?.isEnabled()), pitch:map.getPitch(), bearing:map.getBearing(), zoom:map.getZoom(), padding:map.getPadding(), maxPitch:map.getMaxPitch() };
    map.setMaxPitch(85);
    handlers.forEach(h=>map[h]?.disable());
    rig=null;
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
    const c=playerCar, lat=c.pos[1], mpp=chaseMpp(), d=1.5*map.getContainer().clientHeight*mpp, k=r=>1-Math.exp(-r*dt);
    const wantH=c.heading;
    if(!rig) rig={ h:wantH };
    rig.h+=(((wantH-rig.h+3*Math.PI)%(2*Math.PI))-Math.PI)*k(CHASE.turn);
    const sin=Math.sin(rig.h), cos=Math.cos(rig.h), back=d*Math.cos(CHASE.elevation), up=d*Math.sin(CHASE.elevation);
    const carZ=terrainHeightAt(c.pos[0],lat)+c.jump;
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
    const c=playerCar, t=groundTilt(mpp), airborne=c.jump>0;
    const squat=airborne?0:Math.max(-.06,Math.min(.06,c.accel/(vmax/1.5)*.05)); // nose lifts when accelerating, dips when braking
    const target=airborne?{pitch:Math.max(-.35,Math.min(.35,c.jumpV/(900*Math.max(1,mpp/200))*.25)),roll:0}:{pitch:t.pitch+squat,roll:t.roll};
    const k=70, d=11;
    c.pitchV+=((target.pitch-c.pitch)*k-c.pitchV*d)*dt; c.pitch+=c.pitchV*dt;
    c.rollV+=((target.roll-c.roll)*k-c.rollV*d)*dt; c.roll+=c.rollV*dt;
    c.pitch=Math.max(-1.2,Math.min(1.2,c.pitch)); c.roll=Math.max(-.9,Math.min(.9,c.roll));
  }

  // Speeds are tied to the view: top speed crosses the screen in ~5 s, so the car moves across the map at any zoom.
  const MAX_CLIMB=Math.tan(32*Math.PI/180); // steepest slope (rise/run) the car can climb

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

  function physicsStep(dt, input, mpp, vmax0) {
    if(playerCar.falling) { fallStep(dt); return; }
    const boost=input.boost&&input.throttle, vmax=vmax0*(boost?2.6:1); // Shift: higher top speed and a much harder push
    const c=playerCar, engine=vmax0/1.5*(boost?4:1), sin=Math.sin(c.heading), cos=Math.cos(c.heading);
    // Hill mechanics. Slope along the heading is sampled either side of the car (terrain as drawn, incl. relief) and
    // low-passed so single rough cells don't jolt the car. Climbing costs traction: engine force fades to nothing as the
    // slope approaches MAX_CLIMB, gravity drags the car back, and a face steeper than MAX_CLIMB stops it dead.
    const span=Math.max(150,mpp*6), dLon=sin*span*metresToLon(c.pos[1]), dLat=cos*span*metresToLat;
    const raw=(terrainHeightAt(c.pos[0]+dLon,c.pos[1]+dLat)-terrainHeightAt(c.pos[0]-dLon,c.pos[1]-dLat))/(2*span);
    c.grade+=(raw-c.grade)*(1-Math.exp(-10*dt));
    const grade=c.grade, airborne=c.jump>0;
    const climb=g=>Math.max(0,g)/MAX_CLIMB;                        // 0 flat/downhill → 1 at the limit
    const topSpeed=g=>vmax*Math.max(0,1-climb(g));                 // the steeper the climb, the lower the speed the engine can hold
    let a=0;
    if(!airborne) {
      if(input.throttle) { const top=topSpeed(grade); a+=engine*(top>0?Math.max(-1,1-Math.max(0,c.speed)/top):-1); }
      if(input.brake) { const top=.3*topSpeed(-grade); a+=c.speed>.02*vmax ? -engine*2.2 : -engine*2*Math.max(-.3,Math.min(.6,(top+c.speed)/vmax)); } // brake, then reverse up to a (slope-limited) crawl
      if(!input.throttle) a-=c.speed*.35+Math.sign(c.speed)*engine*.12; // coasting: rolling resistance plus a little friction so it settles
      if(!input.throttle||grade<0) a-=grade/Math.hypot(1,grade)*engine*.5; // gravity along the slope: pulls back uphill, speeds you up downhill
    }
    c.accel=a;
    let v=c.speed+a*dt;
    const dir=input.throttle?1:input.brake&&c.speed<=.02*vmax?-1:(v>=0?1:-1);
    const movingUp=dir*grade>=MAX_CLIMB;
    c.stalled=!airborne&&movingUp&&(input.throttle||input.brake);
    if(!airborne&&movingUp) v=v>0?Math.max(0,v-engine*5*dt):Math.min(0,v+engine*5*dt); // too steep: speed bleeds off to zero
    if(!input.throttle&&!input.brake&&Math.abs(v)<.01*vmax&&Math.abs(grade)<MAX_CLIMB*.6) v=0; // parked on a hill it can hold
    c.speed=Math.max(-.3*vmax,Math.min(vmax*1.15,v));
    // Steering: yaw rate follows speed (no turning on the spot), limited by lateral grip; reversing flips it like a real car.
    const radius=60*mpp, grip=Math.PI*.55, rate=Math.max(-1.6,Math.min(1.6,c.speed/radius))*input.steer;
    c.heading=((c.heading+Math.max(-grip,Math.min(grip,rate))*dt)%(Math.PI*2)+Math.PI*2)%(Math.PI*2);
    // Carry momentum over the edge and fall before returning to the dock.
    const dist=c.speed*dt, nLon=Math.sin(c.heading)*dist*metresToLon(c.pos[1]), nLat=Math.cos(c.heading)*dist*metresToLat;
    if(!onTerrain(c.pos[0]+nLon,c.pos[1]+nLat)) {
      c.falling=true; c.fallZ=terrainHeightAt(c.pos[0],c.pos[1])+c.jump;
      c.fallV=c.jumpV; c.fallTime=0; c.fallGravity=Math.max(900,mpp*50);
      c.stalled=false; driveKeys.clear();
      setHint('Off the edge! Returning the car to its dock…');
      fallStep(dt); return;
    }
    c.pos[0]+=nLon; c.pos[1]+=nLat;
    updateTilt(dt,mpp,vmax);
    if(c.jumpV||c.jump) {
      const k=Math.max(1,mpp/200);
      c.jumpV-=900*k*dt; c.jump=Math.max(0,c.jump+c.jumpV*dt);
      if(c.jump===0) c.jumpV=0;
    }
  }

  const HINT_DRIVE='Driving · W drive · A/D steer · S brake · Space jump · Q/E relief · Shift boost · Esc pause';
  let hintText='';
  function updateHint() {
    const deg=Math.round(Math.atan(playerCar.grade)*180/Math.PI);
    const text=playerCar.stalled?`Too steep (${deg}°) · reverse out or turn`:Math.abs(deg)>=3?`${HINT_DRIVE} · slope ${deg>0?'+':''}${deg}°`:HINT_DRIVE;
    if(text!==hintText) { hintText=text; setHint(text); }
  }

  function tick(dt) {
    if(!playerCar.selected) return false;
    dt=Math.min(.05,dt);
    const c=playerCar, old=[c.pos[0],c.pos[1],c.heading,c.speed,c.jump,c.pitch,c.roll];
    const mpp=metresPerPixel(), vmax=map.getContainer().clientWidth*mpp/5;
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
    else if(e.code==='Space') { if(!e.repeat&&playerCar.jump===0) playerCar.jumpV=520*Math.max(1,metresPerPixel()/200); }
    else driveKeys.add(e.code);
  }
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

  return { layer, click, hover, start, tick, state: playerCar, driveKeys, place, reset, isPlacing:()=>!!dragging||choosing };
};
