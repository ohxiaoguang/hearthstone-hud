import { rollup } from 'rollup';
import config from '../rollup.config.js';
const bundle = await rollup(config);
try {
  await bundle.write(config.output);
} finally {
  await bundle.close();
}
console.log('Frontend build complete');
// @rollup/plugin-typescript can retain filesystem watchers on macOS after
// bundle.close(). All output and plugin cleanup above have completed.
process.exit(0);
