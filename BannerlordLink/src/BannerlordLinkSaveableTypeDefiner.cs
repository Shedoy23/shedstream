using BannerlordLink.Actions;
using TaleWorlds.SaveSystem;

namespace BannerlordLink
{
    // Persistent IDs: never renumber or reuse them, including after removing a type.
    // The engine discovers this definer automatically when building its save schema.
    public sealed class BannerlordLinkSaveableTypeDefiner : SaveableTypeDefiner
    {
        public BannerlordLinkSaveableTypeDefiner() : base(194210000) { }

        protected override void DefineClassTypes()
        {
            // Both subclasses live in Kingdom.UnresolvedDecisions. Their state is
            // inherited from the native decisions; their exact runtime types still
            // need save definitions or saving the entire campaign fails.
            AddClassDefinition(typeof(ViewerDeclareWarDecision), 1);
            AddClassDefinition(typeof(ViewerMakePeaceDecision), 2);
        }
    }
}
