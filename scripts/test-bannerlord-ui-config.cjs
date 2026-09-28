const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require('playwright');
const front=path.join(__dirname,'../Расширение/frontend');

async function main() {
    for (const shell of ['extension.html','mobile.html']) {
        const html=fs.readFileSync(path.join(front,shell),'utf8');
        assert(html.includes('viewer-bannerlord-ui-config.js'),`${shell}: UI config script missing`);
        for (const id of ['summon','active_powers','tournament','weapon_choice'])
            assert(html.includes(`data-bnr-ui-section="${id}"`),`${shell}: ${id} component missing`);
    }
    const browser=await chromium.launch({headless:true,...(process.platform==='win32'?{channel:'msedge'}:{})});
    try {
        const page=await browser.newPage({viewport:{width:340,height:900}});
        const errors=[];page.on('pageerror',error=>errors.push(error.message));
        await page.setContent(`<meta charset="utf-8"><div class="bnr-tab-pane active" data-bnr-pane="combat">
            <div id="bnr-pane-combat-body"></div>
            <div id="bnr-summon-slot" data-bnr-ui-section="summon">Summon</div>
            <div id="bnr-active-powers-slot" data-bnr-ui-section="active_powers">Powers</div>
            <div id="bannerlord-tournament-card" data-bnr-ui-section="tournament"><h3 data-bnr-ui-label="tournament">🏆 Турнир зрителей</h3></div>
            <div id="bnr-build-choice-slot" data-bnr-ui-section="weapon_choice"></div></div>
            <div id="bnr-equipment-shop"><article data-tier="1"><strong>Low</strong></article><article data-tier="6"><strong>High</strong></article></div>`);
        await page.addStyleTag({path:path.join(front,'viewer.css')});
        await page.addScriptTag({path:path.join(front,'viewer-bannerlord-ui-config.js')});
        const order=()=>page.locator('[data-bnr-pane="combat"] > [data-bnr-ui-section]').evaluateAll(nodes=>nodes.map(node=>node.dataset.bnrUiSection));
        assert.deepEqual(await order(),['summon','active_powers','tournament','weapon_choice']);
        await page.evaluate(()=>BnrUiConfig.update({version:1,
            combat_order:['tournament','summon','active_powers','weapon_choice'],
            combat_visible:{active_powers:false},
            labels:{tournament:'<img src=x onerror=alert(1)>',discard:'Сдать вещь'},
            tier_colors:{'6':{text:'#ABCDEF',border:'#123456',background:'#234567'}}}));
        assert.deepEqual(await order(),['tournament','summon','active_powers','weapon_choice']);
        assert.equal(await page.locator('#bnr-active-powers-slot').isVisible(),false);
        assert.equal(await page.locator('[data-bnr-ui-label="tournament"]').innerText(),'<img src=x onerror=alert(1)>');
        assert.equal(await page.locator('img').count(),0,'server label is text, not markup');
        assert.equal(await page.evaluate(()=>BnrUiConfig.label('discard')),'Сдать вещь');
        assert.equal(await page.locator('[data-tier="6"]').evaluate(node=>getComputedStyle(node).getPropertyValue('--tier-color').trim()),'#ABCDEF');
        await page.evaluate(()=>BnrUiConfig.update({version:1,
            combat_order:['summon','summon','tournament','weapon_choice'],
            combat_visible:{summon:'false'},
            tier_colors:{'6':{text:'url(javascript:alert(1))'}}}));
        assert.deepEqual(await order(),['summon','active_powers','tournament','weapon_choice'],'bad order falls back');
        assert.equal(await page.locator('#bnr-summon-slot').isVisible(),true,'bad visibility falls back');
        assert.equal(await page.locator('[data-tier="6"]').evaluate(node=>getComputedStyle(node).getPropertyValue('--tier-color').trim()),'#f5d174');
        assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'no 340px overflow');
        assert.deepEqual(errors,[]);
        console.log('PASS: bounded UI config, order/visibility, labels, tier palette, invalid fallback and narrow layout');
    } finally {await browser.close();}
}
main().catch(error=>{console.error(error);process.exitCode=1;});
