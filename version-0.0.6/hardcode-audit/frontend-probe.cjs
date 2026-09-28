// Read-only reproduction of current frontend behavior, not a passing product test.
// Expected defects are assertions; exit 0 means reproduced, not fixed.
// Run from any cwd: node <this file>. No network or runtime files modified.
'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../..');
const sourcePath=path.join(root,'Расширение/frontend/viewer-bannerlord.js');
const source=fs.readFileSync(sourcePath,'utf8');
const start=source.indexOf('const BNR_SKILLS = [');
const end=source.indexOf('// ===== Workshops (',start);
assert(start>=0 && end>start,'Could not locate current progression source');
const block=source.slice(start,end);
assert(block.includes('function loadBannerlordProgression()'),'Renderer missing');
const results=[];
function run(name,skills,attributes){
  let html='';
  const slot={querySelectorAll:()=>[]};
  const context={document:{getElementById:()=>slot},
    _bannerlordLastHero:{has_hero:true,skills,attributes},console,
    escapeHtml:String,_fmtK:String,
    _smartInnerHTML:(_el,value)=>{html=value;return false;}
  };
  vm.createContext(context);
  let error=null;
  try {vm.runInContext(block+'\nloadBannerlordProgression();',context);}
  catch(e){error={name:e.name,message:e.message};}
  return {name,html,error};
}
const unknown=run('unknown_skill',[{skill_key:'ModMagic',label:'Mod Magic',level:99,focus:1}],{});
assert.equal(unknown.error,null);
assert(!unknown.html.includes('ModMagic') && !unknown.html.includes('Mod Magic'),'Unknown skill unexpectedly supported: reassess finding');
assert(unknown.html.includes('Одноручное'),'Expected fabricated vanilla row missing: reassess finding');
results.push({scenario:unknown.name,expected_defect_reproduced:true,shows_mod_skill:false,shows_absent_vanilla_skill:true});
for(const [name,skills,attrs] of [
 ['focus_6',[{skill_key:'OneHanded',level:99,focus:6}],{}],
 ['attribute_11',[],{Vigor:11}]
]){
 const result=run(name,skills,attrs);
 assert.equal(result.error?.name,'RangeError','Expected current range failure: reassess finding');
 results.push({scenario:name,expected_defect_reproduced:true,error:result.error});
}
const equipmentSource=fs.readFileSync(path.join(root,'Расширение/frontend/viewer-bannerlord-equipment.js'),'utf8');
const statStart=equipmentSource.indexOf('    const statNames = ');
const statEnd=equipmentSource.indexOf('    let snapshot',statStart);
const funcsStart=equipmentSource.indexOf('    function stats(item)');
const funcsEnd=equipmentSource.indexOf('    function itemHtml(',funcsStart);
assert(statStart>=0 && statEnd>statStart && funcsStart>=0 && funcsEnd>funcsStart,'Equipment stat renderer changed');
const eqContext={escapeHtml:String};
vm.createContext(eqContext);
vm.runInContext(equipmentSource.slice(statStart,statEnd)+'\nconst text=String;\n'+equipmentSource.slice(funcsStart,funcsEnd)+
 '\nglobalThis.rendered=stats({stats:{swing_dmg:25,mod_magic_damage:50}});'+
 '\nglobalThis.numeric=numericStats({stats:{swing_dmg:25,mod_magic_damage:50}});',eqContext);
assert(eqContext.rendered.includes('25'));
assert(!eqContext.rendered.includes('50'));
assert(!Object.prototype.hasOwnProperty.call(eqContext.numeric,'mod_magic_damage'));
results.push({scenario:'unknown_item_stat',expected_defect_reproduced:true,rendered:eqContext.rendered,retained_keys:Object.keys(eqContext.numeric)});
const output={kind:'isolated_current_source_reproduction',meaning:'exit 0 means expected current defects reproduced, not fixed',source:'Расширение/frontend/viewer-bannerlord.js and viewer-bannerlord-equipment.js',network:false,full_browser:false,live_game:false,results};
fs.writeFileSync(path.join(__dirname,'frontend-probe-results.json'),JSON.stringify(output,null,2)+'\n','utf8');
console.log(JSON.stringify(output,null,2));
