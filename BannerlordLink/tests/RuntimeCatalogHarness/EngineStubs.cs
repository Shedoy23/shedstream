using System.Collections.Generic;
namespace TaleWorlds.Core {
 public class Text { public string Value; public override string ToString()=>Value; public static implicit operator Text(string value)=>new Text{Value=value}; }
 public class PropertyObject { public string StringId; public Text Name; public Text Description; }
 public class SkillObject : PropertyObject { }
 public class CharacterAttribute : PropertyObject { }
}
namespace TaleWorlds.CampaignSystem {
 using TaleWorlds.Core;
 public enum Occupation { Wanderer, Lord }
 public class CultureObject { public string StringId; public Text Name; public Text EncyclopediaText; }
 public class CharacterObject { public CultureObject Culture; public Occupation Occupation; }
 public class PolicyObject : PropertyObject { public Text SecondaryEffects; public static List<PolicyObject> All = new List<PolicyObject>(); }
}
namespace TaleWorlds.CampaignSystem.Settlements.Workshops {
 public class WorkshopType : TaleWorlds.Core.PropertyObject { public static List<WorkshopType> All = new List<WorkshopType>(); }
}
namespace TaleWorlds.ObjectSystem {
 public class MBObjectManager {
  public static MBObjectManager Instance = new MBObjectManager();
  readonly Dictionary<System.Type,object> rows = new Dictionary<System.Type,object>();
  public List<T> GetObjectTypeList<T>() { if(!rows.ContainsKey(typeof(T))) rows[typeof(T)] = new List<T>(); return (List<T>)rows[typeof(T)]; }
 }
}
