.pragma library

function fmtTokens(v) {
  v = Number(v) || 0
  if (v >= 1e6) return (v / 1e6).toFixed(2) + "M"
  if (v >= 1000) return (v / 1000).toFixed(1) + "k"
  return String(Math.round(v))
}

// A test count that fits the TESTS column: exact below 10k, then "12.3k"
function fmtCount(v) {
  v = Number(v) || 0
  return v >= 10000 ? (v / 1000).toFixed(1) + "k" : String(v)
}

// Context used, compact: "86k", "345k", "1.0M"
function fmtCtx(v) {
  v = Number(v) || 0
  if (v >= 1e6) return (v / 1e6).toFixed(1) + "M"
  return Math.round(v / 1000) + "k"
}

// Context bands by tokens used, whatever the window: the first 200k are the "smart" ones.
var CTX_WARN = 200000
var CTX_HOT = 350000
function ctxBand(used) {
  return used > CTX_HOT ? "hot" : used >= CTX_WARN ? "warn" : "ok"
}

// Worst context band among live agents in these trees: "hot" > "warn" > "ok", or "" when nothing is live.
function worstBand(trees) {
  var rank = { "": 0, ok: 1, warn: 2, hot: 3 }, worst = ""
  function walk(n) {
    if (hasCtx(n) && (n.state === "run" || n.state === "attn") && n.ctx) {
      var b = ctxBand(n.ctx.used || 0)
      if (rank[b] > rank[worst]) worst = b
    }
    (n.children || []).forEach(walk)
  }
  trees.forEach(walk)
  return worst
}

function fmtDuration(sec) {
  sec = Math.max(0, Math.floor(sec || 0))
  var h = Math.floor(sec / 3600), m = Math.floor(sec % 3600 / 60), s = sec % 60
  var pad = function(n) { return (n < 10 ? "0" : "") + n }
  return h ? h + ":" + pad(m) + ":" + pad(s) : m + ":" + pad(s)
}

function elapsed(node, nowSec) {
  if (!node || !node.startedAt) return ""
  var end = node.endedAt || nowSec
  return fmtDuration(end - node.startedAt)
}

function ctxFraction(node) {
  var c = node && node.ctx
  if (!c || !c.size) return -1
  return Math.max(0, Math.min(1, c.used / c.size))
}

function hasCtx(node) {
  return node && ["orchestrator", "implementor", "agent", "merger", "fixer", "session"].indexOf(node.kind) >= 0
}

function canOpen(node) {
  return node && !!node.short && ["orchestrator", "implementor", "merger", "fixer", "session"].indexOf(node.kind) >= 0
}

// Layered layout for the ticket graph: each ticket one column right of its deepest blocker, edges that
// skip columns routed through invisible waypoints, rows reordered (barycenter sweeps + adjacent swaps)
// to remove crossings where the graph allows it.
function dagLayout(tickets) {
  var T = {}, ids = []
  for (var i = 0; i < tickets.length; i++) { T[tickets[i].id] = tickets[i]; ids.push(tickets[i].id) }
  var depth = {}
  function d(id) {
    if (depth[id] !== undefined) return depth[id]
    var bs = (T[id].blockedBy || []).filter(function(b) { return T[b] })
    depth[id] = bs.length ? 1 + Math.max.apply(null, bs.map(d)) : 0
    return depth[id]
  }
  ids.forEach(d)
  var L = ids.length ? Math.max.apply(null, ids.map(function(x) { return depth[x] })) : 0
  var layers = [], layerOf = {}, segs = [], chains = []
  for (var k = 0; k <= L; k++) layers.push([])
  ids.slice().sort(function(a, b) { return (+a - +b) || (a < b ? -1 : 1) }).forEach(function(id) {
    layers[depth[id]].push(id); layerOf[id] = depth[id]
  })
  ids.forEach(function(id) {
    (T[id].blockedBy || []).filter(function(b) { return T[b] }).forEach(function(p) {
      var chain = [p]
      for (var k = depth[p] + 1; k < depth[id]; k++) {
        var v = "v:" + p + ":" + id + ":" + k
        layers[k].push(v); layerOf[v] = k; chain.push(v)
      }
      chain.push(id)
      chains.push({ from: p, to: id, chain: chain })
      for (var j = 0; j < chain.length - 1; j++) segs.push([chain[j], chain[j + 1]])
    })
  })
  function index() { var m = {}; layers.forEach(function(l) { l.forEach(function(n, i) { m[n] = i }) }); return m }
  function crossings() {
    var m = index(), c = 0
    for (var i = 0; i < segs.length; i++) for (var j = i + 1; j < segs.length; j++) {
      var a = segs[i], b = segs[j]
      if (layerOf[a[0]] !== layerOf[b[0]]) continue
      if ((m[a[0]] - m[b[0]]) * (m[a[1]] - m[b[1]]) < 0) c++
    }
    return c
  }
  function nbrs(n, up) { return segs.filter(function(s) { return s[up ? 1 : 0] === n }).map(function(s) { return s[up ? 0 : 1] }) }
  var best = layers.map(function(l) { return l.slice() }), bestC = crossings()
  for (var it = 0; it < 8 && bestC; it++) {
    var sweep = function(k, up) {
      var m = index()
      layers[k] = layers[k].map(function(n, i) {
        var nb = nbrs(n, up)
        return [n, nb.length ? nb.reduce(function(a, x) { return a + m[x] }, 0) / nb.length : i]
      }).sort(function(x, y) { return x[1] - y[1] }).map(function(x) { return x[0] })
    }
    for (var k1 = 1; k1 <= L; k1++) sweep(k1, true)
    for (var k2 = L - 1; k2 >= 0; k2--) sweep(k2, false)
    var c = crossings()
    if (c < bestC) { bestC = c; best = layers.map(function(l) { return l.slice() }) }
  }
  for (var b = 0; b < best.length; b++) layers[b] = best[b]
  var improved = true
  while (improved && bestC) {
    improved = false
    layers.forEach(function(l) {
      for (var i = 0; i < l.length - 1; i++) {
        var t = l[i]; l[i] = l[i + 1]; l[i + 1] = t
        var c2 = crossings()
        if (c2 < bestC) { bestC = c2; improved = true } else { t = l[i]; l[i] = l[i + 1]; l[i + 1] = t }
      }
    })
  }
  var rows = Math.max.apply(null, layers.map(function(l) { return l.length }).concat([1]))
  var pos = {}
  layers.forEach(function(l, k) { l.forEach(function(n, i) { pos[n] = { col: k, row: i + (rows - l.length) / 2 } }) })
  return { ids: ids, chains: chains, pos: pos, cols: L + 1, rows: rows }
}

