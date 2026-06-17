#!/usr/bin/env node
/**
 * Patch antd v6 Card type declaration for React 19 compatibility.
 *
 * Problem: antd exports Card via `interface CardInterface extends typeof InternalCard`,
 * which loses the callable signature required by React 19's stricter JSX types (TS2604).
 *
 * Fix: change `interface extends typeof X` to `type = typeof X & { ... }` (intersection
 * type preserves the call signature).
 *
 * This script is idempotent - safe to run multiple times.
 */

const fs = require('fs');
const path = require('path');

const PATCHED = `import InternalCard from './Card';
import CardGrid from './CardGrid';
import CardMeta from './CardMeta';
export type { CardProps, CardTabListType } from './Card';
export type { CardGridProps } from './CardGrid';
export type { CardMetaProps } from './CardMeta';
export type CardInterface = typeof InternalCard & {
    Grid: typeof CardGrid;
    Meta: typeof CardMeta;
};
declare const Card: CardInterface;
export default Card;
`;

const TARGETS = [
  path.join(__dirname, '..', 'node_modules', 'antd', 'es', 'card', 'index.d.ts'),
  path.join(__dirname, '..', 'node_modules', 'antd', 'lib', 'card', 'index.d.ts'),
];

let patched = 0;
for (const target of TARGETS) {
  if (!fs.existsSync(target)) continue;
  const content = fs.readFileSync(target, 'utf-8');
  if (content.includes('export type CardInterface = typeof InternalCard &')) {
    patched++;
    continue; // already patched
  }
  fs.writeFileSync(target, PATCHED, 'utf-8');
  patched++;
  console.log(`[patch-antd-card] patched: ${target}`);
}

if (patched > 0) {
  console.log(`[patch-antd-card] done (${patched} file(s))`);
}
