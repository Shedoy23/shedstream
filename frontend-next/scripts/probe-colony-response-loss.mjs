// Diagnostic transport probe only: one browser fetch, local fixture, no app.
import http from 'node:http';
import {chromium} from 'playwright';
let mode='empty',received=[];
const server=http.createServer(async(req,res)=>{
  if(req.method!=='POST'){res.setHeader('Content-Type','text/html');res.end('<title>Local transport probe</title>');return;}
  let body='';for await(const part of req)body+=part;
  received.push({mode,body});
  if(mode==='empty'){res.destroy();return;}
  res.writeHead(200,{'Content-Type':'application/json','Content-Length':'100','Connection':'close'});
  res.write('{"success":');
  setTimeout(()=>res.destroy(),50);
});
await new Promise(resolve=>server.listen(4191,'127.0.0.1',resolve));
let browser;
try{
  browser=await chromium.launch({headless:true,chromiumSandbox:true});
  const context=await browser.newContext();await context.route('**/*',route=>route.continue());
  const page=await context.newPage();await page.goto('http://127.0.0.1:4191/');
  const results=[];
  for(const method of ['empty','truncated']){
    mode=method;received=[];
    const outcome=await page.evaluate(async()=>{
      let calls=0;
      try{calls++;const r=await fetch('/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({client_action_id:'single-local-call'})});await r.json();return {calls,unexpected:'success'};}
      catch(error){return {calls,error:String(error)};}
    });
    results.push({mode,received:[...received],outcome});
  }
  console.log(JSON.stringify({browser:browser.version(),sandbox:true,results},null,2));
}finally{await browser?.close();await new Promise(resolve=>server.close(resolve));}
