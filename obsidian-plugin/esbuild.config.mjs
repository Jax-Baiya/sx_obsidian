import esbuild from 'esbuild';
import process from 'process';

const watch = process.argv.includes('--watch');

const ctx = await esbuild.context({
  entryPoints: ['src/main.ts'],
  bundle: true,
  sourcemap: true,
  format: 'cjs',
  target: 'es2020',
  platform: 'browser',
  outfile: 'main.js',
  external: ['obsidian']
});

if (watch) {
  await ctx.watch();
  console.log('[sx-obsidian-db] watching...');
} else {
  await ctx.rebuild();
  await ctx.dispose();
  console.log('[sx-obsidian-db] build complete');
}