// ---- flattening the agent tree into stable rows -------------------------------------------------
// Rows are plain objects with primitive fields so they can live in a ListModel and update in place
// (a delegate that is recreated every second would drop focus and half-typed answers).

function isExpanded(node, overrides) {
  if (overrides[node.id] !== undefined) return overrides[node.id]
  return !(node.state === "done" && (node.kind === "skill" || node.kind === "agent" || node.kind === "implementor"))
}

// "~/.claude/CLAUDE.md  1.2k\nCLAUDE.md  34.4k\n= 35.6k, 3.6% of the window", for the CLAUDE.md column's tooltip
function mdFiles(md, size) {
  if (!md.files || !md.files.length) return ""
  var lines = md.files.map(function(f) { return f.path + "  " + fmtTokens(f.tokens) })
  return lines.join("\n") + "\n= " + fmtTokens(md.tokens) + (size ? ", " + (md.tokens / size * 100).toFixed(1) + "% of the window" : "")
}

// The daemon's git status (fleet/git.py status(), plus the last push) as flat fields for a ListModel row.
// Runs pass the same object to GitTicks directly.
function gitFields(g) {
  g = g || {}
  var p = g.push || {}
  return {
    gitPath: g.path || "", gitBranch: g.branch || "", gitBase: g.base || "", gitMerged: !!g.merged,
    gitDirty: g.dirty || 0, gitRemote: g.remote || "", gitUnpushed: g.unpushed || 0, gitPushed: !!g.pushed,
    gitTarget: g.target || "", gitPushState: p.state || "", gitPushKind: p.kind || "", gitPushMsg: p.msg || ""
  }
}

function rowFor(n, depth, extra) {
  var c = n.ctx || {}
  var md = n.claudeMd || {}
  var g = gitFields(n.git)
  var tc = n.tests || {}
  var r = {
    key: n.id, depth: depth, kind: n.kind || "", name: n.name || "", tag: n.tag || "", label: n.label || "",
    state: n.state || "", status: n.status || "", summary: n.summary || "", note: n.note || "",
    ctxUsed: c.used || 0, ctxSize: c.size || 0, tokens: n.tokens || 0,
    mdTokens: md.tokens || 0, mdFiles: mdFiles(md, c.size),
    startedAt: n.startedAt || 0, endedAt: n.endedAt || 0, short: n.short || "", ticket: n.ticket || "",
    waitingFor: n.waitingFor || "", hasKids: (n.children || []).length > 0, expanded: false,
    runId: "", lane: "", laneFirst: false, laneLast: false, activity: n.activity || "", alive: !!n.alive,
    testTotal: tc.total || 0, testPassed: tc.passed || 0, testFailed: tc.failed || 0, testSkipped: tc.skipped || 0,
    testCmd: tc.cmd || "", testExpected: tc.expected || 0,
    testEstimated: !!tc.estimated
  }
  for (var f in g) r[f] = g[f]
  for (var k in extra) r[k] = extra[k]
  return r
}

function pushTree(out, n, depth, overrides, extra) {
  var r = rowFor(n, depth, extra)
  r.expanded = r.hasKids && isExpanded(n, overrides)
  out.push(r)
  if (r.expanded) (n.children || []).forEach(function(c) { pushTree(out, c, depth + 1, overrides, extra) })
}

// One lane per child of the root (implementors, mergers, fixers); the root itself sits above the lanes.
function flattenRun(run, overrides, laneFor) {
  var out = []
  if (!run.tree) return out
  var root = rowFor(run.tree, 0, { runId: run.id })
  root.expanded = root.hasKids && isExpanded(run.tree, overrides)
  out.push(root)
  if (!root.expanded) return out
  ;(run.tree.children || []).forEach(function(child) {
    var start = out.length
    pushTree(out, child, 1, overrides, { runId: run.id, lane: laneFor(child) })
    out[start].laneFirst = true
    out[out.length - 1].laneLast = true
  })
  return out
}

function flattenSessions(sessions, overrides, laneFor) {
  var out = []
  sessions.forEach(function(s) {
    var start = out.length
    pushTree(out, s, 1, overrides, { lane: laneFor(s) })
    out[start].laneFirst = true
    out[out.length - 1].laneLast = true
  })
  return out
}

// Update a ListModel to match `items` (each with a unique `key`) without recreating unchanged rows.
function syncModel(model, items) {
  for (var i = 0; i < items.length; i++) {
    var it = items[i]
    if (i < model.count && model.get(i).key === it.key) { model.set(i, it); continue }
    var found = -1
    for (var j = i + 1; j < model.count; j++) if (model.get(j).key === it.key) { found = j; break }
    if (found >= 0) { model.move(found, i, 1); model.set(i, it) }
    else model.insert(i, it)
  }
  while (model.count > items.length) model.remove(model.count - 1)
}
