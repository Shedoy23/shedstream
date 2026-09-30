const fs=require('fs'),path=require('path');
const sharp=require('C:/Users/Edward/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/sharp');
(async()=>{
 const src=process.argv[2],root=path.resolve(__dirname,'..'),out=path.join(root,'Расширение/frontend/pet-assets/mage-behaviour-v1');
 fs.mkdirSync(out,{recursive:true});fs.copyFileSync(src,path.join(out,'source.png'));
 fs.copyFileSync(path.join(root,'Расширение/frontend/pet-assets/mage-walk-study-v1/walk-8.png'),path.join(out,'walk-8.png'));
 const meta=await sharp(src).metadata(),input=await sharp(src).resize(Math.ceil(meta.width/4)*4,Math.ceil(meta.height/3)*3,{kernel:'nearest'}).png().toBuffer();
 const {data,info}=await sharp(input).ensureAlpha().raw().toBuffer({resolveWithObject:true}),cw=info.width/4,boxes=[],bands=[];
 // Generated rows are not perfectly equally spaced: locate blank gutters first.
 let start=-1,last=-1;
 for(let y=0;y<info.height;y++){let n=0;for(let x=0;x<info.width;x++)if(data[(y*info.width+x)*4+3]>160)n++;
  if(n>4){if(start<0)start=y;else if(y-last>5){bands.push([start,last]);start=y}last=y}}
 bands.push([start,last]);if(bands.length!==3)throw Error('Expected three separated sprite rows');
 for(let i=0;i<12;i++){const band=bands[Math.floor(i/4)];let l=cw,t=info.height,r=0,b=0;
  for(let y=band[0];y<=band[1];y++)for(let x=0;x<cw;x++)if(data[(y*info.width+i%4*cw+x)*4+3]>160){l=Math.min(l,x);r=Math.max(r,x);t=Math.min(t,y);b=Math.max(b,y)}
  if(r<=l||b<=t)throw Error('Empty cell');boxes.push({l,t,r,b})}
 const left=Math.max(0,Math.min(...boxes.map(b=>b.l))-3),right=Math.min(cw-1,Math.max(...boxes.map(b=>b.r))+3),width=right-left+1,scale=Math.min(234/width,226/Math.max(...boxes.map(b=>b.b-b.t+7)));
 const frames=[];
 for(let i=0;i<12;i++){const top=Math.max(0,boxes[i].t-3),height=Math.min(info.height,boxes[i].b+4)-top,w=Math.round(width*scale),h=Math.round(height*scale);
 const crop=await sharp(input).extract({left:i%4*cw+left,top,width,height}).resize(w,h,{kernel:'nearest'}).png().toBuffer();
 frames.push({input:await sharp({create:{width:256,height:256,channels:4,background:'#00000000'}}).composite([{input:crop,left:Math.round((256-w)/2),top:248-h}]).png().toBuffer(),left:i*256,top:0})}
 await sharp({create:{width:3072,height:256,channels:4,background:'#00000000'}}).composite(frames).png().toFile(path.join(out,'behaviour-12.png'));
 fs.writeFileSync(path.join(out,'manifest.json'),JSON.stringify({prototype:true,walkingFrames:8,behaviourFrames:12,cell:256,source:path.basename(src),scale,bands,boxes},null,2));
 console.log('Packed twelve poses at one scale; sleeping poses keep natural seated height');
})().catch(e=>{console.error(e);process.exitCode=1});
