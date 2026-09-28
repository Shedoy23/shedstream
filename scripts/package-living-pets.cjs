const fs=require('fs'),path=require('path');
const sharp=require('C:/Users/Edward/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/sharp');
const root=path.resolve(__dirname,'..'),out=path.join(root,'Расширение/frontend/pet-assets/living-pets-v1');
async function analyse(src,rows){
 const meta=await sharp(src).metadata(),input=await sharp(src).resize(Math.ceil(meta.width/4)*4,Math.ceil(meta.height/rows)*rows,{kernel:'nearest'}).png().toBuffer();
 const {data,info}=await sharp(input).ensureAlpha().raw().toBuffer({resolveWithObject:true}),cw=info.width/4,bands=[];let start=-1,last=-1;
 for(let y=0;y<info.height;y++){let n=0;for(let x=0;x<info.width;x++)if(data[(y*info.width+x)*4+3]>160)n++;
 if(n>4){if(start<0)start=y;else if(y-last>5){bands.push([start,last]);start=y}last=y}}
 bands.push([start,last]);
 while(bands.length>rows){let k=0,gap=Infinity;for(let i=0;i<bands.length-1;i++){const d=bands[i+1][0]-bands[i][1];if(d<gap){gap=d;k=i}}bands.splice(k,2,[bands[k][0],bands[k+1][1]])}
 if(bands.length!==rows)throw Error('Row gutters missing: '+src);
 const boxes=[];
 for(let i=0;i<rows*4;i++){const band=bands[Math.floor(i/4)];let l=cw,t=info.height,r=0,b=0;
 for(let y=band[0];y<=band[1];y++)for(let x=0;x<cw;x++)if(data[(y*info.width+i%4*cw+x)*4+3]>160){l=Math.min(l,x);r=Math.max(r,x);t=Math.min(t,y);b=Math.max(b,y)}
 if(r<=l||b<=t)throw Error('Empty cell '+i);boxes.push({l,t,r,b})}
 const left=Math.max(0,Math.min(...boxes.map(b=>b.l))-3),right=Math.min(cw-1,Math.max(...boxes.map(b=>b.r))+3);
 return {src,input,info,cw,boxes,bands,left,width:right-left+1,scale:220/(boxes[0].b-boxes[0].t+7)};
}
async function pack(a,scale,file){
 const frames=[];
 for(let i=0;i<a.boxes.length;i++){const top=Math.max(0,a.boxes[i].t-3),height=Math.min(a.info.height,a.boxes[i].b+4)-top,w=Math.round(a.width*scale),h=Math.round(height*scale);
 const crop=await sharp(a.input).extract({left:i%4*a.cw+a.left,top,width:a.width,height}).resize(w,h,{kernel:'nearest'}).png().toBuffer();
 frames.push({input:await sharp({create:{width:256,height:256,channels:4,background:'#00000000'}}).composite([{input:crop,left:Math.round((256-w)/2),top:248-h}]).png().toBuffer(),left:i*256,top:0})}
 await sharp({create:{width:256*frames.length,height:256,channels:4,background:'#00000000'}}).composite(frames).png().toFile(file);
}
(async()=>{
 const sources=JSON.parse(fs.readFileSync(process.argv[2],'utf8')),manifest=[];
 for(const item of sources){
 if(!item.walk||!item.behaviour){if(process.argv.includes('--partial'))continue;throw Error('Missing sheet '+item.id)}
 const dir=path.join(out,'assets',item.id);fs.mkdirSync(dir,{recursive:true});
 const walk=await analyse(item.walk,2),behaviour=await analyse(item.behaviour,3);
 const shrink=Math.min(1,...[walk,behaviour].flatMap(a=>[234/(a.width*a.scale),232/(Math.max(...a.boxes.map(b=>b.b-b.t+7))*a.scale)]));
 for(const [kind,a] of [['walk',walk],['behaviour',behaviour]]){
 fs.copyFileSync(a.src,path.join(dir,'source-'+kind+'.png'));
 await pack(a,a.scale*shrink,path.join(dir,kind==='walk'?'walk-8.png':'behaviour-12.png'))}
 manifest.push({id:item.id,name:item.name,frames:20,scale:[walk.scale*shrink,behaviour.scale*shrink],bands:[walk.bands,behaviour.bands]});console.log('Packed '+item.id);
 }
 const mage=path.join(out,'assets/lantern_mage');fs.mkdirSync(mage,{recursive:true});
 for(const file of ['walk-8.png','behaviour-12.png'])fs.copyFileSync(path.join(root,'Расширение/frontend/pet-assets/mage-behaviour-v1',file),path.join(mage,file));
 manifest.push({id:'lantern_mage',name:'Сонный колдунчик',frames:20,existingApprovedPrototype:true});
 fs.writeFileSync(path.join(out,'manifest.json'),JSON.stringify({prototype:true,pets:manifest},null,2));
})().catch(e=>{console.error(e);process.exitCode=1});
