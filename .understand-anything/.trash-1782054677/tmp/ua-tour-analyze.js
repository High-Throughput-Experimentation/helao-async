#!/usr/bin/env node
"use strict";

const fs = require("fs");

function main() {
  const inputPath = process.argv[2];
  const outputPath = process.argv[3];
  if (!inputPath || !outputPath) {
    console.error("Usage: node ua-tour-analyze.js <input.json> <output.json>");
    process.exit(1);
  }

  const raw = JSON.parse(fs.readFileSync(inputPath, "utf8"));
  const nodes = raw.nodes || [];
  const edges = raw.edges || [];
  const layers = raw.layers || [];

  const nodeById = new Map();
  for (const n of nodes) nodeById.set(n.id, n);

  // Adjacency for forward edges (all types) + import/call edges
  const fanIn = new Map();
  const fanOut = new Map();
  const forwardImportCall = new Map(); // for BFS
  const allForward = new Map();
  const allBackward = new Map();

  for (const n of nodes) {
    fanIn.set(n.id, 0);
    fanOut.set(n.id, 0);
    forwardImportCall.set(n.id, new Set());
    allForward.set(n.id, new Set());
    allBackward.set(n.id, new Set());
  }

  for (const e of edges) {
    if (!nodeById.has(e.source) || !nodeById.has(e.target)) continue;
    fanOut.set(e.source, (fanOut.get(e.source) || 0) + 1);
    fanIn.set(e.target, (fanIn.get(e.target) || 0) + 1);
    allForward.get(e.source).add(e.target);
    allBackward.get(e.target).add(e.source);
    if (e.type === "imports" || e.type === "calls") {
      forwardImportCall.get(e.source).add(e.target);
    }
  }

  const nameOf = (id) => (nodeById.get(id) || {}).name || id;
  const sumOf = (id) => (nodeById.get(id) || {}).summary || "";

  // A. Fan-In ranking
  const fanInRanking = [...fanIn.entries()]
    .map(([id, v]) => ({ id, fanIn: v, name: nameOf(id) }))
    .sort((a, b) => b.fanIn - a.fanIn)
    .slice(0, 20);

  // B. Fan-Out ranking
  const fanOutRanking = [...fanOut.entries()]
    .map(([id, v]) => ({ id, fanOut: v, name: nameOf(id) }))
    .sort((a, b) => b.fanOut - a.fanOut)
    .slice(0, 20);

  // C. Entry point candidates
  const codeEntryNames = new Set([
    "index.ts", "index.js", "main.ts", "main.js", "app.ts", "app.js",
    "server.ts", "server.js", "mod.rs", "main.go", "main.py", "main.rs",
    "manage.py", "app.py", "wsgi.py", "asgi.py", "run.py", "__main__.py",
    "Application.java", "Main.java", "Program.cs", "config.ru", "index.php",
    "App.swift", "Application.kt", "main.cpp", "main.c", "launch.py",
  ]);

  const fanOutValues = [...fanOut.values()].sort((a, b) => b - a);
  const top10pctIdx = Math.max(0, Math.floor(fanOutValues.length * 0.1) - 1);
  const top10pctThreshold = fanOutValues.length ? fanOutValues[top10pctIdx] : 0;
  const fanInValuesAsc = [...fanIn.values()].sort((a, b) => a - b);
  const bottom25Idx = Math.floor(fanInValuesAsc.length * 0.25);
  const bottom25Threshold = fanInValuesAsc.length ? fanInValuesAsc[bottom25Idx] : 0;

  const entryScores = [];
  for (const n of nodes) {
    let score = 0;
    const fp = (n.filePath || "").replace(/\\/g, "/");
    const depth = fp ? fp.split("/").length : 99;
    if (n.type === "document") {
      const isRootMd = /\.md$/i.test(n.name || "") && depth <= 1;
      if (/^readme\.md$/i.test(n.name || "") && depth <= 1) score += 5;
      else if (isRootMd) score += 2;
    } else if (n.type === "file") {
      if (codeEntryNames.has(n.name)) score += 3;
      if (depth <= 2) score += 1;
      if ((fanOut.get(n.id) || 0) >= top10pctThreshold && top10pctThreshold > 0) score += 1;
      if ((fanIn.get(n.id) || 0) <= bottom25Threshold) score += 1;
    }
    if (score > 0) {
      entryScores.push({ id: n.id, score, name: n.name, summary: sumOf(n.id), type: n.type });
    }
  }
  entryScores.sort((a, b) => b.score - a.score);
  const entryPointCandidates = entryScores.slice(0, 5);

  // D. BFS from top CODE entry point
  let startNode = null;
  for (const c of entryScores) {
    if (c.type === "file") { startNode = c.id; break; }
  }
  if (!startNode && nodes.length) {
    // fallback: highest fan-out file
    const f = fanOutRanking.find((r) => (nodeById.get(r.id) || {}).type === "file");
    startNode = f ? f.id : nodes[0].id;
  }

  const order = [];
  const depthMap = {};
  const byDepth = {};
  if (startNode) {
    const queue = [[startNode, 0]];
    const seen = new Set([startNode]);
    while (queue.length) {
      const [id, d] = queue.shift();
      order.push(id);
      depthMap[id] = d;
      (byDepth[d] = byDepth[d] || []).push(id);
      for (const nxt of forwardImportCall.get(id) || []) {
        if (!seen.has(nxt)) { seen.add(nxt); queue.push([nxt, d + 1]); }
      }
    }
  }

  // E. Non-code inventory
  const nonCodeFiles = { documentation: [], infrastructure: [], data: [], config: [] };
  const infraTypes = new Set(["service", "pipeline", "resource"]);
  const dataTypes = new Set(["table", "schema", "endpoint"]);
  for (const n of nodes) {
    const rec = { id: n.id, name: n.name, type: n.type, summary: sumOf(n.id) };
    if (n.type === "document") nonCodeFiles.documentation.push(rec);
    else if (infraTypes.has(n.type)) nonCodeFiles.infrastructure.push(rec);
    else if (dataTypes.has(n.type)) nonCodeFiles.data.push(rec);
    else if (n.type === "config") nonCodeFiles.config.push(rec);
  }

  // F. Clusters: bidirectional import/call pairs, expanded
  const isImportCall = (a, b) => forwardImportCall.get(a) && forwardImportCall.get(a).has(b);
  const pairs = [];
  const pairSeen = new Set();
  for (const a of nodeById.keys()) {
    for (const b of forwardImportCall.get(a) || []) {
      if (a === b) continue;
      if (isImportCall(b, a)) {
        const key = [a, b].sort().join("||");
        if (!pairSeen.has(key)) { pairSeen.add(key); pairs.push([a, b]); }
      }
    }
  }
  const clusters = [];
  const usedInCluster = new Set();
  for (const [a, b] of pairs) {
    if (usedInCluster.has(a) && usedInCluster.has(b)) continue;
    const members = new Set([a, b]);
    // expand: add nodes connected to 2+ members
    let changed = true;
    while (changed && members.size < 5) {
      changed = false;
      const candidateCount = new Map();
      for (const m of members) {
        const neigh = new Set([
          ...(allForward.get(m) || []),
          ...(allBackward.get(m) || []),
        ]);
        for (const c of neigh) {
          if (members.has(c)) continue;
          candidateCount.set(c, (candidateCount.get(c) || 0) + 1);
        }
      }
      for (const [c, cnt] of candidateCount.entries()) {
        if (cnt >= 2 && members.size < 5) { members.add(c); changed = true; }
      }
    }
    // count internal edges
    let edgeCount = 0;
    for (const m of members) {
      for (const f of allForward.get(m) || []) if (members.has(f)) edgeCount++;
    }
    for (const m of members) usedInCluster.add(m);
    clusters.push({ nodes: [...members], edgeCount });
  }
  clusters.sort((a, b) => b.edgeCount - a.edgeCount);
  const topClusters = clusters.slice(0, 10);

  // G. Layers
  const layerOut = {
    count: layers.length,
    list: layers.map((l) => ({ id: l.id, name: l.name, description: l.description })),
  };

  // H. Node summary index
  const nodeSummaryIndex = {};
  for (const n of nodes) {
    nodeSummaryIndex[n.id] = { name: n.name, type: n.type, summary: n.summary || "" };
  }

  const out = {
    scriptCompleted: true,
    entryPointCandidates,
    fanInRanking,
    fanOutRanking,
    bfsTraversal: { startNode, order, depthMap, byDepth },
    nonCodeFiles,
    clusters: topClusters,
    layers: layerOut,
    nodeSummaryIndex,
    totalNodes: nodes.length,
    totalEdges: edges.length,
  };

  fs.writeFileSync(outputPath, JSON.stringify(out, null, 2));
  console.error("done: " + nodes.length + " nodes, " + edges.length + " edges, start=" + startNode);
  process.exit(0);
}

try { main(); } catch (e) { console.error(e.stack || String(e)); process.exit(1); }
