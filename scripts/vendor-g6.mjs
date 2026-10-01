// Reproduce the vendored browser distribution and its dependency license notices.
import fs from 'node:fs';
import path from 'node:path';
const root = process.cwd();
const destination = path.join(root, 'src/skill_atlas/web/static');
const seen = new Set();
const notices = [];
function visit(name, from) {
  let directory = from;
  let packageDir;
  while (true) {
    const candidate = path.join(directory, 'node_modules', name);
    if (fs.existsSync(path.join(candidate, 'package.json'))) { packageDir = candidate; break; }
    const parent = path.dirname(directory);
    if (parent === directory) throw new Error(`Missing dependency ${name}`);
    directory = parent;
  }
  if (seen.has(packageDir)) return;
  seen.add(packageDir);
  const metadata = JSON.parse(fs.readFileSync(path.join(packageDir, 'package.json'), 'utf8'));
  const licenses = fs.readdirSync(packageDir).filter(file => /^(license|licence|notice)(\.|$)/i.test(file)).sort();
  notices.push(`${metadata.name} ${metadata.version} (${metadata.license || 'see license'})\n` +
    licenses.map(file => fs.readFileSync(path.join(packageDir, file), 'utf8')).join('\n'));
  for (const dependency of Object.keys(metadata.dependencies || {}).sort()) visit(dependency, packageDir);
  return {metadata, packageDir};
}
const {metadata, packageDir} = visit('@antv/g6', root);
const outputs = {
  'g6.min.js': `/*! @antv/g6 ${metadata.version} | MIT | See g6-LICENSE.txt for dependency notices. */\n` +
    fs.readFileSync(path.join(packageDir, 'dist/g6.min.js'), 'utf8'),
  'g6-LICENSE.txt': notices.join('\n\n' + '='.repeat(72) + '\n\n'),
};
for (const [file, content] of Object.entries(outputs)) {
  const target = path.join(destination, file);
  if (process.argv.includes('--check')) {
    if (fs.readFileSync(target, 'utf8') !== content) throw new Error(`Run npm run vendor:g6 to update ${file}`);
  } else fs.writeFileSync(target, content);
}
