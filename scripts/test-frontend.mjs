import ts from 'typescript';
import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
const source=readFileSync(new URL('../src/clipboard.ts',import.meta.url),'utf8');
const code=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2020,module:ts.ModuleKind.ES2020}}).outputText;
const {copyText}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
let copied='';
assert.equal(await copyText('report',{writeText:async text=>{copied=text;}},null),'clipboard');
assert.equal(copied,'report');
let removed=false,restored=false,selected=false;
const input={style:{},focus(){},select(){selected=true;},remove(){removed=true;}};
const doc={body:{appendChild(){}},activeElement:{focus(){restored=true;}},createElement(){return input;},execCommand(){return true;}};
assert.equal(await copyText('long '.repeat(2000),{writeText:async()=>{throw new Error('denied');}},doc),'fallback');
assert.ok(removed&&restored&&selected);assert.equal(input.value.length,10000);
const fail={...doc,execCommand(){return false;}};
await assert.rejects(copyText('manual',{writeText:async()=>{throw new Error('denied');}},fail),/denied.*compat copy API returned false/);
await assert.rejects(copyText('manual',null,null),/no text clipboard API/);
const ui=readFileSync(new URL('../src/index.tsx',import.meta.url),'utf8');
assert.match(ui,/aria-label=\{t\('manualAria'\)\}/);
assert.doesNotMatch(ui,/导出 TXT|\.txt['"]|createObjectURL/);
console.log('Clipboard tests: 4 paths passed; selectable fallback and no TXT export verified');

assert.doesNotMatch(ui, /<details|<summary/);
assert.match(ui, /ButtonItem layout="below" onClick=\{\(\)=>setOpen\(value=>!value\)\}/);
assert.match(ui, /open&&<div/);
console.log('Fold controls use Decky ButtonItem and React state; no native details/summary');

// The retired controls must be gone, and the new resource/about entries present.
assert.doesNotMatch(ui, /clear_card_cache|cardLanguage|followUi|download_missing_images/);
assert.match(ui, /t\('languageOptions'\)/);
assert.match(ui, /t\('resources'\)/);
assert.match(ui, /t\('about'\)/);
assert.doesNotMatch(ui, /ConfirmModal/);          // inline confirmation, no modal
assert.match(ui, /role=\"alertdialog\"/);
assert.match(ui, /cancel_image_download|cancelImageDownload/);
assert.match(ui, /download_all_images|downloadAllImages/);
console.log('Settings page: language options, download resources and about wired');

// Interface strings must stay in sync between English and Chinese, and every
// key used by the panel has to exist.
const catalog=readFileSync(new URL('../src/i18n.ts',import.meta.url),'utf8');
const block=(name)=>{
  const start=catalog.indexOf(`const ${name}: Dict = {`);
  assert.ok(start>=0,`missing ${name} dictionary`);
  const end=catalog.indexOf('\n};',start);
  return catalog.slice(start,end);
};
const keys=(name)=>new Set([...block(name).matchAll(/^\s{2}([a-zA-Z]\w*):/gm)].map(m=>m[1]));
const enKeys=keys('en'),zhKeys=keys('zhCN');
assert.deepEqual([...zhKeys].sort(),[...enKeys].sort());
const used=new Set([...ui.matchAll(/\bt\('(\w+)'/g)].map(m=>m[1]));
const missing=[...used].filter(key=>!enKeys.has(key));
assert.deepEqual(missing,[]);
console.log(`Interface strings: ${enKeys.size} keys in both languages, ${used.size} used by the panel`);
