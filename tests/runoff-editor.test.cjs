const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync(__dirname + '/../6_display/template.html', 'utf8');
const script = html.match(/<script>\s*([\s\S]*?)<\/script>/)[1].replace('const META = __META__;', 'const META = {};');
new vm.Script(script);
const saved = new Map();
const context = vm.createContext({ console, structuredClone, crypto: require('node:crypto').webcrypto, D: { engineHash: 'test' }, fetch() {},
  localStorage: { getItem: k => saved.get(k), setItem: (k, v) => saved.set(k, v) } });
vm.runInContext(html.slice(html.indexOf('// ---- Runoff area editor'), html.indexOf('// ---- end runoff area editor')), context);
const run = code => vm.runInContext(code, context);

// A 3 x 1 strip of 0.1-degree squares in one basin: nodes a, b (river), c; a and c are watersheds that join the river directly.
const square = x => [[x, -35], [x + .1, -35], [x + .1, -34.9], [x, -34.9], [x, -35]];
const areas = { cells: { a: [square(145)], b: [square(145.1)], c: [square(145.2)] } };
const engine = { nodes: [
  { id: 'a', basin: 'B', share: .2, area: 100, next: 'b', lon: 145.05, lat: -34.95 },
  { id: 'b', basin: 'B', share: .5, area: 250, next: '', lon: 145.15, lat: -34.95, river: true, outlet: true },
  { id: 'c', basin: 'B', share: .3, area: 150, next: 'b', lon: 145.25, lat: -34.95 }] };
context.areas = areas; context.engine = engine;
run('RR = Object.assign(rrBuild(areas, engine), { system: "test", rev: 0, edited: false })');
assert.equal(run('RR.cells.length'), 3);
assert.equal(run('RR.V.length'), 8); // the corners shared by neighbouring squares are one vertex
const km2 = id => run(`rrCellKm2(rrCell('${id}') || RR.cells.find(c => c.id === '${id}'), RR.V)`);
const shares = () => run('rrShares(RR)');
const near = (a, b, msg) => assert.ok(Math.abs(a - b) < 1e-9, `${msg}: ${a} vs ${b}`);
near(shares().a, .2, 'unedited share'); near(shares().b, .5, 'unedited share');

// Basin and outer borders are fixed; nothing here is a free corner until a cell is split, so every vertex is pinned.
assert.equal(run('rrTopology(RR).pinned.size'), 8);

// Splitting a cell: a new cell takes the half nearest the new dot, with the same runoff density; the basin total is kept.
const before = run('rrPack(RR)');
const added = run('rrSplit(RR, RR.cells.find(c => c.id === "c"), [145.28, -34.95])');
assert.equal(typeof added, 'object');
assert.equal(run('RR.cells.length'), 4);
near(shares().c + shares()[added.id], .3, 'split keeps the cell total');
assert.ok(shares()[added.id] > 0 && shares().c > 0);
near(shares().a + shares().b + shares().c + shares()[added.id], 1, 'basin total');
// the cut's two new corners sit on the basin's outer edge, so they are fixed too, and the neighbour b still shares its border with a
assert.equal(run('RR.V.length'), 10);
assert.equal(run('rrTopology(RR).pinned.size'), 10);
run('RR = Object.assign(rrUnpack(' + JSON.stringify(before) + '), { system: "test", rev: 0, edited: false })');

// A 2 x 2 block: the middle corner is shared by four areas and free. Dragging it trades runoff between them, keeping the basin total.
const quad = [['p', 145, -35], ['q', 145.1, -35], ['r', 145, -34.9], ['s', 145.1, -34.9]];
context.quadAreas = { cells: Object.fromEntries(quad.map(([id, x, y]) => [id, [[[x, y], [x + .1, y], [x + .1, y + .1], [x, y + .1], [x, y]]]])) };
context.quadEngine = { nodes: quad.map(([id, x, y]) => ({ id, basin: 'Q', share: .25, area: 100, next: '', lon: x + .05, lat: y + .05 })) };
run('RR = Object.assign(rrBuild(quadAreas, quadEngine), { system: "test", rev: 0, edited: false })');
const free = run('[...Array(RR.V.length).keys()].filter(i => !rrTopology(RR).pinned.has(i))');
assert.equal(free.length, 1);
run(`RR.V[${free[0]}] = [145.12, -34.88]`);
const moved = shares();
near(moved.p + moved.q + moved.r + moved.s, 1, 'dragging a border keeps the basin total');
assert.ok(moved.s < .25 && moved.p > .25, 'the area the corner moved away from shrinks and the opposite one grows');
run('RR = Object.assign(rrUnpack(' + JSON.stringify(before) + '), { system: "test", rev: 0, edited: false })');

