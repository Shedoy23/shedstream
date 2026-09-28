using System;
using System.Linq;
using System.Collections.Generic;
using System.Threading.Tasks;
using Newtonsoft.Json.Linq;
using BannerlordLink.Util;
using TaleWorlds.CampaignSystem;
using TaleWorlds.Core;
using TaleWorlds.ObjectSystem;
class Program {
 static int checks;
 static void Check(bool ok,string message){checks++;if(!ok)throw new Exception(message);}
 static async Task Main(){
  var m=MBObjectManager.Instance;
  var custom=new CultureObject{StringId="mod_north",Name="Север мода",EncyclopediaText="Игровое описание"};
  var unavailable=new CultureObject{StringId="no_templates",Name="Без шаблонов"};
  m.GetObjectTypeList<CultureObject>().AddRange(new[]{custom,unavailable});
  var template=new CharacterObject{Culture=custom,Occupation=Occupation.Wanderer};
  m.GetObjectTypeList<CharacterObject>().Add(template);
  Check(RuntimeGameCatalogs.CreationTemplates("mod_north",out var reason).Single()==template && reason==null,"Custom culture preserves requested template");
  Check(RuntimeGameCatalogs.CreationTemplates("no_templates",out reason).Count==0 && reason=="culture_no_wanderer_templates","Known unavailable culture must not become random other culture");
  Check(RuntimeGameCatalogs.CreationTemplates("removed_mod",out reason).Count==0 && reason=="culture_not_found","Removed culture fails explicitly");
  Check(RuntimeGameCatalogs.CreationTemplates("",out reason).Single()==template,"Explicit random still works");
  var caseDistinct=new CultureObject{StringId="MOD_NORTH",Name="Другой мод"};
  var otherTemplate=new CharacterObject{Culture=caseDistinct,Occupation=Occupation.Wanderer};
  m.GetObjectTypeList<CultureObject>().Add(caseDistinct);
  m.GetObjectTypeList<CharacterObject>().Add(otherTemplate);
  Check(RuntimeGameCatalogs.CreationTemplates("MOD_NORTH",out reason).Single()==otherTemplate,"Case-distinct mod IDs must select exact culture");
  m.GetObjectTypeList<SkillObject>().Add(new SkillObject{StringId="magic",Name="Магия",Description="Из мода"});
  m.GetObjectTypeList<CharacterAttribute>().Add(new CharacterAttribute{StringId="spirit",Name="Дух",Description="Сила духа"});
  PolicyObject.All.Add(new PolicyObject{StringId="mod_law",Name="Закон мода",Description="Правило",SecondaryEffects="Эффект"});
  var payloads=RuntimeGameCatalogs.Build("save1","session1",1).Select(JObject.Parse).ToList();
  Check(payloads.Count==4 && payloads.All(x=>(string)x["save_id"]=="save1"&&(string)x["equipment_session_id"]=="session1"&&(long)x["catalog_seq"]==1),"All catalogs have same session and revision");
  var cultures=(JArray)payloads.Single(x=>(string)x["catalog"]=="cultures")["entries"];
  Check((string)cultures[0]["name"]=="Север мода"&&(bool)cultures[0]["available"],"Catalog uses game name and same creation availability");
  Check(!(bool)cultures[1]["available"]&&(string)cultures[1]["unavailable_reason"]=="culture_no_wanderer_templates","Unavailable entry stays visible with reason");
  Check((string)payloads.Single(x=>(string)x["catalog"]=="policies")["entries"][0]["description"]=="Правило\nЭффект","Policy effects from game");
  Check((string)payloads.Single(x=>(string)x["catalog"]=="skills")["entries"][0]["id"]=="magic","Custom skill preserved");
  Check((string)payloads.Single(x=>(string)x["catalog"]=="attributes")["entries"][0]["name"]=="Дух","Custom attribute name preserved");
  PolicyObject.All.Clear();
  Check(((JArray)RuntimeGameCatalogs.Build("save1","session1",2).Select(JObject.Parse).Single(x=>(string)x["catalog"]=="policies")["entries"]).Count==0,"Empty snapshot published, not skipped");
  Check(RuntimeGameCatalogs.ValidateSession(null,null,"save1","session1")==null,"Legacy unspecified identity accepted");
  Check(RuntimeGameCatalogs.ValidateSession("old",null,"save1","session1")=="stale_hero_session","Stale save refused before creation");
  Check(RuntimeGameCatalogs.ValidateSession("save1","old","save1","session1")=="stale_equipment_session","Same-save reload refused");
  var batch=new CatalogSnapshotBatch(new[]{"equipment","cultures","policies"});
  var sent=new List<string>();bool fail=true;
  Func<string,Task<bool>> send=p=>{sent.Add(p);return Task.FromResult(p!="cultures"||!fail);};
  Check(!await batch.PublishAsync(send),"Failure stops batch");
  Check(string.Join(",",sent)=="equipment,cultures","No later catalog after failure");
  fail=false;Check(await batch.PublishAsync(send),"Retry completes");
  Check(string.Join(",",sent)=="equipment,cultures,cultures,policies","Retry retains exact pending payload order");
  var throwing=new CatalogSnapshotBatch(new[]{"cultures"});
  try {await throwing.PublishAsync(_=>throw new InvalidOperationException("offline"));}catch(InvalidOperationException){}
  Check(await throwing.PublishAsync(_=>Task.FromResult(true)),"Exception retains payload for retry");
  Console.WriteLine($"PASS {checks} runtime catalog checks");
 }
}
