using System.Collections.Generic;

namespace BannerlordLink.Util
{
    /// <summary>
    /// Учёт того, какой снимок состояния героя РЕАЛЬНО доехал до бэкенда.
    ///
    /// ЗАЧЕМ (2026-09-09). Раньше `HeroStateSync.PushIfChanged` писал хэш в кэш
    /// ДО отправки, а саму отправку запускал fire-and-forget и результат
    /// выбрасывал. Отправка не удалась — кэш уже утверждает «доставлено», и
    /// пока состояние героя не изменится СНОВА, актуальный снимок не уйдёт
    /// никогда. Зритель видит замороженные золото/уровень/навыки, а в логе
    /// одна строка про ошибку сети.
    ///
    /// Здесь снимок считается доставленным ТОЛЬКО после положительного
    /// подтверждения конкретного конверта. Неудача не подтверждает ничего —
    /// следующий тик (раз в 30с) построит актуальный снимок и отправит снова.
    ///
    /// ОЧЕРЕДИ ПОВТОРОВ НЕТ И НЕ НУЖНО. Для зеркала состояния важен только
    /// ПОСЛЕДНИЙ актуальный снимок: копить неудавшиеся означало бы слать
    /// заведомо устаревшее и растить память без предела. Повтор — это просто
    /// «на следующем тике хэш всё ещё не подтверждён».
    ///
    /// ПОЧЕМУ ЗДЕСЬ НЕТ ТИПОВ ДВИЖКА. Класс намеренно не знает о `Hero` и
    /// вообще о TaleWorlds: JSON строится на главном потоке вызывающим, сюда
    /// приходит уже готовая строка. Это даёт два свойства сразу — из фонового
    /// потока не трогаются объекты игры, и этот же файл компилируется в
    /// тестовый harness без игровых DLL (тест гоняет НАСТОЯЩИЙ механизм, а не
    /// переписанную копию алгоритма).
    ///
    /// Потокобезопасен: подтверждения приходят из фоновых задач.
    /// </summary>
    public sealed class StateSyncTracker
    {
        /// <summary>Билет на одну отправку. Возвращается при старте и
        /// предъявляется при подтверждении/отказе.</summary>
        public struct Attempt
        {
            public string Username;
            public int Hash;
            public long Seq;
            public long Epoch;
            public bool IsValid;
        }

        private readonly object _lock = new object();
        private readonly Dictionary<string, int> _confirmed = new Dictionary<string, int>();
        private readonly Dictionary<string, long> _latestSeq = new Dictionary<string, long>();
        private long _seq;
        private long _epoch;

        /// <summary>Надо ли отправлять этот снимок.
        ///
        /// false — ровно один случай: точно такой же снимок уже ПОДТВЕРЖДЁН.
        /// Всё остальное (не отправляли, отправка провалилась, отправка ещё в
        /// полёте) даёт true: неподтверждённое состояние обязано уехать.
        /// Повторная отправка того же состояния безвредна — на бэкенде это
        /// UPDATE теми же значениями.</summary>
        public bool TryBeginSend(string username, string json, out Attempt attempt)
        {
            attempt = default(Attempt);
            if (string.IsNullOrEmpty(username) || json == null) return false;

            int hash = json.GetHashCode();
            lock (_lock)
            {
                int confirmed;
                if (_confirmed.TryGetValue(username, out confirmed) && confirmed == hash)
                    return false;

                _seq++;
                _latestSeq[username] = _seq;
                attempt = new Attempt
                {
                    Username = username,
                    Hash = hash,
                    Seq = _seq,
                    Epoch = _epoch,
                    IsValid = true,
                };
                return true;
            }
        }

        /// <summary>Бэкенд подтвердил ИМЕННО этот конверт.
        ///
        /// Подтверждение принимается только если с тех пор не стартовала более
        /// свежая отправка для того же героя и не сменилась сессия. Иначе
        /// старый ответ объявил бы доставленным устаревший снимок, и более
        /// новый перестал бы отправляться — та же болезнь, только тоньше.
        /// Возвращает true, если кэш действительно обновлён.</summary>
        public bool Confirm(Attempt attempt)
        {
            if (!attempt.IsValid) return false;
            lock (_lock)
            {
                if (attempt.Epoch != _epoch) return false;      // ответ из прошлой сессии
                long latest;
                if (!_latestSeq.TryGetValue(attempt.Username, out latest)) return false;
                if (latest != attempt.Seq) return false;        // уже ушла более свежая
                _confirmed[attempt.Username] = attempt.Hash;
                return true;
            }
        }

        /// <summary>Отправка не удалась либо бэкенд отклонил конверт.
        /// Ничего не подтверждаем — следующий тик отправит актуальный снимок.
        /// Метод существует ради явности: «неудача» это отдельное решение, а
        /// не отсутствие вызова.</summary>
        public void Fail(Attempt attempt)
        {
            // Намеренно пусто: подтверждённый кэш не трогаем. Снимок в нём —
            // это то, что доехало; неудачная попытка не делает его хуже.
        }

        /// <summary>Загрузили другой сейв / началась новая сессия.
        ///
        /// Кэш очищается (иначе зеркало решит «не изменилось» по хэшу прошлого
        /// сейва), И поднимается эпоха: подтверждения отправок, стартовавших до
        /// загрузки, больше не принимаются. Без эпохи callback от отменённой
        /// сессии записал бы хэш в свежий кэш, и состояние нового сейва не
        /// уехало бы.</summary>
        public void ResetForNewSession()
        {
            lock (_lock)
            {
                _epoch++;
                _confirmed.Clear();
                _latestSeq.Clear();
            }
        }

        /// <summary>Сколько героев имеют подтверждённый снимок — для логов и тестов.</summary>
        public int ConfirmedCount
        {
            get { lock (_lock) { return _confirmed.Count; } }
        }
    }
}
