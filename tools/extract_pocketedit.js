// Prints PocketEdit's MODULE_LIBRARY_DATA and COMMAND_LIBRARY_DATA as JSON.
// usage: node tools/extract_pocketedit.js PocketEdit/index.html > pocketedit.json
const fs = require('fs');
const s = fs.readFileSync(process.argv[2], 'utf8');
function grab(name) {
  const i = s.indexOf('const ' + name + ' =');
  if (i < 0) throw new Error(name + ' not found');
  const j = s.indexOf('{', i);
  let d = 0, k = j;
  for (; k < s.length; k++) { if (s[k] === '{') d++; else if (s[k] === '}') { d--; if (!d) break; } }
  return eval('(' + s.slice(j, k + 1) + ')');
}
process.stdout.write(JSON.stringify({ modules: grab('MODULE_LIBRARY_DATA'), commands: grab('COMMAND_LIBRARY_DATA') }));
