using System;
using TaleWorlds.Engine;
using TaleWorlds.Library;
using TaleWorlds.MountAndBlade;

namespace BannerlordLink.Util
{
    /// <summary>
    /// 2026-09-22 — безопасная точка появления призванного героя.
    ///
    /// До этого координата считалась одной формулой: перпендикуляр к якорю,
    /// 2–4 метра, — и отдавалась движку как есть. Если там стена, телега,
    /// обрыв или другой боец, зритель появлялся внутри модели: «застрял в
    /// текстурах». Движок на это не жалуется, поэтому в логе призыв выглядел
    /// успешным.
    ///
    /// Теперь кандидат проходит четыре проверки у самой сцены, и берётся
    /// ПЕРВЫЙ прошедший (`SpawnPointSearch` — 24 кандидата, ближние кольца
    /// раньше):
    ///   1. точка лежит на навигационной поверхности;
    ///   2. её высота не убежала от якоря (крыша, подвал, обрыв);
    ///   3. от якоря до неё существует путь — внутрь запертой геометрии пути нет;
    ///   4. рядом нет другого бойца.
    /// Z берём у навигационной поверхности, а не у якоря: иначе герой
    /// появляется в полу или в воздухе даже на честной площадке.
    ///
    /// Ни один кандидат не прошёл — возвращаем false, и вызывающий честно
    /// уходит в зону подкреплений. Это лучше, чем появиться в стене.
    /// </summary>
    internal static class SafeSummonPlacement
    {
        /// <summary>Насколько высота точки может отличаться от якоря, метров.</summary>
        private const float MaxHeightDelta = 3.0f;
        /// <summary>Свободный радиус вокруг точки, метров.</summary>
        private const float FootClearance    = 1.2f;
        private const float MountedClearance = 2.5f;

        internal static bool TryPlace(
            Vec3 anchorPos, bool mounted, int seed,
            out Vec3 spawnPos, out string reason)
        {
            spawnPos = anchorPos;
            reason = "no_mission";
            var mission = Mission.Current;
            var scene = mission?.Scene;
            if (scene == null) return false;

            float clearance = mounted ? MountedClearance : FootClearance;
            float clearanceSq = clearance * clearance;
            WorldPosition anchorWp;
            try { anchorWp = new WorldPosition(scene, anchorPos); }
            catch (Exception ex)
            {
                reason = "anchor_invalid:" + ex.GetType().Name;
                return false;
            }

            int rejectedNav = 0, rejectedHeight = 0, rejectedPath = 0, rejectedBusy = 0;
            Vec3 found = anchorPos;

            bool Allowed(float x, float y)
            {
                try
                {
                    var wp = new WorldPosition(scene, new Vec3(x, y, anchorPos.z));
                    if (wp.GetNavMesh() == UIntPtr.Zero) { rejectedNav++; return false; }

                    float z = wp.GetNavMeshZ();
                    if (Math.Abs(z - anchorPos.z) > MaxHeightDelta) { rejectedHeight++; return false; }

                    if (!scene.DoesPathExistBetweenPositions(anchorWp, wp)) { rejectedPath++; return false; }

                    foreach (var agent in mission.Agents)
                    {
                        if (agent == null || !agent.IsActive()) continue;
                        var p = agent.Position;
                        float dx = p.x - x, dy = p.y - y;
                        if (dx * dx + dy * dy < clearanceSq) { rejectedBusy++; return false; }
                    }

                    found = new Vec3(x, y, z);
                    return true;
                }
                catch
                {
                    // Сцена может огрызнуться на кандидата вне своих границ —
                    // это «нельзя», а не повод ронять призыв.
                    rejectedNav++;
                    return false;
                }
            }

            bool ok = SpawnPointSearch.TryFind(
                anchorPos.x, anchorPos.y, seed, mounted, Allowed, out _, out _);

            if (ok)
            {
                spawnPos = found;
                reason = "ok";
                return true;
            }

            reason = $"нет свободной точки (нет навигации {rejectedNav}, " +
                     $"высота {rejectedHeight}, нет пути {rejectedPath}, занято {rejectedBusy})";
            return false;
        }
    }
}