// Deleting an area gives it to the neighbour sharing the most border, keeps the total, and refuses a river node's area.
assert.equal(run('typeof rrMerge(RR, RR.cells.find(c => c.id === "a"), null)'), 'string'); // no neighbour to join
const into = run('rrMerge(RR, RR.cells.find(c => c.id === "a"))');
assert.equal(into.id, 'b');
assert.equal(run('RR.cells.length'), 2);
near(shares().b, .7, 'merged share'); near(shares().c, .3, 'untouched share');

// Overlay on the engine: shares follow the draft, the deleted node goes, and the total per basin is exact.
run('RR.edited = true; RR.rev++');
const out = run('rrApplyAreas(engine, RR)');
assert.equal(out.nodes.length, 2);
near(out.nodes.find(n => n.id === 'b').share, .7, 'merged node');
near(out.nodes.reduce((s, n) => s + n.share, 0), 1, 'overlay total');
assert.equal(engine.nodes.length, 3); // the source engine is untouched

// A cut-out area joins the river node it was cut from, and flows into the same node as its host.
run('RR = Object.assign(rrUnpack(' + JSON.stringify(before) + '), { system: "test", rev: 0, edited: false })');
const cut = run('rrSplit(RR, RR.cells.find(c => c.id === "a"), [145.02, -34.95])');
const withCut = run('rrApplyAreas(engine, RR)');
const node = withCut.nodes.find(n => n.id === cut.id);
assert.equal(node.next, 'b');
assert.equal(node.basin, 'B');
near(withCut.nodes.reduce((s, n) => s + n.share, 0), 1, 'overlay total after a cut');
near(withCut.nodes.find(n => n.id === 'b').share, .5, 'unedited area'); // an unedited area keeps its share

// Following the routing network: a node the routing editor deleted gives its area to the node that took its runoff; dots follow moved river nodes.
run('RR = Object.assign(rrUnpack(' + JSON.stringify(before) + '), { system: "test", rev: 0, edited: false })');
run('RR.cells.find(c => c.id === "a").river = true');
run(`RR.route = { graph: { nodes: [{ id: 'b', lon: 145.16, lat: -34.96 }], links: [], redirects: { a: 'b' }, folded: {} }, edited: false }`);
run('rrFollowRouting({ nodes: [{ id: "c" }, { id: "b", river: true }] })');
assert.equal(run('RR.cells.map(c => c.id).join()'), 'b,c');
assert.equal(run('JSON.stringify(RR.cells[0].dot)'), '[145.16,-34.96]');
assert.equal(run('RR.cells[0].river'), true);
near(shares().b, .7, 'area followed the redirect');

// A node made in the routing editor (no watershed) gets a small area round its dot, holding its share, so the two sets of nodes match.
run(`RR.route.graph.nodes.push({ id: 'tributary-1', lon: 145.3, lat: -34.9, model: { basin: 'B', share: .1, area: 40 } })`);
run('rrFollowRouting({ nodes: [{ id: "c" }, { id: "b", river: true }] })');
const made = run('RR.cells.find(c => c.id === "tributary-1")');
assert.ok(made && made.river && run('rrCellKm2(RR.cells.find(c => c.id === "tributary-1"), RR.V)') > 0);
assert.deepEqual(JSON.parse(JSON.stringify(made.dot)), [145.3, -34.9]);
near(made.dens * run('rrCellKm2(RR.cells.find(c => c.id === "tributary-1"), RR.V)'), .1, 'new area carries the node share');
run('rrFollowRouting({ nodes: [{ id: "c" }, { id: "b", river: true }] })');
assert.equal(run('RR.cells.filter(c => c.id === "tributary-1").length'), 1); // not made twice

// Drafts survive a pack and unpack.
const round = run('rrUnpack(rrPack(RR))');
assert.equal(round.cells.length, 3);
assert.throws(() => run('rrUnpack({ V: [], cells: [{ id: "x", rings: [[0, 1, 2]], dot: [0, 0] }], removed: [] })'));
console.log('Runoff area editor: build, shared corners, fixed borders, split, delete, shares and engine overlay passed.');
