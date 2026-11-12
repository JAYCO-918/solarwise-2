// Writes icons.svg: an SVG sprite with the Lucide icons (ISC licence) used in the slides.
// Run from the repository root once the interface's dependencies are installed:  node presentation/src/make_icons.mjs
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const icons = path.resolve(here, "..", "..", "frontend", "node_modules", "lucide-react", "dist", "esm", "icons");
const NAMES = [
  "sun-medium", "spray-can", "search", "eye", "check", "x", "minus", "flask-conical", "gauge", "waypoints",
  "circle-question-mark", "thermometer-sun", "zap-off", "trees", "unplug", "file-question-mark", "wrench",
  "shield-check", "scale", "coins", "triangle-alert", "list-checks", "map-pin", "arrow-right", "cloud-rain",
  "database", "file-text", "users", "sparkles", "droplets", "wind", "cpu", "lock", "target", "flag", "handshake",
  "plug-zap", "languages", "sliders-horizontal", "layers", "workflow", "ruler", "microscope", "trending-down",
  "git-compare-arrows", "file-spreadsheet", "clipboard-check", "server", "monitor", "satellite-dish", "bot",
  "badge-check", "circle-check", "circle-x", "circle-minus", "circle-alert", "banknote", "sunrise", "history",
  "chevron-right", "sun", "ban", "circle-off", "info", "quote", "calendar-clock", "hand-coins", "receipt-text",
];
// Some icon files only re-export another icon under an older name: follow the re-export.
async function iconModule(file) {
  const module = await import(pathToFileURL(file).href);
  if (module.__iconData) return module;
  const target = /from '\.\/([a-z0-9-]+\.mjs)'/.exec(fs.readFileSync(file, "utf8"));
  if (!target) throw new Error(`cannot read the icon in ${file}`);
  return iconModule(path.join(path.dirname(file), target[1]));
}
const attrs = (o) => Object.entries(o).filter(([k]) => k !== "key").map(([k, v]) => `${k}="${v}"`).join(" ");
let out = '<svg xmlns="http://www.w3.org/2000/svg" style="display:none" aria-hidden="true">\n';
for (const name of NAMES) {
  const file = path.join(icons, `${name}.mjs`);
  if (!fs.existsSync(file)) throw new Error(`no such icon: ${name}`);
  const { __iconData } = await iconModule(file);
  out += `<symbol id="i-${name}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">`;
  out += __iconData.node.map(([tag, a]) => `<${tag} ${attrs(a)}/>`).join("");
  out += "</symbol>\n";
}
out += "</svg>\n";
fs.writeFileSync(path.join(here, "icons.svg"), out);
console.log(`icons.svg: ${NAMES.length} icons, ${out.length} bytes`);
