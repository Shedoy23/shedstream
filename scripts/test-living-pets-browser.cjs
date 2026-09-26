const assert=require('assert'),fs=require('fs'),path=require('path'),http=require('http');
const {chromium}=require('C:/Users/Edward/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const profiles=require('../Расширение/frontend/pet-assets/living-pets-v1/profiles.json');
(async()=>{
 const folder=path.resolve(__dirname,'../Расширение/frontend/pet-assets/living-pets-v1'),out=path.resolve(__dirname,'../dist/living-pets-20260926');fs.mkdirSync(out,{recursive:true});
 const server=http.createServer((req,res)=>{const f=path.resolve(folder,'.'+new URL(req.url,'http://localhost').pathname);if(!f.startsWith(folder+path.sep)||!fs.existsSync(f)){res.writeHead(404);return res.end()}res.setHeader('Content-Type',f.endsWith('.js')?'application/javascript':f.endsWith('.png')?'image/png':f.endsWith('.json')?'application/json':'text/html');fs.createReadStream(f).pipe(res)});
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 try{
 const page=await browser.newPage({viewport:{width:1200,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(process.argv[2]||'http://127.0.0.1:'+server.address().port+'/preview.html');
 await page.waitForFunction(()=>document.querySelectorAll('.pet-choice canvas[data-state]').length===12);
 await page.evaluate(()=>{window.historyStates={};new MutationObserver(()=>document.querySelectorAll('.pet-choice').forEach(b=>{const id=b.dataset.pet;(historyStates[id]??=[]);const state=b.querySelector('canvas').dataset.state;if(historyStates[id].at(-1)!==state)historyStates[id].push(state)})).observe(document.querySelector('#gallery'),{subtree:true,attributes:true,attributeFilter:['data-state']})});
 await page.getByRole('button',{name:'Гулять',exact:true}).click();
 await page.waitForFunction(()=>[...document.querySelectorAll('.pet-choice canvas')].every(c=>c.dataset.state==='walk'));
 await page.getByRole('button',{name:'Спать',exact:true}).click();
 await page.waitForFunction(()=>[...document.querySelectorAll('.pet-choice canvas')].every(c=>c.dataset.state==='sleep'));
 await page.getByRole('button',{name:'Светлый фон',exact:true}).click();
 await page.screenshot({path:path.join(out,'all-sleep.png'),fullPage:true});
 const history=await page.evaluate(()=>historyStates);for(const p of profiles)for(const s of ['start','walk','stop','yawn','sit','sleep'])assert(history[p.id].includes(s),p.id+' '+s);
 await page.getByRole('button',{name:'Гулять',exact:true}).click();await page.waitForFunction(()=>[...document.querySelectorAll('.pet-choice canvas')].every(c=>c.dataset.state==='walk'));
 const waking=await page.evaluate(()=>historyStates);for(const p of profiles)for(const s of ['wake','rise','start','walk'])assert(waking[p.id].includes(s),p.id+' '+s);
 await page.getByRole('button',{name:'В другую сторону',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('#hero').style.transform.includes('scaleX(-1)'));
 await page.getByRole('button',{name:'Замедлить ×4',exact:true}).click();assert.equal(await page.locator('#slow').getAttribute('aria-pressed'),'true');
 await page.locator('summary').click();
 for(const profile of profiles){
  await page.locator('#pet').selectOption(profile.id);assert.equal(await page.locator('#hero').getAttribute('data-pet'),profile.id);
  const frameHashes=[];
  for(let i=0;i<20;i++){
   await page.locator('.frame').nth(i).click();
   assert.equal(await page.locator('#hero').getAttribute('data-frame'),String(i<8?i:i-8));
   const stat=await page.locator('#hero').evaluate(c=>{const a=c.getContext('2d').getImageData(0,0,256,256).data;let pixels=0,h=2166136261;for(let k=0;k<a.length;k++){h=Math.imul(h^a[k],16777619);if(k%4===3&&a[k]>160)pixels++}return {pixels,hash:h>>>0}});
   assert(stat.pixels>500,profile.id+' empty frame '+i);frameHashes.push(stat.hash);
  }
  assert(new Set(frameHashes.slice(0,8)).size>=7,profile.id+' repeated walk frames');
  await page.screenshot({path:path.join(out,profile.id+'-frames.png'),fullPage:true});
  console.log('PASS frames: '+profile.id);
 }
 await page.locator('#size').selectOption('256');
 await page.setViewportSize({width:390,height:900});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 await page.emulateMedia({reducedMotion:'reduce'});await page.reload();await page.waitForFunction(()=>document.querySelectorAll('.pet-choice canvas[data-state]').length===12);
 assert.equal(await page.locator('#auto').getAttribute('aria-pressed'),'false');assert.equal(await page.locator('#pause').getAttribute('aria-pressed'),'true');
 assert.deepEqual(errors,[]);
 console.log('PASS:12 pets,240 visible frames, sleep/wake transitions, queued turn, slow motion, mobile, reduced motion; no JS errors');
 }finally{await browser.close();await new Promise(r=>server.close(r))}
})().catch(e=>{console.error(e);process.exitCode=1});
