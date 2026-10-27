const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const scope = {window: {}};
vm.runInNewContext(fs.readFileSync(path.join(root, 'meal-config.js'), 'utf8'), scope);
const endpoint = 'https://raw.githubusercontent.com/sseungmiii/knu_meal_test/main/menu.json';
test('the meal screen reads the shared live URL rather than a deployment snapshot', () => {
  assert.equal(scope.window.MEAL_CONFIG.dataUrl, endpoint);
  const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
  assert.match(html, /fetch\(window\.MEAL_CONFIG\.dataUrl,\s*\{ cache: "no-store" \}\)/);
  assert.ok(html.indexOf('./meal-config.js') < html.indexOf('async function init'));
  assert.doesNotMatch(html, /\.\.\/menu\.json/);
});
test('the legacy Pages URL resolves to the repository homepage', () => {
  const html = fs.readFileSync(path.join(root, 'test_2/index.html'), 'utf8');
  assert.match(html, /url=\.\.\//);
  assert.equal(new URL('../', 'https://sseungmiii.github.io/knu_meal_test/test_2/').href,
    'https://sseungmiii.github.io/knu_meal_test/');
});
test('Vercel menu.json forwards to the same canonical data', () => {
  const config = JSON.parse(fs.readFileSync(path.join(root, 'vercel.json'), 'utf8'));
  assert.equal(config.outputDirectory, 'public');
  assert.equal(config.rewrites.find(r => r.source === '/menu.json').destination, endpoint);
});
test('static output excludes crawler source, private files and stale menu snapshots', () => {
  const output = path.join(root, 'public');
  const files = fs.readdirSync(output, {recursive: true}).filter(name => fs.statSync(path.join(output, name)).isFile());
  assert.deepEqual(files.map(name => name.replaceAll('\\', '/')).sort(),
    ['index.html', 'meal-config.js', 'meal-status.js', 'test_2/index.html'].sort());
});
