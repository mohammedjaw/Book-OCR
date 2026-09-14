// Execute the shipped polling script against a small DOM/fetch harness.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const elements = {};
for (const id of ['ocr-status','status-labels','completed','processing','pending','failed','progress','progress-text','worker-text','poll-error','exports','start-form','pause-form','retry-form']) elements[id] = {textContent:'',button:{},querySelector(){return this.button;}};
elements['ocr-status'].dataset = {url:'/status'};
elements['ocr-status'].querySelectorAll = () => [];
elements['status-labels'].textContent = JSON.stringify({running:'Running',completed:'Completed',connection_error:'Retrying'});
let callback, delay, calls = 0, result = {total:8,counts:{completed:2,processing:2,pending:4,failed:0},active:true,state:'running',retryable_failed:0,complete:false};
const context = {
 document:{hidden:false,getElementById:id=>elements[id],addEventListener(){}},
 fetch:async()=>{calls++; if(result instanceof Error) throw result;return {ok:true,json:async()=>result};},
 AbortController,clearTimeout(){},setTimeout(fn,ms){if(ms!==10000){callback=fn;delay=ms;}return 1;},
};
vm.runInNewContext(fs.readFileSync('static/js/book-status.js','utf8'),context);
const flush = () => new Promise(resolve=>setImmediate(resolve));
(async()=>{
 await flush();
 assert.equal(elements.completed.textContent,2);assert.equal(elements.progress.value,2);
 assert.equal(elements['start-form'].button.disabled,true);assert.equal(elements['pause-form'].button.disabled,false);assert.equal(delay,3000);
 result = new Error('offline');await callback();assert.equal(elements['poll-error'].textContent,'Retrying');assert.equal(delay,6000);
 result = {total:8,counts:{completed:8},active:false,state:'completed',retryable_failed:0,complete:true};
 await callback();assert.equal(elements.completed.textContent,8);assert.equal(elements.exports.hidden,false);assert.equal(elements['worker-text'].textContent,'Completed');assert.equal(delay,15000);assert.equal(calls,3);
 console.log('Polling: active updates, buttons, failure recovery, completion and slower idle polling passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
