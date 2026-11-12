// Converts the PowerPoint file to PDF with LibreOffice (compiled to WebAssembly), so that its text can be compared
// with the reference PDF by check_pptx.py. Optional tool: it needs `npm install @matbee/libreoffice-converter`
// somewhere, and LIBREOFFICE_CONVERTER pointing at that package.
//
//   LIBREOFFICE_CONVERTER=/path/to/node_modules/@matbee/libreoffice-converter node presentation/src/check_pptx.mjs
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const out = path.resolve(here, "..");
const work = path.join(out, ".work");
const converter = process.env.LIBREOFFICE_CONVERTER;
if (!converter) {
  console.error("set LIBREOFFICE_CONVERTER to the folder of the @matbee/libreoffice-converter package");
  process.exit(2);
}
const { convertDocument } = await import(pathToFileURL(path.join(converter, "dist", "index.js")).href);
const source = process.argv[2] || path.join(out, "SolarWise-DZ-pitch.pptx");
const started = Date.now();
const result = await convertDocument(fs.readFileSync(source), { outputFormat: "pdf" }, { wasmPath: path.join(converter, "wasm") });
fs.mkdirSync(work, { recursive: true });
const target = path.join(work, "pptx-as-rendered.pdf");
fs.writeFileSync(target, result.data);
console.log(`${path.basename(source)} rendered by LibreOffice in ${Math.round((Date.now() - started) / 1000)} s: ${path.relative(process.cwd(), target)}`);
process.exit(0);
