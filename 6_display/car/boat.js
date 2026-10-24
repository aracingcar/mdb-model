/* MDB Model's drivable river boat: its physics. Loaded before car.js, which supplies the shared player state and map helpers. */
window.createBoatMechanics = function ({ playerCar, VEHICLES, chaseMpp, metresToLon, metresToLat, onWater, waterAt, waterZ, clamp }) {
  // Boat: a planing runabout on flat water. Thrust from the outboard against quadratic water drag; the hull resists
  // sliding sideways far more than going forwards, so it carves turns but drifts a little; the rudder turns it in
  // proportion to the water flowing past, plus prop wash so it can still turn from rest under throttle. Banks stop it:
  // hit one and it scrapes along it if it can, or bounces back. Simulated in its own metres like the car.
  const BOAT={ length:6.6, mass:1100, thrust:7000, reverse:2500, dragFwd:20, dragFwdLin:60, dragSide:900, dragSideLin:500,
    turnRate:.9, turnSpeed:6, washTurn:.4, nitro:2.2 };
  const scale=()=>VEHICLES.boat.drawPx*chaseMpp()/BOAT.length; // map metres per boat metre
  function step(dt,input,mpp) {
    const c=playerCar, B=BOAT, sin=Math.sin(c.heading), cos=Math.cos(c.heading);
    c.steer=input.steer ? clamp(c.steer+input.steer*dt*2.5,-1,1) : c.steer>0 ? Math.max(c.steer-dt*1.5,0) : Math.min(c.steer+dt*1.5,0);
    const vx=sin*c.vel[0]+cos*c.vel[1], vy=cos*c.vel[0]-sin*c.vel[1];
    let Fx=0;
    if(input.throttle) Fx+=B.thrust*(input.boost?B.nitro:1);
    if(input.brake) Fx-=vx>.5 ? B.thrust*.6 : B.reverse; // throttle back hard, then reverse
    Fx-=B.dragFwd*vx*Math.abs(vx)+B.dragFwdLin*vx;
    const Fy=-(B.dragSide*vy*Math.abs(vy)+B.dragSideLin*vy);
    const ax=Fx/B.mass, ay=Fy/B.mass;
    c.accel=ax;
    c.vel[0]+=(ax*sin+ay*cos)*dt; c.vel[1]+=(ax*cos-ay*sin)*dt;
    const flow=Math.min(1,Math.abs(vx)/B.turnSpeed)*Math.sign(vx||1), wash=input.throttle?B.washTurn:0;
    const yawWant=c.steer*(B.turnRate*flow+wash);
    c.yawRate+=(yawWant-c.yawRate)*(1-Math.exp(-2.5*dt));
    c.heading=((c.heading+c.yawRate*dt)%(Math.PI*2)+Math.PI*2)%(Math.PI*2);
    // Move, staying on the river.
    const S=scale(), lat=c.pos[1], v=Math.hypot(c.vel[0],c.vel[1]), dir=Math.atan2(c.vel[0],c.vel[1]);
    const go=(h,len)=>[c.pos[0]+Math.sin(h)*len*S*dt*metresToLon(lat), lat+Math.cos(h)*len*S*dt*metresToLat];
    let next=go(dir,v);
    if(v>0&&!onWater(...next)) {
      next=null;
      for(const a of [.35,-.35,.7,-.7,1.05,-1.05,1.4,-1.4]) { // scrape along the bank
        const n=go(dir+a,v*Math.cos(a));
        if(onWater(...n)) { next=n; const keep=.92*v*Math.cos(a); c.vel=[Math.sin(dir+a)*keep,Math.cos(dir+a)*keep]; break; }
      }
      if(!next) { c.vel=c.vel.map(x=>-.3*x); next=c.pos.slice(); c.yawRate*=.5; } // head-on: bounce off
    }
    c.pos[0]=next[0]; c.pos[1]=next[1];
    c.waterTop=waterAt?.(c.pos[0],c.pos[1])?.top??c.waterTop;
    const fwd=Math.sin(c.heading)*c.vel[0]+Math.cos(c.heading)*c.vel[1], side=Math.cos(c.heading)*c.vel[0]-Math.sin(c.heading)*c.vel[1];
    c.speed=fwd; c.slip=Math.hypot(fwd,side)>1?-Math.atan2(side,Math.abs(fwd)):0;
    // Wake: two white trails from the stern quarters while under way.
    if(Math.abs(fwd)>1.5) {
      const L=VEHICLES.boat.drawPx*mpp, hs=Math.sin(c.heading), hc=Math.cos(c.heading), now=performance.now(), z=waterZ()+L*.02;
      const corner=k=>{ const f=-.45*L, s2=k*.2*L; return [c.pos[0]+(hs*f+hc*s2)*metresToLon(c.pos[1]), c.pos[1]+(hc*f-hs*s2)*metresToLat, z]; };
      const pts=[corner(-1),corner(1)];
      if(c.lastSkid&&now-c.lastSkid.t<250) for(let i=0;i<2;i++) c.skids.push({a:c.lastSkid.p[i],b:pts[i],t:now});
      c.lastSkid={p:pts,t:now};
      if(c.skids.length>400) c.skids.splice(0,c.skids.length-400);
    } else c.lastSkid=null;
    // Trim: bow lifts as it gets on the plane and settles at speed, leans into turns, and rocks gently on the water.
    const t=performance.now()/1000, plane=Math.min(1,Math.abs(fwd)/7)-Math.max(0,(Math.abs(fwd)-12)/20);
    const target={ pitch:.11*plane+.03*Math.sin(t*1.9), roll:clamp(c.yawRate*Math.abs(fwd)*.03,-.3,.3)+.03*Math.sin(t*1.3) };
    c.pitchV+=((target.pitch-c.pitch)*40-c.pitchV*9)*dt; c.pitch+=c.pitchV*dt;
    c.rollV+=((target.roll-c.roll)*40-c.rollV*9)*dt; c.roll+=c.rollV*dt;
  }

  return { step, scale };
};
