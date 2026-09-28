const assert=require('node:assert/strict');
const path=require('node:path');
const {chromium}=require('playwright');
async function main() {
 const browser=await chromium.launch({headless:true,...(process.platform==='win32'?{channel:'msedge'}:{})});
 try {
  const page=await browser.newPage({viewport:{width:340,height:1000}});
  await page.setContent('<div id="bnr-equipment-shop"></div>');
  await page.evaluate(()=>{
   window.API_URL='https://fixture.invalid'; window.authToken=''; window.escapeHtml=s=>String(s).replaceAll('<','&lt;');
   window.fixture={success:true,ready:false,can_manage:false,items:[],inventory:[],reason:'offline',message:'Игра сейчас не на связи'};
   window.fetch=async()=>({ok:true,json:async()=>structuredClone(fixture)});
  });
  await page.addScriptTag({path:path.resolve(__dirname,'../Расширение/frontend/viewer-bannerlord-equipment.js')});
  await page.evaluate(()=>loadBannerlordEquipmentShop());
  assert(!(await page.locator('[data-bnr-eq-view="owned"]').innerText()).includes('· 0'),'unknown snapshot is not zero inventory');
  await page.locator('[data-bnr-eq-view="owned"]').click();
  assert.equal(await page.locator('[data-bnr-owned-slot]').count(),0,'unknown equipment must not show eleven empty slots');
  await page.evaluate(()=>{
   fixture.ready=true;
   fixture.party_inventory={available:false,reason:'hero_prisoner',message:'Герой в плену — багаж отряда недоступен'};
   fixture.inventory=[{owned_id:'body',item_id:'armor',name:'Мой доспех',slot:'body'}];
   return loadBannerlordEquipmentShop();
  });
  assert.equal(await page.locator('[data-bnr-owned-slot]').count(),11);
  assert((await page.locator('#bnr-equipment-shop').innerText()).includes('Надето на герое'));
  assert((await page.locator('#bnr-equipment-shop').innerText()).includes('багаж отряда недоступен'));
  assert(!(await page.locator('#bnr-equipment-shop').innerText()).includes('0 доступно'),'unavailable is not empty baggage');
  await page.evaluate(()=>{
   fixture.party_inventory={available:true,party_name:'Отряд Алисы'}; fixture.can_manage=true; fixture.reason=null;
   return loadBannerlordEquipmentShop();
  });
  assert((await page.locator('#bnr-equipment-shop').innerText()).includes('Багаж отряда'));
  assert((await page.locator('#bnr-equipment-shop').innerText()).includes('0 доступно'),'known empty equipment baggage is zero');
  console.log('PASS native inventory UI: unknown, captive equipment, unavailable baggage, known empty');
 } finally {await browser.close();}
}
main().catch(e=>{console.error(e);process.exitCode=1;});
