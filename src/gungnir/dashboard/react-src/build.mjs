// Bundles the React source into a single, dependency-free static/index.html —
// no CDN, no separate JS/CSS files, matching how server.py's `if _STATIC.exists()`
// route always serves static/index.html directly. Run: node build.mjs
import * as esbuild from "esbuild";
import { readFileSync, writeFileSync } from "fs";
import { fileURLToPath } from "url";
import { dirname, join } from "path";

const __dirname = dirname(fileURLToPath(import.meta.url));

const result = await esbuild.build({
  entryPoints: [join(__dirname, "index.jsx")],
  bundle: true,
  minify: true,
  format: "iife",
  jsx: "automatic",
  define: { "process.env.NODE_ENV": '"production"' },
  write: false,
});

const bundle = result.outputFiles[0].text;
if (bundle.includes("</script")) throw new Error("bundle contains a literal </script> — cannot embed safely");

const css = readFileSync(join(__dirname, "styles.css"), "utf8");

const html = `<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Odin — AI Trading Console</title>
<style>
${css}
</style>
</head>
<body>
<div id="root"></div>
<script>
${bundle}
</script>
</body></html>
`;

const outArg = process.argv[2] || "static/index.html";
const outPath = join(__dirname, "..", outArg);
writeFileSync(outPath, html);
console.log("Wrote", outPath, "(" + html.length + " bytes)");
