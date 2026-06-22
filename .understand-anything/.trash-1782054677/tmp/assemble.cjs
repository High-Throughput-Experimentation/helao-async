const fs = require('fs');
const base = '/mnt/STORAGE/repos/helao/helao-async/.understand-anything/intermediate/';
const g = require(base + 'assembled-graph.json');
const ids = new Set(g.nodes.map(n => n.id));

// --- tour normalize ---
let T = require(base + 'tour.json');
if (T.steps && !Array.isArray(T)) T = T.steps;
T = T.map(s => {
  if (s.nodesToInspect && !s.nodeIds) s.nodeIds = s.nodesToInspect;
  if (s.whyItMatters && !s.description) s.description = s.whyItMatters;
  s.nodeIds = (s.nodeIds || []).filter(x => ids.has(x));
  const o = { order: s.order, title: s.title, description: s.description, nodeIds: s.nodeIds };
  if (s.languageLesson) o.languageLesson = s.languageLesson;
  return o;
}).sort((a, b) => a.order - b.order);

const L = require(base + 'layers.json');

const kg = {
  version: '1.0.0',
  project: {
    name: 'HELAO-async',
    languages: ['python', 'yaml', 'batch', 'dmc', 'markdown', 'shell', 'drawio', 'ipynb', 'css', 'json', 'csv'],
    frameworks: ['FastAPI', 'Bokeh', 'Pydantic', 'uvicorn', 'Starlette', 'aiohttp', 'pytest'],
    description: "Caltech HTE group's distributed instrument control software following HELAO design principles: cooperating FastAPI and Bokeh servers (action drivers, orchestrators, visualizers, operator UIs) launched as a configurable orchestration group. Scope: helao/core framework, helao/helpers, the hte production deployment, and root launch tooling.",
    analyzedAt: process.env.TS || new Date().toISOString(),
    gitCommitHash: '04577cb946d0c6a4921a2f9dcff320595a986a7a'
  },
  nodes: g.nodes,
  edges: g.edges,
  layers: L,
  tour: T
};
fs.writeFileSync(base + 'assembled-graph.json', JSON.stringify(kg, null, 2));
console.log('assembled: nodes', kg.nodes.length, 'edges', kg.edges.length, 'layers', L.length, 'tour', T.length);
