const fs=require('fs'),path=require('path'),assert=require('assert/strict');
// Browser scratch files belong to the writable test workspace.
const scratch=path.resolve('tests/.tmp/browser');fs.mkdirSync(scratch,{recursive:true});process.env.TEMP=scratch;process.env.TMP=scratch;
const {chromium}=require('C:/Users/Edward/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'});const page=await browser.newPage({viewport:{width:1000,height:700},reducedMotion:'reduce'});const errors=[];
 page.on('pageerror',e=>errors.push(e.message));await page.goto('http://127.0.0.1:17863/?demo=1');
 await page.locator('#thought').waitFor();await page.screenshot({path:'evidence/overlay-siege.png'});
 await page.getByRole('button',{name:'Победа',exact:true}).click();assert.equal(await page.locator('#outcome').innerText(),'ПОБЕДА');await page.screenshot({path:'evidence/overlay-victory.png'});
 await page.setViewportSize({width:420,height:760});await page.getByRole('button',{name:'Длинная мысль'}).click();
 assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));assert.ok(await page.locator('#thought').evaluate(e=>e.scrollHeight<=e.clientHeight+1));await page.screenshot({path:'evidence/overlay-mobile.png'});
 await page.getByRole('button',{name:'ИИ выключен'}).click();assert.ok(await page.locator('#card').isHidden());
 // Exercise live rendering with synthetic API input, including HTML injection.
 let visible=true;
 await page.route('**/api/state',route=>route.fulfill({contentType:'application/json',body:JSON.stringify({thoughts:{visible,thought:'<img src=x onerror=alert(1)>',previous:[],age:1},battle:null})}));
 await page.goto('http://127.0.0.1:17863/');await page.waitForFunction(()=>document.querySelector('#thought').textContent.includes('<img'));
 assert.equal(await page.locator('#thought img').count(),0);visible=false;await page.waitForFunction(()=>document.querySelector('#card').hidden);
 assert.deepEqual(errors,[]);fs.writeFileSync('evidence/browser-check.json',JSON.stringify({passed:true,checks:['siege demo','victory','mobile 420px no horizontal overflow','long text','AI off hides','literal untrusted text','live polling updates'],pageErrors:errors},null,2));await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
