'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');

const android=name=>fs.readFileSync(path.join(__dirname,'../android/src/com/cyberbasslord/lightforge',name),'utf8');

test('NativeDeux only publishes buffers after every direct allocation succeeds',()=>{
 const source=android('NativeDeux.java');
 const readyCheck=source.indexOf('if(buffersReady())return;');
 const clear=source.indexOf('clearBuffers();',readyCheck);
 assert.ok(readyCheck>=0&&clear>readyCheck,'a legacy partial buffer set must be cleared before allocating a retry');
 assert.doesNotMatch(source,/if\(transform!=null\)return;/);
 const firstAllocation=source.indexOf('NativeDeuxTransform nextTransform=new NativeDeuxTransform();');
 const finalAllocation=source.indexOf('FloatBuffer nextBatchOutput=direct(size);');
 const publish=source.indexOf('transform=nextTransform;spectrum=nextSpectrum;summed=nextSummed;values=nextValues;mask=nextMask;');
 assert.ok(firstAllocation>=0&&finalAllocation>firstAllocation&&publish>finalAllocation,
  'a partial allocation must stay private until the entire buffer set is available');
 assert.match(source,/private boolean buffersReady\(\)\{return transform!=null&&spectrum!=null&&values!=null&&mask!=null&&summed!=null&&batchInput!=null&&batchOutput!=null;\}/);
});

test('NativePassageTask retires failed or cancelled engines before a retry can reuse them',()=>{
 const source=android('NativePassageTask.java');
 const retryFence=source.indexOf('if(cancelled||!"completed".equals(state))retireEngine(null);');
 const worker=source.indexOf('executor.execute(()->{');
 const retireFailure=source.indexOf('retireEngine(model);',worker);
 const failedState=source.indexOf('state=outcome;',worker);
 assert.ok(retryFence>=0&&worker>retryFence,'a failed, cancelled, or incomplete passage must start with no reusable engine');
 assert.ok(retireFailure>=worker&&retireFailure<failedState,
  'the failed worker must detach its engine before exposing a retryable state');
 assert.match(source,/private void retireEngine\(NativeDeux expected\)[\s\S]*?if\(expected==null\)\{model=engine;engine=null;\}[\s\S]*?else if\(engine==expected\)\{model=expected;engine=null;\}/);
});
