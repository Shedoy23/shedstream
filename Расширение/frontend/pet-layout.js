// Раскладка питомцев на оверлее: кто где стоит и куда гуляет.
//
// ЗАЧЕМ ОТДЕЛЬНЫМ ФАЙЛОМ. Раньше это жило внутри overlay.html и проверялось
// глазами: «вроде не налезают». Глазами такое не проверяется — наложение
// зависит от числа зрителей, ширины подписи и случайных чисел, и появляется
// не на каждом стриме. Здесь это чистая функция, для которой «никто ни на кого
// не налез» — арифметика, а не впечатление (tests/test_pet_layout.js).
//
// ПОЧЕМУ НАЛЕЗАЛИ. Каждому давали ПОЛОСУ шириной 88/N vw, но амплитуда прогулки
// была 15–30vw независимо от числа питомцев. При 13 зрителях полоса — 6.8vw, а
// гуляли на 15–30, то есть насквозь через чужие полосы. В комментарии это было
// записано как «задумано», но выглядит как ком.
//
// ЧТО ДЕЛАЕМ. Два приёма вместе:
//   1. Прогулка не выходит за свою полосу — пересечься физически невозможно.
//   2. Питомцы раскладываются в НЕСКОЛЬКО РЯДОВ по глубине. Ряд сзади мельче,
//      стоит выше и бледнее. Это удваивает ширину полосы (в ряду вдвое меньше
//      соседей) и заодно даёт сцене глубину: тот, кто сзади, читается как
//      дальний, а не как налезший.
(function (global) {
    'use strict';

    // Ширина, которую занимает питомец с подписью, в процентах ширины экрана.
    // Замер 5.28: подпись «[26lvl] kuro_gothic» шире самого спрайта, поэтому
    // считаем по подписи, а не по картинке.
    var SLOT_VW = 9;

    // Поле у краёв: спрайт не должен упираться в границу кадра OBS.
    var EDGE_VW = 3;

    var ROWS = [
        // depth 0 — передний ряд: крупнее, ниже, ярче.
        { bottom: 0,  scale: 1.00, opacity: 1.00 },
        // depth 1 — средний.
        { bottom: 42, scale: 0.80, opacity: 0.90 },
        // depth 2 — дальний: ещё мельче и выше.
        { bottom: 78, scale: 0.64, opacity: 0.78 },
    ];

    // Насколько полоса должна быть шире самого питомца, чтобы прогулка вообще
    // читалась. Меньше — «не налезают» выродится в «стоят столбами», и это
    // формально верно, но по сути потеря механики.
    var LANE_ROOMINESS = 1.8;

    /**
     * Разложить N питомцев так, чтобы в одном ряду они не пересекались.
     * Возвращает массив описаний по одному на питомца.
     */
    function layoutPets(count, opts) {
        opts = opts || {};
        var rnd = opts.random || Math.random;
        var slot = opts.slotVw || SLOT_VW;
        var edge = opts.edgeVw || EDGE_VW;
        var rows = opts.rows || ROWS;
        var out = [];
        if (!count || count < 1) return out;

        // Сколько рядов реально нужно: пока в ряду помещается меньше питомцев,
        // чем есть, добавляем ряд. Один зритель не должен уезжать в задний ряд.
        var usable = 100 - edge * 2;
        // Сколько влезает в ряд С МЕСТОМ ДЛЯ ПРОГУЛКИ, а не впритык.
        var perRowComfy = Math.max(1, Math.floor(usable / (slot * LANE_ROOMINESS)));
        var rowsNeeded = Math.min(rows.length,
                                  Math.max(1, Math.ceil(count / perRowComfy)));

        // Раскидываем по рядам ЧЕРЕДУЯ, а не пачками: иначе при 3 зрителях двое
        // окажутся спереди вплотную, а сзади будет пусто.
        var perRowCount = [];
        for (var r = 0; r < rowsNeeded; r++) perRowCount.push(0);
        for (var k = 0; k < count; k++) perRowCount[k % rowsNeeded]++;

        var placed = [];
        for (var i = 0; i < rowsNeeded; i++) placed.push(0);

        for (var idx = 0; idx < count; idx++) {
            var row = idx % rowsNeeded;
            var inRow = perRowCount[row];
            var pos = placed[row]++;

            // Полоса этого питомца внутри своего ряда.
            var laneW = usable / inRow;
            var laneStart = edge + pos * laneW;

            // Место, которое питомец занимает В ЭТОМ РЯДУ: дальние нарисованы
            // мельче, значит и места им нужно меньше — иначе задний ряд
            // резервировал бы ширину, которой не занимает.
            var rowSlot = slot * (rows[row].scale || 1);
            // Толпа: если даже уменьшенный не влезает, ужимаем место под него.
            // Тесно — приемлемо, налезать — нет.
            if (rowSlot > laneW) rowSlot = laneW;

            // Прогулка не покидает полосу: свободного места ровно
            // (ширина полосы - место под самого питомца).
            var freeVw = Math.max(0, laneW - rowSlot);
            var amp = freeVw * (0.45 + rnd() * 0.5);      // 45-95% свободного
            var jitter = (laneW - rowSlot - amp);
            var startVw = laneStart + (jitter > 0 ? rnd() * jitter : 0);
            var dir = rnd() < 0.5 ? 1 : -1;
            if (dir === -1) { startVw += amp; }           // идём влево из правого края

            out.push({
                row: row,
                // Геометрию НЕ округляем: старт, амплитуда и ширина места
                // округлялись по отдельности, и сумма трёх ошибок давала
                // наложение в 0.1vw — тест поймал его как настоящее. Округление
                // уместно при записи в CSS, а не в расчёте.
                startVw: startVw,
                ampVw: amp,
                dir: dir,
                laneStartVw: laneStart,
                laneWidthVw: laneW,
                slotVw: rowSlot,
                bottomPx: rows[row].bottom,
                scale: rows[row].scale,
                opacity: rows[row].opacity,
                // Разводим ритм: одинаковые длительности выглядят как строй.
                durationS: 90 + Math.floor(rnd() * 61),
                delayS: Math.round(rnd() * 80) / 10,
                swayDelayS: Math.round((idx * 0.25) * 100) / 100,
                // Подписи соседей всё равно могут сойтись — поднимаем через одну.
                nameLiftPx: (pos % 2) ? 15 : 0,
            });
        }
        return out;
    }

    /** Отрезок, который питомец занимает за всю прогулку (с его шириной). */
    function occupiedSpan(item, slotVw) {
        var slot = slotVw || item.slotVw || SLOT_VW;
        var from = Math.min(item.startVw, item.startVw + item.dir * item.ampVw);
        var to = Math.max(item.startVw, item.startVw + item.dir * item.ampVw) + slot;
        return { from: from, to: to };
    }

    global.PetLayout = {
        layoutPets: layoutPets,
        occupiedSpan: occupiedSpan,
        SLOT_VW: SLOT_VW,
        ROWS: ROWS,
    };
})(typeof window !== 'undefined' ? window : globalThis);

if (typeof module !== 'undefined' && module.exports) {
    module.exports = (typeof window !== 'undefined' ? window : globalThis).PetLayout;
}
