/* Audit harness only. Uses frozen1.2.0 snapshot outside production. */
const {chromium}=require('/opt/codex/runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('fs'),path=require('path'),cp=require('child_process');
const track=process.argv[2]||'demo';
(async()=>{
 const server=cp.spawn('python3',['-m','http.server','8823','--bind','127.0.0.1','--directory','/tmp/lightforge-1.2.0-baseline'],{stdio:'ignore'});let browser;
 try{
  await new Promise(r=>setTimeout(r,500));
  browser=await chromium.launch({executablePath:path.resolve('app/toolchain/chrome/chrome-headless-shell-linux64/chrome-headless-shell'),headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
  const page=await browser.newPage();await page.goto('http://127.0.0.1:8823');
  const result=await page.evaluate(async(track)=>await MusicAnalyzer.analyze('http://127.0.0.1:8823/'+track+'.wav',{sensitivity:.82}),track);
  const raw=result.baselineFeatures;delete result.baselineFeatures;
  fs.writeFileSync('app/lightforge/qa/music-1.3.0/baseline-'+track+'-music.json',JSON.stringify(result));
  fs.writeFileSync('app/lightforge/qa/music-1.3.0/baseline-'+track+'-activations.json',JSON.stringify(raw));
  console.log(JSON.stringify({duration:result.duration,bpm:result.bpm,meter:result.meter,beats:result.beats.length,onsets:result.onsets.length,sections:result.sections,engine:result.engine},null,2));
 }finally{if(browser)await browser.close();server.kill();}
})().catch(e=>{console.error(e);process.exitCode=1;});
