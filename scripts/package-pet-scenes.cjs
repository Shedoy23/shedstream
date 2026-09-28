// Mechanical slicing only: all artwork comes from built-in imagegen.
const fs=require('fs'),path=require('path');
const sharp=require(process.env.SHARP_MODULE||'C:/Users/Edward/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/sharp');
const root=path.resolve(__dirname,'..');
const spec=JSON.parse(fs.readFileSync(path.join(root,'scripts/pet-scenes-spec.json'),'utf8'));
async function main(){
 const manifest=[];
 for(const item of spec){
  const input=path.join(process.argv[2],item.source);
  const {data,info}=await sharp(input).ensureAlpha().raw().toBuffer({resolveWithObject:true});
  if(info.width!==1536||info.height!==1024)throw Error('Unexpected size: '+item.id);
  const boxes=[];
  for(let i=0;i<6;i++){
   let l=512,t=512,r=0,b=0;
   for(let y=0;y<512;y++)for(let x=0;x<512;x++)if(data[(((i<3?0:512)+y)*1536+(i%3)*512+x)*4+3]>=160){l=Math.min(l,x);r=Math.max(r,x);t=Math.min(t,y);b=Math.max(b,y);}
   if(l>=r||t>=b)throw Error('Empty pose');
   boxes.push({l,t,r,b});
  }
  // One scale and horizontal crop for the whole scene; props never recenter the body.
  const left=Math.max(0,Math.min(...boxes.map(b=>b.l))-5),right=Math.min(511,Math.max(...boxes.map(b=>b.r))+5);
  const height=Math.min(512,Math.max(...boxes.map(b=>b.b-b.t+1))+10),width=right-left+1;
  const scale=Math.min(236/width,226/height),w=Math.round(width*scale);
  const frames=[];
  for(let i=0;i<6;i++){
   const top=Math.max(0,boxes[i].t-5),bottom=Math.min(511,boxes[i].b+5),h=Math.round((bottom-top+1)*scale);
   const pose=await sharp(input).extract({left:(i%3)*512+left,top:(i<3?0:512)+top,width,height:bottom-top+1}).resize(w,h,{kernel:'nearest'}).png().toBuffer();
   frames.push(await sharp({create:{width:256,height:256,channels:4,background:'#00000000'}}).composite([{input:pose,left:Math.round((256-w)/2),top:248-h}]).png().toBuffer());
  }
  const output=path.join(root,'Расширение/frontend/pet-assets/v2',item.id,'scene-v1.png');
  await sharp({create:{width:1536,height:256,channels:4,background:'#00000000'}}).composite(frames.map((input,i)=>({input,left:i*256,top:0}))).png().toFile(output);
  const archive=path.join(root,'dist/pet-scenes-20260926/sources');fs.mkdirSync(archive,{recursive:true});fs.copyFileSync(input,path.join(archive,item.id+'.png'));
  manifest.push({...item,frames:6,frameMs:700,boxes});console.log(item.id+' packed');
 }
 const out=path.join(root,'Расширение/frontend/pet-assets/scenes-v1');fs.mkdirSync(out,{recursive:true});
 fs.writeFileSync(path.join(out,'manifest.json'),JSON.stringify(manifest,null,2));
}
main().catch(e=>{console.error(e);process.exitCode=1});
