'use strict';
const {Worker,isMainThread,workerData}=require('node:worker_threads');
const fs=require('node:fs');
if(isMainThread){
 const watchdog=new Worker(__filename,{workerData:{ceiling:Number(process.env.GAME_RSS_CEILING||2684354560),file:process.env.GAME_RSS_RECEIPT||__dirname+'/dense-memory-rss-watchdog.json'}});
 watchdog.unref();
}else{
 let peak=0;
 function sample(){
  const rss=process.memoryUsage().rss;peak=Math.max(peak,rss);
  const receipt={scope:'An independent watchdog thread samples process.memoryUsage().rss; process.kill uses the process namespace directly.',rssCeilingBytes:workerData.ceiling,maxObservedRssBytes:peak,currentRssBytes:rss,safetyStop:rss>workerData.ceiling,pid:process.pid};
  fs.writeFileSync(workerData.file,JSON.stringify(receipt));
  if(receipt.safetyStop)process.kill(process.pid,'SIGKILL');
 }
 sample();setInterval(sample,25);
}
