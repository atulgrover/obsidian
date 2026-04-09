import esbuild from 'esbuild';
import process from 'process';

const prod = process.argv[2] === 'production';

const context = await esbuild.context({
	entryPoints: ['src/main.ts'],
	bundle: true,
	external: ['obsidian'],
	format: 'cjs',
	target: 'es2018',
	logLevel: 'info',
	sourcemap: prod ? false : 'inline',
	treeShaking: prod,
	outfile: 'main.js',
	outdir: '.',
	plugins: [
		{
			name: 'shared-resolver',
			setup(build) {
				build.onResolve({ filter: /^\.\.\/shared\/settings/ }, () => ({ path: '../shared/settings.ts' }));
			},
		},
	],
});

if (prod) {
	await context.rebuild();
	process.exit(0);
} else {
	await context.watch();
}