// Build the offline renderer. Run npm ci --prefix ../toolchain/graphics first
// using preview/src/package.json + package-lock.json when recreating tooling.
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
const project=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const dependencies=path.resolve(project,'../toolchain/graphics/node_modules');
const require=createRequire(path.join(dependencies,'esbuild/package.json'));
const esbuild=require('esbuild');
await esbuild.build({entryPoints:[path.join(project,'web/preview/src/vehicle-preview.js')],outfile:path.join(project,'web/preview/vehicle-preview.js'),bundle:true,minify:true,format:'iife',target:['chrome91'],nodePaths:[dependencies],legalComments:'eof',logLevel:'info'});
