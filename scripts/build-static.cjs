const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const output = path.resolve(root, 'public');
if (path.dirname(output) !== root || path.basename(output) !== 'public') throw new Error('Unexpected output directory');
// Only this generated output directory is removed. Source and backup files are untouched.
fs.rmSync(output, {recursive: true, force: true});
const files = ['index.html', 'meal-config.js', 'meal-status.js', 'test_2/index.html'];
for (const file of files) {
  const target = path.join(output, file);
  fs.mkdirSync(path.dirname(target), {recursive: true});
  fs.copyFileSync(path.join(root, file), target);
}
console.log('Prepared 4 public files. Menu data is read from the canonical shared URL.');
