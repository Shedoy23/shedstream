const assert=require('assert');
const fs=require('fs');
const path=require('path');
const http=require('http');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'C:/Users/Edward/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const root=path.resolve(__dirname,'../Расширение/frontend');
const fantasy=process.argv.includes('--fantasy');
const out=path.resolve(__dirname,fantasy?'../dist/pets-fantasy-20260926':'../dist/pets-collection-20260926');
const ids=fantasy?require('./pet-fantasy-spec.json').items.map(x=>x[0]):['wayfarer','crimson_knight','colony_engineer','lantern_mage','shadow_rogue','rain_fisher'];
async function main(){
 const sharp=require('C:/Users/Edward/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/sharp');
 for(const id of ids.filter(id=>id!=='blanket_ghost')){
  const dir=path.join(root,'pet-assets/v2',id);
  for(let frame=0;frame<6;frame++){
   const region={left:frame*256,top:0,width:256,height:256};
   const before=await sharp(path.join(dir,'animation.png')).extract(region).raw().toBuffer();
   const after=await sharp(path.join(dir,'animation-v2.png')).extract(region).raw().toBuffer();
   if(frame===2)assert(!before.equals(after),id+' opposite contact must change');
   else assert(before.equals(after),id+' non-target frame changed');
  }
 }
 require(path.join(root,'pet-assets/companions-v1/overlay-pets.js'));
 const pose=global.PetCompanions.poseAt;
 assert.deepEqual(pose(.4,1,1,'lantern_mage',false),{frame:1,flip:false});
 assert.equal(pose(.9,1,1,'lantern_mage',false).flip,true);
 assert.equal(pose(.4,1,-1,'lantern_mage',false).flip,true);
 assert.equal(pose(.6,1,1,'lantern_mage',false).frame,4);
 assert.equal(pose(.75,1,1,'lantern_mage',false).frame,5);
 const server=http.createServer((req,res)=>{const url=new URL(req.url,'http://localhost');const f=path.resolve(root,'.'+decodeURIComponent(url.pathname));if(!f.startsWith(root+path.sep)||!fs.existsSync(f)){res.writeHead(404);return res.end();}res.setHeader('Content-Type',f.endsWith('.png')?'image/png':f.endsWith('.js')?'application/javascript':f.endsWith('.json')?'application/json':f.endsWith('.css')?'text/css':'text/html');fs.createReadStream(f).pipe(res)});
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const base='http://127.0.0.1:'+server.address().port;
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 const page=await browser.newPage({viewport:{width:1120,height:850}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 try{
  // Exercise the retained renderer explicitly. Living OBS integration has its
  // own multi-pet suite; seeking the removed CSS clock would not test it.
  if(process.argv.includes('--legacy-render')) await page.route('**/living-pets-v1/**',route=>route.fulfill({status:404,body:''}));
  await page.goto(base+'/pet-assets/'+(fantasy?'fantasy-v1':'companions-v1')+'/preview.html');
  await page.getByRole('button',{name:'Спать',exact:true}).click();
  await page.waitForFunction(()=>[...document.querySelectorAll('.sprite')].every(s=>s.dataset.frame==='4'));
  await page.screenshot({path:path.join(out,'collection-sleep.png'),fullPage:true});
  await page.getByRole('button',{name:'Привет',exact:true}).click();
  await page.getByRole('button',{name:'Светлый фон',exact:true}).click();
  await page.screenshot({path:path.join(out,'collection-light.png'),fullPage:true});
  for(const frame of [1,2]){
   await page.getByRole('button',{name:'Шаг '+frame,exact:true}).click();
   await page.waitForFunction(f=>[...document.querySelectorAll('.sprite')].every(s=>Number(s.dataset.frame)===f),frame);
   assert(await page.evaluate(()=>[...document.querySelectorAll('.sprite')].every(s=>s.style.backgroundImage.includes('animation-v2')||s.style.backgroundImage.includes('blanket_ghost'))));
   await page.screenshot({path:path.join(out,'walk-step-'+frame+'.png'),fullPage:true});
  }
  await page.getByRole('button',{name:'Замедлить ×4',exact:true}).click();
  assert.equal(await page.evaluate(()=>speed),.25);
  await page.getByRole('button',{name:'Обычная скорость',exact:true}).click();
  await page.getByRole('button',{name:'Фирменные сценки',exact:true}).click();
  for(let frame=0;frame<6;frame++){
   await page.evaluate(f=>{t=(f+.25)*.7;paused=true},frame);
   await page.waitForFunction(f=>[...document.querySelectorAll('.sprite')].every(s=>s.dataset.action==='scene'&&Number(s.dataset.frame)===f),frame);
  }
  await page.screenshot({path:path.join(out,'signature-scenes-light.png'),fullPage:true});
  await page.setViewportSize({width:390,height:850});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  let viewers=ids.map((id,i)=>({username:'viewer_'+i,level:10+i,pet_type:'hatched',equipped:{body:{item_id:'skin_'+id}}}));
  await page.route('**/api/**',route=>route.fulfill({contentType:'application/json',body:JSON.stringify(route.request().url().includes('/overlay/pets')?{success:true,enabled:true,viewers}:{success:true,active:false,events:[]})}));
  await page.setViewportSize({width:1920,height:1080});
  await page.goto(base+'/overlay.html?channel_id=98319857');
  await page.waitForFunction(()=>document.querySelectorAll('.pet-companion[data-pose]').length===6);
  await page.evaluate(()=>document.querySelectorAll('.pet-card').forEach(c=>{const a=c.getAnimations().find(a=>a.animationName==='pet-walk');const tm=a.effect.getTiming();a.pause();a.currentTime=Number(tm.delay)+Number(tm.duration)*.4;}));
  await page.waitForFunction(()=>[...document.querySelectorAll('.pet-companion')].every(c=>['1','2'].includes(c.dataset.pose)));
  await page.screenshot({path:path.join(out,'overlay-six.png')});
  await page.waitForTimeout(3100); // Initial greeting has priority over signature scenes.
  for(let frame=0;frame<6;frame++){
   await page.evaluate(f=>document.querySelectorAll('.pet-companion').forEach(canvas=>{
    const seed=Number(canvas.dataset.sceneSeed),a=canvas.closest('.pet-card').getAnimations().find(a=>a.animationName==='pet-walk'),tm=a.effect.getTiming();
    a.pause();a.currentTime=Number(tm.delay)+Number(tm.duration)*(seed%2+.06+(seed%12)*.01)+(f+.25)*700;
   }),frame);
   await page.waitForFunction(f=>[...document.querySelectorAll('.pet-companion')].every(c=>c.dataset.action==='scene'&&Number(c.dataset.pose)===f),frame);
  }
  assert(await page.evaluate(()=>[...document.querySelectorAll('.pet-companion')].every(c=>c.getContext('2d').getImageData(0,0,256,256).data.some((v,i)=>i%4===3&&v>0))));
  await page.screenshot({path:path.join(out,'overlay-signature-scenes.png')});
  await page.emulateMedia({reducedMotion:'reduce'});
  await page.waitForFunction(()=>[...document.querySelectorAll('.pet-companion')].every(c=>c.dataset.action==='base'&&c.dataset.pose==='0'));
  await page.emulateMedia({reducedMotion:'no-preference'});
  // Same viewer, same name and level, only body skin changes: must redraw immediately.
  viewers=[{username:'same_viewer',level:20,pet_type:'hatched',equipped:{body:{item_id:'skin_lantern_mage'}}}];
  await page.evaluate(()=>pollPets());
  await page.waitForFunction(()=>document.querySelector('.pet-companion')?.dataset.petVariant==='lantern_mage');
  viewers[0].equipped.body.item_id='skin_'+ids[0];
  await page.evaluate(()=>pollPets());
  assert.equal(await page.locator('.pet-companion').getAttribute('data-pet-variant'),ids[0]);
  viewers[0].equipped.body.item_id='skin_kimono';
  await page.evaluate(()=>pollPets());
  assert.equal(await page.locator('.pet-companion').count(),0);
  assert.equal(await page.locator('.pet-walk-frame').count(),2);
  assert.equal(errors.length,0,errors.join('\n'));
  console.log('PASS: six rendered, signature sequence 0-5 in preview and OBS, reduced motion, light background, mobile fit, walking/turns/sleep/cheer, live skin switch, legacy fallback; no JS errors');
 }finally{await browser.close();await new Promise(r=>server.close(r));}
}
main().catch(e=>{console.error(e);process.exitCode=1});
