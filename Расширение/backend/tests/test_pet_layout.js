/**
 * test_pet_layout.js — питомцы на оверлее не налезают друг на друга.
 *
 * Запуск:  node ../tests/test_pet_layout.js   (или через scripts/run-backend-tests.py)
 *
 * ЗАЧЕМ. Раскладка проверялась глазами, а глазами такое не проверяется:
 * наложение зависит от числа зрителей, ширины подписи и случайных чисел —
 * и вылезает не на каждом стриме, а на людном. Владелец попросил, чтобы
 * «зритель на зрителя не накладывался»; здесь это арифметика.
 *
 * Что держим:
 *   1. В ОДНОМ РЯДУ отрезки, занимаемые питомцами за всю прогулку, не
 *      пересекаются. Не «редко пересекаются» — никогда.
 *   2. Никто не уезжает за край кадра.
 *   3. Один зритель не отправляется в задний ряд (сцена не должна выглядеть
 *      пустой спереди).
 *   4. Прогулка остаётся заметной: амплитуда не схлопывается в ноль, иначе
 *      «не налезают» превратилось бы в «стоят столбами».
 */
'use strict';

const path = require('path');
const PetLayout = require(path.join(__dirname, '..', '..', 'frontend', 'pet-layout.js'));

let failures = 0;
function check(cond, label) {
    if (cond) {
        console.log('  ✅ ' + label);
    } else {
        console.log('  ❌ ' + label);
        failures++;
    }
}

// Детерминированный «рандом»: тест обязан быть воспроизводимым, иначе
// падение раз в двадцать прогонов невозможно расследовать.
function seeded(seed) {
    let s = seed >>> 0;
    return function () {
        s = (s * 1664525 + 1013904223) >>> 0;
        return s / 4294967296;
    };
}

console.log('\n[1] В одном ряду никто ни на кого не налезает');
let worstOverlap = 0;
let checkedCounts = 0;
for (let count = 1; count <= 30; count++) {
    for (let seed = 1; seed <= 20; seed++) {
        const items = PetLayout.layoutPets(count, { random: seeded(seed * 7 + count) });
        const byRow = {};
        items.forEach((it) => {
            (byRow[it.row] = byRow[it.row] || []).push(PetLayout.occupiedSpan(it));
        });
        Object.keys(byRow).forEach((row) => {
            const spans = byRow[row].sort((a, b) => a.from - b.from);
            for (let i = 1; i < spans.length; i++) {
                const gap = spans[i].from - spans[i - 1].to;
                if (gap < -0.01) worstOverlap = Math.min(worstOverlap, gap);
            }
        });
        checkedCounts++;
    }
}
check(worstOverlap >= -0.01,
    `перебрано ${checkedCounts} раскладок (1-30 зрителей), худшее наложение ${worstOverlap.toFixed(2)}vw`);

console.log('\n[2] Никто не уезжает за край кадра');
let outside = 0;
for (let count = 1; count <= 30; count++) {
    PetLayout.layoutPets(count, { random: seeded(count) }).forEach((it) => {
        const span = PetLayout.occupiedSpan(it);
        if (span.from < -0.01 || span.to > 100.01) outside++;
    });
}
check(outside === 0, `за границами кадра оказалось ${outside} питомцев`);

console.log('\n[3] Один зритель стоит в переднем ряду');
const solo = PetLayout.layoutPets(1, { random: seeded(42) });
check(solo.length === 1 && solo[0].row === 0,
    `единственный зритель не уехал в глубину (ряд ${solo[0] && solo[0].row})`);

console.log('\n[4] Прогулка не схлопнулась в ноль');
// Иначе «не налезают» достигалось бы тем, что все стоят на месте — формально
// верно, по сути потеря механики.
let zeroAmp = 0;
let sample = 0;
for (let count = 1; count <= 14; count++) {
    PetLayout.layoutPets(count, { random: seeded(count * 3) }).forEach((it) => {
        sample++;
        if (it.ampVw < 0.5) zeroAmp++;
    });
}
check(zeroAmp === 0, `у всех ${sample} питомцев (до 14 зрителей) амплитуда > 0.5vw`);

console.log('\n[5] Задний ряд читается как дальний, а не как налезший');
const many = PetLayout.layoutPets(20, { random: seeded(11) });
const back = many.filter((it) => it.row === 1);
check(back.length > 0, `при 20 зрителях задний ряд задействован (${back.length} шт.)`);
check(back.every((it) => it.scale < 1 && it.bottomPx > 0),
    'задние мельче и стоят выше — это глубина, а не столкновение');

console.log('\n' + '='.repeat(58));
if (failures) {
    console.log(`ПРОВАЛЕНО: ${failures}`);
    process.exit(1);
}
console.log('Все проверки прошли');
process.exit(0);
