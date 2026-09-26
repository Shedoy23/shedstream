// Mechanical atlas slicing/scale/packing only; artwork is generated with imagegen.
const fs = require('fs');
const path = require('path');
const sharp = require(process.env.SHARP_MODULE || 'C:/Users/Edward/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/sharp');
const root = path.resolve(__dirname, '..');
const source = process.argv[2];
if (!source) throw new Error('Pass directory containing generated original PNGs');
const spec = process.argv[3] ? JSON.parse(fs.readFileSync(process.argv[3], 'utf8')) : null;
const items = spec ? spec.items : [
  ['wayfarer','Странник','exec-15d01c90-456d-428c-8dc6-a89b7c8c7ccd.png',512],
  ['crimson_knight','Багряный рыцарь','exec-6bb4f409-e40e-4650-9c2d-a1b1d411dce7.png',512],
  ['colony_engineer','Инженер','exec-a365c78b-feb4-479c-a0dd-74f9624b2dbc.png',512],
  ['lantern_mage','Сонный колдунчик','exec-30688c9b-643a-4526-a640-1e50cac8564b.png',536],
  ['shadow_rogue','Разбойник','exec-4dcf42d3-d0fc-4fb7-b59f-e1e09850939b.png',512],
  ['rain_fisher','Рыбак','exec-737174b2-af98-4a60-879c-44ed0ae0fa4d.png',512],
];
const names = ['south','east','walk-2','wave','sleep','cheer'];
async function main() {
  const manifest = [];
  for (const [id,name,file,split] of items) {
    const input = path.join(source,file);
    const raw = await sharp(input).ensureAlpha().raw().toBuffer({resolveWithObject:true});
    if(raw.info.width!==1536||raw.info.height!==1024)throw new Error('Unexpected atlas size '+file);
    const boxes=[];
    for(let i=0;i<6;i++) {
      const x0=(i%3)*512,y0=i<3?0:split,y1=i<3?split:1024;
      let left=x0+512,top=y1,right=x0,bottom=y0;
      for(let y=y0;y<y1;y++) for(let x=x0;x<x0+512;x++) {
        if(raw.data[(y*1536+x)*4+3] < 160) continue;
        left=Math.min(left,x);right=Math.max(right,x);top=Math.min(top,y);bottom=Math.max(bottom,y);
      }
      if(right<=left||bottom<=top)throw new Error('Empty pose '+id+' '+i);
      boxes.push({left:Math.max(x0,left-6),top:Math.max(y0,top-6),width:Math.min(x0+511,right+6)-Math.max(x0,left-6)+1,height:Math.min(y1-1,bottom+6)-Math.max(y0,top-6)+1});
    }
    const scale=Math.min(226/Math.max(...boxes.map(b=>b.height)),236/Math.max(...boxes.map(b=>b.width)));
    const out=path.join(root,'Расширение/frontend/pet-assets/v2',id);
    fs.mkdirSync(out,{recursive:true});
    const archive=path.join(root,spec ? spec.archive : 'dist/pets-collection-20260926/sources');
    fs.mkdirSync(archive,{recursive:true});fs.copyFileSync(input,path.join(archive,id+'.png'));
    const sprites=[];
    for(let i=0;i<6;i++) {
      const b=boxes[i], w=Math.round(b.width*scale),h=Math.round(b.height*scale);
      const pose=await sharp(input).extract(b).resize(w,h,{kernel:'nearest'}).png().toBuffer();
      const frame=await sharp({create:{width:256,height:256,channels:4,background:{r:0,g:0,b:0,alpha:0}}}).composite([{input:pose,left:Math.round((256-w)/2),top:248-h}]).png().toBuffer();
      fs.writeFileSync(path.join(out,names[i]+'.png'),frame);sprites.push(frame);
    }
    await sharp(sprites[1]).flop().png().toFile(path.join(out,'west.png'));
    await sharp({create:{width:1536,height:256,channels:4,background:{r:0,g:0,b:0,alpha:0}}}).composite(sprites.map((input,i)=>({input,left:i*256,top:0}))).png().toFile(path.join(out,'animation.png'));
    manifest.push({id,name,rarity:'rare',price:500000,frames:names,boxes,source:file});
    console.log(id+' packed');
  }
  const dir=path.join(root,'Расширение/frontend/pet-assets',spec ? spec.collection : 'companions-v1');fs.mkdirSync(dir,{recursive:true});
  fs.writeFileSync(path.join(dir,'manifest.json'),JSON.stringify(manifest,null,2));
}
main().catch(e=>{console.error(e);process.exitCode=1;});
