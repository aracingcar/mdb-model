/* MDB Model's selectable terrain car. This file is copied into docs/car for GitHub Pages. */
window.createCarMechanics = function ({ deck, map, terrain, getRelief, setRelief, pausePlayback, refresh }) {
  const playerCar = { kind:'playerCar', pos:[149.13,-35.28], heading:0, speed:0, selected:false, jump:0, jumpV:0 };
  const driveKeys = new Set(), driveCodes = new Set(['KeyW','KeyA','KeyS','KeyD','KeyQ','KeyE','Space']);
  const hint = document.createElement('div');
  hint.id = 'driveHint';
  hint.className = 'car-drive-hint';
  hint.setAttribute('role','status');
  hint.setAttribute('aria-live','polite');
  document.body.append(hint);

  const carAtlas = document.createElement('canvas');
  carAtlas.width = carAtlas.height = 64;
  const ctx = carAtlas.getContext('2d');
  ctx.translate(32,32);
  ctx.fillStyle='#17252e'; ctx.beginPath(); ctx.roundRect(-16,-26,32,52,9); ctx.fill();
  ctx.fillStyle='#e55735'; ctx.beginPath(); ctx.roundRect(-12,-22,24,44,7); ctx.fill();
  ctx.fillStyle='#bfe9ef'; ctx.beginPath(); ctx.roundRect(-9,-17,18,12,3); ctx.fill(); ctx.beginPath(); ctx.roundRect(-9,1,18,11,3); ctx.fill();
  ctx.fillStyle='#fff'; ctx.fillRect(-15,-5,4,9); ctx.fillRect(11,-5,4,9);
  const iconMapping = { car:{x:0,y:0,width:64,height:64,mask:false,anchorY:32} };

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
    return new deck.IconLayer({
      id:'player-car', data:[playerCar], iconAtlas:carAtlas, iconMapping,
      getIcon:()=> 'car', getPosition:d=>[d.pos[0],d.pos[1],terrainHeightAt(d.pos[0],d.pos[1])+15+d.jump],
      getSize:d=>d.selected?40:36, sizeUnits:'pixels', sizeMinPixels:32, sizeMaxPixels:44,
      billboard:true, getAngle:d=>d.heading*180/Math.PI, pickable:true,
      parameters:{depthTest:false},
      updateTriggers:{getPosition:[playerCar.pos[0],playerCar.pos[1],getRelief(),playerCar.jump],getAngle:playerCar.heading,getSize:playerCar.selected}
    });
  }

  function click(info) {
    if(info.object?.kind!=='playerCar') return;
    playerCar.selected=!playerCar.selected; playerCar.speed=0; driveKeys.clear();
    if(playerCar.selected) pausePlayback();
    hint.classList.toggle('active',playerCar.selected);
    hint.textContent=playerCar.selected?'Car selected · W drive · A/D steer · S brake · Space jump · Q/E relief':'Click the car in Canberra · W drive · A/D steer · S brake · Space jump · Q/E relief';
    refresh();
  }

  function hover(info) {
    if(info.object?.kind!=='playerCar') return false;
    const tip=document.getElementById('tip');
    tip.innerHTML='<b>Canberra car</b>Click to select, then drive with WASD';
    tip.style.display='block'; tip.style.left=Math.min(info.x+14,innerWidth-230)+'px'; tip.style.top=(info.y+14)+'px';
    return true;
  }

  function tick(dt) {
    if(!playerCar.selected) return false;
    dt=Math.min(.05,dt);
    const oldX=playerCar.pos[0], oldY=playerCar.pos[1], oldHeading=playerCar.heading, oldSpeed=playerCar.speed, oldJump=playerCar.jump;
    const throttle=driveKeys.has('KeyW'), brake=driveKeys.has('KeyS');
    const steer=(driveKeys.has('KeyD')?1:0)-(driveKeys.has('KeyA')?1:0);
    const ground=terrainHeightAt(oldX,oldY), steerRate=.18+.62*Math.min(1,playerCar.speed/15);
    playerCar.heading=(playerCar.heading+steer*steerRate*dt+Math.PI*4)%(Math.PI*2);
    if(throttle) {
      const trial=playerCar.speed+12*dt, distance=trial*dt, cos=Math.max(.2,Math.cos(oldY*Math.PI/180));
      const nx=oldX+Math.sin(playerCar.heading)*distance/(111320*cos), ny=oldY+Math.cos(playerCar.heading)*distance/111320;
      const grade=(terrainHeightAt(nx,ny)-ground)/Math.max(1,distance), drag=Math.min(10,Math.max(0,grade)*getRelief()*1.5);
      playerCar.speed=Math.min(48,playerCar.speed+Math.max(2,12-drag)*dt);
    } else playerCar.speed=Math.max(0,playerCar.speed-(brake?30:3.5)*dt);
    const distance=playerCar.speed*dt, cos=Math.max(.2,Math.cos(playerCar.pos[1]*Math.PI/180));
    playerCar.pos[0]+=Math.sin(playerCar.heading)*distance/(111320*cos); playerCar.pos[1]+=Math.cos(playerCar.heading)*distance/111320;
    if(playerCar.jumpV||playerCar.jump) { playerCar.jumpV-=900*dt; playerCar.jump=Math.max(0,playerCar.jump+playerCar.jumpV*dt); if(playerCar.jump===0) playerCar.jumpV=0; }
    if(distance>.05) {
      const point=map.project(playerCar.pos), w=map.getContainer().clientWidth, h=map.getContainer().clientHeight;
      if(point.x<w*.22||point.x>w*.78||point.y<h*.22||point.y>h*.78) map.setCenter(playerCar.pos);
    }
    return distance>.01||Math.abs(playerCar.heading-oldHeading)>.0001||Math.abs(playerCar.speed-oldSpeed)>.001||playerCar.jump!==oldJump||oldX!==playerCar.pos[0]||oldY!==playerCar.pos[1];
  }

  function keydown(e) {
    if(!playerCar.selected||!driveCodes.has(e.code)||e.target.matches('input,button,a')) return;
    e.preventDefault();
    if(e.code==='KeyQ'||e.code==='KeyE') { if(!e.repeat) setRelief(e.code==='KeyE'?.1:-.1); }
    else if(e.code==='Space') { if(!e.repeat&&playerCar.jump===0) playerCar.jumpV=520; }
    else driveKeys.add(e.code);
  }
  addEventListener('keydown',keydown);
  addEventListener('keyup',e=>driveKeys.delete(e.code));
  addEventListener('blur',()=>driveKeys.clear());

  function start(redraw) {
    let last=performance.now();
    function frame(now) {
      const dt=Math.min(.05,(now-last)/1000); last=now;
      if(playerCar.selected&&tick(dt)) redraw();
      requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  }

  return { layer, click, hover, start };
};
