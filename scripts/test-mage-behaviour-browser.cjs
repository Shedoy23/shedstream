const assert=require('assert'),fs=require('fs'),path=require('path'),http=require('http');
const {chromium}=require('C:/Users/Edward/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
(async()=>{
 const folder=path.resolve(__dirname,'../Расширение/frontend/pet-assets/mage-behaviour-v1');
 const server=http.createServer((req,res)=>{const f=path.resolve(folder,'.'+new URL(req.url,'http://localhost').pathname);if(!f.startsWith(folder+path.sep)||!fs.existsSync(f)){res.writeHead(404);return res.end()}res.setHeader('Content-Type',f.endsWith('.js')?'application/javascript':f.endsWith('.png')?'image/png':f.endsWith('.json')?'application/json':'text/html');fs.createReadStream(f).pipe(res)});
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const browser=await chromium.launch({headless:true,channel:'msedge'}),out=path.resolve(__dirname,'../dist/pet-scenes-20260926');fs.mkdirSync(out,{recursive:true});
 try{
  const page=await browser.newPage({viewport:{width:1120,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(process.argv[2]||'http://127.0.0.1:'+server.address().port+'/preview.html');
  await page.waitForFunction(()=>document.querySelectorAll('.frame').length===20);
  await page.evaluate(()=>{window.states=[];new MutationObserver(()=>{const s=document.querySelector('#hero').dataset.state;if(states.at(-1)!==s)states.push(s)}).observe(document.querySelector('#hero'),{attributes:true,attributeFilter:['data-state']})});
  await page.getByRole('button',{name:'Гулять',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#hero').dataset.state==='walk');
  await page.screenshot({path:path.join(out,'mage-behaviour-walk.png'),fullPage:true});
  await page.getByRole('button',{name:'Спать',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#hero').dataset.state==='sleep');
  const states=await page.evaluate(()=>window.states);
  for(const s of ['start','walk','stop','yawn','sit','sleep'])assert(states.includes(s),s+' not observed');
  await page.getByRole('button',{name:'Светлый фон',exact:true}).click();
  await page.screenshot({path:path.join(out,'mage-behaviour-sleep.png'),fullPage:true});
  await page.getByRole('button',{name:'Гулять',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#hero').dataset.state==='walk');
  const waking=await page.evaluate(()=>window.states);assert(waking.includes('wake'));assert(waking.includes('rise'));
  await page.getByRole('button',{name:'В другую сторону',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#hero').style.transform.includes('scaleX(-1)'));
  await page.getByRole('button',{name:'Замедлить ×4',exact:true}).click();
  assert.equal(await page.getByRole('button',{name:'Замедлить ×4',exact:true}).getAttribute('aria-pressed'),'true');
  await page.locator('summary').click();
  const frames=page.locator('.frame');
  for(let i=0;i<20;i++){await frames.nth(i).click();assert.equal(await page.locator('#hero').getAttribute('data-frame'),String(i<8?i:i-8));assert(await page.locator('#hero').evaluate(c=>c.getContext('2d').getImageData(0,0,256,256).data.some((v,i)=>i%4===3&&v>0)))}
  await page.screenshot({path:path.join(out,'mage-behaviour-all-frames.png'),fullPage:true});
  await page.setViewportSize({width:390,height:900});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  await page.emulateMedia({reducedMotion:'reduce'});await page.reload();await page.waitForFunction(()=>document.querySelectorAll('.frame').length===20);
  assert.equal(await page.getByRole('button',{name:'Продолжить',exact:true}).getAttribute('aria-pressed'),'true');
  assert.equal(await page.getByRole('button',{name:'Сам по себе',exact:true}).getAttribute('aria-pressed'),'false');
  assert.deepEqual(errors,[]);
  console.log('PASS: walk-stop-sleep-wake transitions, turn after stop, all20 frames, mobile, reduced motion; no JS errors');
 }finally{await browser.close();await new Promise(r=>server.close(r))}
})().catch(e=>{console.error(e);process.exitCode=1});
