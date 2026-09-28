using System;
using TaleWorlds.CampaignSystem;
using TaleWorlds.Core;
using TaleWorlds.ObjectSystem;

namespace BannerlordLink.Util
{
    /// <summary>
    /// Поиск героя по строковому id — тому, что бэкенд хранит в
    /// `heir_hero_id` / `child_hero_id`.
    ///
    /// ЗАЧЕМ ЭТОТ ФАЙЛ (2026-07-31). Четыре места искали героя через
    /// `MBObjectManager.GetObject&lt;Hero&gt;(id)`. Но id, который мы сами
    /// сохранили, выглядит как `CharacterObject_9729` — это StringId
    /// **CharacterObject**, а не Hero. Поиск героя по чужому типу возвращает
    /// null, и наверх уходит `hero_not_found`.
    ///
    /// Как это выглядело: на проде создание вассального клана падало 7 раз из
    /// 7, респек ребёнка — 3 из 3. Проверено вживую 31.07: наследник Кавил
    /// (`CharacterObject_9729`) есть в базе и жив, а мод его «не находит».
    ///
    /// Резолвер пробует три пути по очереди — от самого дешёвого:
    ///   1. id действительно принадлежит Hero (старое поведение, совместимость);
    ///   2. id принадлежит CharacterObject → берём его `HeroObject`;
    ///   3. перебор живых героев по `CharacterObject.StringId` — на случай,
    ///      когда объект пересоздан движком и прямой поиск промахивается.
    ///
    /// ПОЧЕМУ ОДИН ФАЙЛ, А НЕ ПРАВКА В ЧЕТЫРЁХ. В этом проекте один и тот же
    /// фикс уже трижды ложился в один файл из нескольких похожих и там
    /// оставался. Четыре копии резолвера разъедутся так же.
    /// </summary>
    public static class HeroResolver
    {
        /// <summary>
        /// Найти героя. Возвращает null и заполняет `reason`, если не вышло.
        /// Живость НЕ проверяется — это дело вызывающего (наследнику она
        /// обязательна, а, например, поиск покойного родителя — нет).
        /// </summary>
        public static Hero ByStringId(string id, out string reason)
        {
            reason = null;
            if (string.IsNullOrEmpty(id))
            {
                reason = "no_hero_id";
                return null;
            }

            // 1. Прямой поиск — id действительно героя.
            try
            {
                var direct = MBObjectManager.Instance.GetObject<Hero>(id);
                if (direct != null) return direct;
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[HeroResolver] GetObject<Hero>('{id}') упал: {ex.Message}");
            }

            // 2. Это id CharacterObject — у него есть свой герой.
            try
            {
                var co = MBObjectManager.Instance.GetObject<CharacterObject>(id);
                if (co != null && co.HeroObject != null)
                {
                    BannerlordLinkModule.Log(
                        $"[HeroResolver] '{id}' — CharacterObject, взят HeroObject "
                        + $"'{co.HeroObject.Name}'");
                    return co.HeroObject;
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[HeroResolver] GetObject<CharacterObject>('{id}') упал: {ex.Message}");
            }

            // 3. Последний рубеж — перебор живых по CharacterObject.StringId.
            try
            {
                foreach (var h in Hero.AllAliveHeroes)
                {
                    if (h == null || h.CharacterObject == null) continue;
                    if (h.CharacterObject.StringId == id)
                    {
                        BannerlordLinkModule.Log(
                            $"[HeroResolver] '{id}' найден перебором живых: '{h.Name}'");
                        return h;
                    }
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[HeroResolver] перебор живых героев упал: {ex.Message}");
            }

            reason = "hero_not_found";
            return null;
        }
    }
}
