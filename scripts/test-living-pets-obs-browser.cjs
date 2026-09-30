const assert=require('assert'),fs=require('fs'),path=require('path'),http=require('http');
const {chromium}=require('C:/Users/Edward/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const profiles=require('../Расширение/frontend/pet-assets/living-pets-v1/profiles.json');
const root=path.resolve(__dirname,'../Расширение/frontend'),out=path.resolve(__dirname,'../dist/living-obs');
fs.mkdirSync(out,{recursive:true});
const viewer=(id,i)=>({username:'viewer_'+i,level:10+i,pet_type:'hatched',equipped:{body:{item_id:'skin_'+id}}});
(async()=>{
 const server=http.createServer((req,res)=>{const f=path.resolve(root,'.'+new URL(req.url,'http://localhost').pathname);if(!f.startsWith(root+path.sep)||!fs.existsSync(f)){res.writeHead(404);return res.end()}res.setHeader('Content-Type',f.endsWith('.js')?'application/javascript':f.endsWith('.png')?'image/png':f.endsWith('.json')?'application/json':f.endsWith('.css')?'text/css':'text/html');fs.createReadStream(f).pipe(res)});
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 const errors=[];
 try{
  const page=await browser.newPage({viewport:{width:1920,height:1080}});
  page.on('pageerror',e=>errors.push(e.message));
  let viewers=profiles.map((p,i)=>viewer(p.id,i)).concat(viewer('kimono',12));
  await page.route('**/api/**',r=>r.fulfill({contentType:'application/json',body:JSON.stringify(r.request().url().includes('/overlay/pets')?{success:true,enabled:true,viewers}:{success:true,active:false,events:[]})}));
  await page.clock.install();
  await page.goto('http://127.0.0.1:'+server.address().port+'/overlay.html?channel_id=98319857');
  await page.waitForFunction(()=>document.querySelectorAll('.pet-companion[data-render-mode="living"]').length===12);
  assert.equal(await page.locator('.pet-walk-frame').count(),2,'legacy pet stays present');
  await page.evaluate(()=>{
   document.body.style.background='#172235';
   window.seen={};new MutationObserver(()=>document.querySelectorAll('.pet-companion').forEach(c=>{
    const h=seen[c.dataset.petVariant]??={states:[],walk:[],scenes:[],actions:[],flips:[]};
    h.states.push(c.dataset.state);h.actions.push(c.dataset.action);h.flips.push(c.dataset.flip);
    if(c.dataset.state==='walk'&&c.dataset.action==='living')h.walk.push(c.dataset.pose);
    if(c.dataset.action==='scene')h.scenes.push(c.dataset.pose);
   })).observe(document.querySelector('#pets-strip'),{subtree:true,attributes:true});
   document.querySelectorAll('.pet-companion').forEach(c=>PetLiving.request(c,'idle'));
  });
  await page.clock.runFor(500);
  assert.equal(await page.locator('[data-action="greeting"]').count(),12);
  await page.screenshot({path:path.join(out,'01-greetings.png')});
  await page.clock.runFor(12500); // All independent signature scenes finish.
  await page.evaluate(()=>document.querySelectorAll('.pet-companion').forEach(c=>PetLiving.request(c,'walk')));
  await page.clock.runFor(6000);
  let seen=await page.evaluate(()=>seen);
  for(const p of profiles){assert(seen[p.id].states.includes('start'),p.id+' start');assert.equal(new Set(seen[p.id].walk).size,8,p.id+' complete gait');assert.equal(new Set(seen[p.id].scenes).size,6,p.id+' complete signature scene');}
  await page.screenshot({path:path.join(out,'02-walking.png')});
  await page.evaluate(()=>document.querySelectorAll('.pet-companion').forEach(c=>PetLiving.request(c,'sleep')));
  await page.clock.runFor(6500);
  assert.equal(await page.locator('[data-state="sleep"]').count(),12);
  const asleepX=await page.locator('.pet-companion').evaluateAll(cs=>cs.map(c=>c.closest('.pet-card').style.transform));
  await page.clock.runFor(2500);
  assert.deepEqual(await page.locator('.pet-companion').evaluateAll(cs=>cs.map(c=>c.closest('.pet-card').style.transform)),asleepX);
  await page.screenshot({path:path.join(out,'03-sleep.png')});
  // A level change reconstructs DOM; keep sleep state for the same viewer/skin.
  viewers[0].level++;
  await page.evaluate(()=>pollPets());await page.clock.runFor(150);
  assert.equal(await page.locator('[data-state="sleep"]').count(),12,'state survives poll rebuild');
  await page.evaluate(()=>document.querySelectorAll('.pet-companion').forEach((c,i)=>PetLiving.request(c,i===0?'sleep':'walk')));
  await page.clock.runFor(5000);
  assert.equal(await page.locator('.pet-companion').first().getAttribute('data-state'),'sleep','independent intent');
  seen=await page.evaluate(()=>seen);
  for(const p of profiles.slice(1))for(const s of ['stop','yawn','sit','sleep','wake','rise','start','walk'])assert(seen[p.id].states.includes(s),p.id+' '+s);
  // Motion and flips must stay inside the lane on both directions, including resize.
  await page.clock.runFor(25000);
  for(const width of [1920,1280,800]){
   await page.setViewportSize({width,height:1080});await page.clock.runFor(5000);
   const bounds=await page.locator('.pet-companion').evaluateAll(cs=>cs.map(c=>{const card=c.closest('.pet-card'),amp=parseFloat(card.style.getPropertyValue('--walk-amp')),x=new DOMMatrix(getComputedStyle(card).transform).m41,rect=c.getBoundingClientRect();return {id:c.dataset.petVariant,x,amp:amp*innerWidth/100,visualWidth:rect.width,scale:parseFloat(card.style.getPropertyValue('--depth-scale'))}}));
   for(const b of bounds){assert(b.x>=Math.min(0,b.amp)-.1&&b.x<=Math.max(0,b.amp)+.1,b.id+' lane');assert(Math.abs(b.visualWidth-128*b.scale)<.1,b.id+' scale');}
  }
  seen=await page.evaluate(()=>seen);
  for(const p of profiles.slice(1))for(const flip of ['true','false'])assert(seen[p.id].flips.includes(flip),p.id+' both directions');
  await page.setViewportSize({width:1920,height:1080});
  await page.evaluate(()=>document.querySelectorAll('.pet-companion').forEach(c=>PetLiving.request(c,'idle')));
  await page.clock.runFor(3000);
  await page.evaluate(()=>document.querySelectorAll('.pet-companion').forEach(c=>PetLiving.react(c)));
  await page.clock.runFor(100);assert.equal(await page.locator('[data-action="reaction"]').count(),12);
  await page.clock.runFor(1000);
  await page.emulateMedia({reducedMotion:'reduce'});await page.clock.runFor(250);
  assert.equal(await page.locator('[data-state="idle"][data-pose="0"]').count(),12);
  await page.emulateMedia({reducedMotion:'no-preference'});
  // Same user changes skin without changing level or name; other pets retain state.
  viewers[0].equipped.body.item_id='skin_frog_samurai';await page.evaluate(()=>pollPets());await page.clock.runFor(250);
  assert.equal(await page.locator('.pet-companion').first().getAttribute('data-pet-variant'),'frog_samurai');
  assert.equal(await page.locator('.pet-companion').first().getAttribute('data-action'),'greeting');
  viewers[0].equipped.body.item_id='skin_kimono';await page.evaluate(()=>pollPets());await page.clock.runFor(250);
  assert.equal(await page.locator('.pet-companion').count(),11);assert.equal(await page.locator('.pet-walk-frame').count(),4);
  // Missing one atlas: only the affected pet uses the previous renderer.
  await page.route('**/living-pets-v1/assets/frog_samurai/walk-8.png',r=>r.fulfill({status:404,body:''}));
  await page.reload();await page.clock.runFor(1000);
  await page.waitForFunction(()=>document.querySelectorAll('[data-render-mode="living"]').length===10);
  assert.equal(await page.locator('[data-pet-variant="frog_samurai"]').getAttribute('data-render-mode'),'fallback');
  assert(await page.locator('[data-pet-variant="frog_samurai"]').evaluate(c=>c.getContext('2d').getImageData(0,0,256,256).data.some((v,i)=>i%4===3&&v>0)));
  // Profiles outage must preserve all legacy animation, not throw or blank pets.
  await page.route('**/living-pets-v1/profiles.json*',r=>r.fulfill({status:503,body:''}));
  await page.reload();await page.clock.runFor(1000);
  await page.waitForFunction(()=>document.querySelectorAll('.pet-companion[data-pose]').length===11);
  assert.equal(await page.locator('[data-render-mode="fallback"]').count(),11);
  assert.deepEqual(errors,[]);
  fs.writeFileSync(path.join(out,'result.json'),JSON.stringify({tested:'actual overlay.html in Chromium, mocked read-only API; NOT OBS',pets:12,legacy:true,errors,states:seen},null,2));
  console.log('PASS: actual overlay.html, 12 simultaneous living pets + legacy; greeting, 8-frame gait, sleep/wake, independent state, directions, bounds, scale, reactions, skin/level changes, reduced motion, image/profile failures; no JS exceptions');
 }finally{await browser.close();await new Promise(r=>server.close(r))}
})().catch(e=>{console.error(e);process.exitCode=1});
