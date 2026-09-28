// Mechanically normalize generated opposite-contact sprites and repack atlas.
const fs=require('fs'),path=require('path');
const sharp=require(process.env.SHARP_MODULE||'C:/Users/Edward/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/sharp');
const root=path.resolve(__dirname,'..');
async function bounds(input){
 const {data,info}=await sharp(input).ensureAlpha().raw().toBuffer({resolveWithObject:true});
 let l=info.width,t=info.height,r=0,b=0;
 for(let y=0;y<info.height;y++)for(let x=0;x<info.width;x++)if(data[(y*info.width+x)*4+3]>=160){l=Math.min(l,x);r=Math.max(r,x);t=Math.min(t,y);b=Math.max(b,y);}
 if(l>=r||t>=b)throw Error('Empty sprite');
 return {left:l,top:t,width:r-l+1,height:b-t+1};
}
async function main(){
 const spec=JSON.parse(fs.readFileSync(path.join(root,'scripts/pet-walk-fix-spec.json'),'utf8'));
 for(const {id,source} of spec){
  const dir=path.join(root,'Расширение/frontend/pet-assets/v2',id),input=path.join(process.argv[2],source);
  const b=await bounds(input),a=await bounds(path.join(dir,'east.png'));
  const scale=Math.min(a.height/b.height,236/b.width),w=Math.round(b.width*scale),h=Math.round(b.height*scale);
  const crop=await sharp(input).extract(b).resize(w,h,{kernel:'nearest'}).png().toBuffer();
  const frame=await sharp({create:{width:256,height:256,channels:4,background:'#00000000'}}).composite([{input:crop,left:Math.round((256-w)/2),top:a.top+a.height-h}]).png().toBuffer();
  fs.writeFileSync(path.join(dir,'walk-opposite-v2.png'),frame);
  const original=fs.readFileSync(path.join(dir,'animation.png'));
  // Replace only frame index 2; preserve all other original frames byte-for-pixel.
  const atlas=await sharp(original).ensureAlpha().raw().toBuffer();
  const replacement=await sharp(frame).ensureAlpha().raw().toBuffer();
  for(let y=0;y<256;y++)replacement.copy(atlas,(y*1536+512)*4,y*256*4,(y+1)*256*4);
  await sharp(atlas,{raw:{width:1536,height:256,channels:4}}).png().toFile(path.join(dir,'animation-v2.png'));
  const archive=path.join(root,'dist/pet-scenes-20260926/walk-sources');fs.mkdirSync(archive,{recursive:true});fs.copyFileSync(input,path.join(archive,id+'.png'));
  console.log(id+' opposite contact packed');
 }
}
main().catch(e=>{console.error(e);process.exitCode=1});
