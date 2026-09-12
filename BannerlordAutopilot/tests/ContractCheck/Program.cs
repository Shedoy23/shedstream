using System;
using System.IO;
using System.Reflection;

namespace BannerlordAutopilot.Tests
{
    /// <summary>Самопроверка контракта движка БЕЗ запуска игры.
    ///
    /// Зачем. `EngineContract.Verify()` решает, включится ли автопилот вообще.
    /// Если бы его первый прогон случился только в игре, ошибка в именах или
    /// сигнатурах обнаружилась бы в момент испытания — то есть дороже всего.
    /// Здесь тот же код выполняется по тем же DLL, что стоят у игрока.
    ///
    /// Вердикт по коду возврата: 0 — контракт совпал, 1 — не совпал (и тогда
    /// печатается, что именно), 2 — проверить не удалось (нет игры/DLL).
    ///
    /// Запуск:
    ///   dotnet run --project BannerlordAutopilot/tests/ContractCheck -c Release
    /// </summary>
    internal static class Program
    {
        private static string _gameBin;

        private static int Main(string[] args)
        {
            _gameBin = args.Length > 0
                ? args[0]
                : @"X:\SteamLibrary\steamapps\common\Mount & Blade II Bannerlord\bin\Win64_Shipping_Client";

            if (!Directory.Exists(_gameBin))
            {
                Console.WriteLine("НЕ ПРОВЕРЕНО: не найдена папка игры: " + _gameBin);
                Console.WriteLine("Передайте путь первым аргументом. Это НЕ «ок» — код возврата 2.");
                return 2;
            }

            // Игровые сборки ссылаются друг на друга; рядом с раннером их нет,
            // поэтому резолвим вручную из папки игры.
            AppDomain.CurrentDomain.AssemblyResolve += ResolveFromGame;

            try
            {
                Type contract = typeof(EngineContract);
                MethodInfo verify = contract.GetMethod("Verify",
                    BindingFlags.Static | BindingFlags.NonPublic | BindingFlags.Public);
                if (verify == null)
                {
                    Console.WriteLine("НЕ ПРОВЕРЕНО: EngineContract.Verify не найден");
                    return 2;
                }

                bool ok = (bool)verify.Invoke(null, null);
                string report = (string)contract
                    .GetProperty("Report", BindingFlags.Static | BindingFlags.NonPublic | BindingFlags.Public)
                    .GetValue(null);

                Console.WriteLine("игра: " + _gameBin);
                Console.WriteLine("версия CampaignSystem: " + FileVersion("TaleWorlds.CampaignSystem.dll"));
                Console.WriteLine(ok ? "КОНТРАКТ СОВПАЛ: " + report : "КОНТРАКТ НЕ СОВПАЛ: " + report);
                Console.WriteLine(ok
                    ? "автопилот в этой сборке включится"
                    : "автопилот в этой сборке ВКЛЮЧАТЬСЯ НЕ БУДЕТ — и это правильное поведение");
                return ok ? 0 : 1;
            }
            catch (Exception ex)
            {
                Console.WriteLine("НЕ ПРОВЕРЕНО: проверка упала — " + ex.GetType().Name + ": " + ex.Message);
                if (ex.InnerException != null)
                {
                    Console.WriteLine("  причина: " + ex.InnerException.Message);
                }
                return 2;
            }
        }

        private static string FileVersion(string dll)
        {
            try
            {
                var info = System.Diagnostics.FileVersionInfo.GetVersionInfo(Path.Combine(_gameBin, dll));
                return info.FileVersion ?? "неизвестна";
            }
            catch (Exception)
            {
                return "неизвестна";
            }
        }

        private static Assembly ResolveFromGame(object sender, ResolveEventArgs args)
        {
            string name = new AssemblyName(args.Name).Name + ".dll";
            string path = Path.Combine(_gameBin, name);
            return File.Exists(path) ? Assembly.LoadFrom(path) : null;
        }
    }
}
