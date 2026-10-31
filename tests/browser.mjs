/* SPDX-License-Identifier: Apache-2.0
 * Runs against tests/seed.py's isolated Guacamole 1.6.0 instance only.
 * Never prints tokens, request headers, response bodies or passwords.
 */
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
const { chromium } = await import(process.env.GTM_PLAYWRIGHT_MODULE || 'playwright');
const url = process.env.GTM_TEST_URL || 'http://127.0.0.1:18080/guacamole/';
const password = process.env.GTM_TEST_PASSWORD;
assert(password, 'Set the test-only GTM_TEST_PASSWORD');
const browser = await chromium.launch({headless:true, args:['--no-sandbox']});
const errors = [];
let checks = 0;
let stage = 'starting';
async function check(condition, message) { assert(condition,message); checks++; }
async function login(role, language='en') {
    stage = 'login ' + role + ' ' + language;
    const context = await browser.newContext({locale:language==='zh_TW'?'zh-TW':'en-US', viewport:{width:1440,height:1000}});
    await context.addInitScript(({language}) => {
        // Guacamole's own preference format, containing no credentials.
        localStorage.setItem('GUAC_PREFERENCES',JSON.stringify({language}));
    }, {language});
    const page=await context.newPage();
    page.on('pageerror',()=>errors.push('Browser JavaScript error'));
    await page.goto(url);
    await page.locator('input[name="username"]').fill('gtm-'+role);
    await page.locator('input[name="password"]').fill(password);
    await page.locator('input.login[type="submit"]').click();
    await page.locator('.gtm-shell').waitFor({timeout:30000});
    return {page,context};
}
try {
    const {page,context}=await login('reader');
    await check(await page.locator('.gtm-table tbody tr[ng-repeat]').count()===4,'Reader sees exactly four authorized entries');
    await check(!await page.locator('.gtm').innerText().then(x=>x.includes('Hidden Lab')),'Hidden connection absent');
    await check(await page.locator('.gtm-host button').count()===0,'READ permission cannot reveal hosts');
    await check(await page.locator('.gtm-sidebar a[href$="/history"]').count()===0,'Reader has no history link');
    await check(await page.locator('.gtm-sidebar a[href$="/connections"]').count()===0,'Reader has no management link');
    const denied = await page.evaluate(async () => {
        const auth=angular.element(document.documentElement).injector().get('authenticationService');
        const source=auth.getAvailableDataSources()[0];
        try {
            await auth.request({method:'GET',cache:false,url:'api/session/data/'+encodeURIComponent(source)+'/connections/1/parameters'});
            return false;
        } catch (ignore) { return true; }
    });
    await check(denied,'Server also denies READ-only parameter disclosure');
    const input=page.locator('.gtm-search input');
    await input.fill('Router');
    await check(await page.locator('.gtm-table tbody tr[ng-repeat]').count()===1,'Search filters rows');
    await page.locator('.gtm-star').click();
    await page.locator('.gtm-sidebar button').filter({hasText:'Favorites'}).click();
    await check(await page.locator('.gtm-table tbody tr[ng-repeat]').count()===1,'Favorite is usable');
    await page.reload(); await page.locator('.gtm-shell').waitFor();
    await page.locator('.gtm-sidebar button').filter({hasText:'Favorites'}).click();
    await check(await page.locator('.gtm-table tbody tr[ng-repeat]').count()===1,'Favorite survives reload');
    await page.locator('.gtm-sidebar button').filter({hasText:'All devices'}).click();
    const selects=page.locator('.gtm-filters select');
    await selects.nth(0).selectOption('network');
    await check(await page.locator('.gtm-table tbody tr[ng-repeat]').count()===1,'Network category uses authorized group');
    await selects.nth(0).selectOption('');
    await selects.nth(1).selectOption({label:'postgresql / Servers'});
    await check(await page.locator('.gtm-table tbody tr[ng-repeat]').count()===1,'Group browsing filters descendants');
    await selects.nth(1).selectOption('');
    const protocolLinks=await page.locator('.gtm-table tbody tr[ng-repeat]').evaluateAll(rows=>rows.map(r=>({protocol:r.querySelector('.gtm-protocol').textContent.trim(),href:r.querySelector('.gtm-connect').getAttribute('href')})));
    for(const protocol of ['rdp','ssh','vnc']) {
        const entry=protocolLinks.find(x=>x.protocol===protocol);
        await check(entry?.href.startsWith('#/client/'),'Native '+protocol+' route exists');
    }
    await page.locator('.gtm-palette-label select').selectOption('dark');
    await check(await page.locator('.gtm').getAttribute('data-palette')==='dark','Personal dark palette applies');
    await page.locator('.gtm-palette-label select').selectOption('default');
    await check(await page.locator('.connection-list-ui').isVisible(),'Personal default restores native view');
    await page.locator('.gtm-native-switch select').selectOption('librenms');
    await page.setViewportSize({width:390,height:844});
    await page.locator('.gtm-menu-toggle').click();
    await check(await page.locator('.gtm-sidebar').evaluate(e=>e.getBoundingClientRect().left===0),'Mobile sidebar opens');
    await check(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),'Mobile page has no horizontal overflow outside table');
    await context.close();
    for(const role of ['editor','auditor','admin','empty']) {
        const {page,context}=await login(role);
        if(role==='empty') {
            await check(await page.locator('.gtm-table tbody tr[ng-repeat]').count()===0,'Empty user receives no demonstration data');
        } else if(role==='editor') {
            await check(await page.locator('.gtm-host button').count()===1,'Editor can reveal only UPDATE-authorized host');
            await page.locator('.gtm-host button').click();
            await page.locator('.gtm-host').filter({hasText:'192.0.2.10'}).waitFor();
            await check(!await page.content().then(x=>x.includes('TEST_ONLY_DO_NOT_RENDER')),'Remote password never rendered');
        } else if(role==='auditor') {
            await check(await page.locator('.gtm-sidebar a[href$="/history"]').count()===1,'Auditor has native history link');
            await check(await page.locator('.gtm-host button').count()===0,'AUDIT does not reveal connection parameters');
        } else {
            await check(await page.locator('.gtm-table tbody tr[ng-repeat]').count()===5,'Admin sees all five entries');
            await check(await page.locator('.gtm-sidebar a[href$="/connections"]').count()===1,'Admin has native settings link');
        }
        await context.close();
    }
    const {page:zh,context:zhContext}=await login('reader','zh_TW');
    await zh.locator('.gtm h1').filter({hasText:'儀表板'}).waitFor();
    await check(await zh.locator('.gtm').innerText().then(x=>!x.includes('GTM.')),'Traditional Chinese GTM keys resolved');
    const nativeLogin=await zh.evaluate(()=>angular.element(document.documentElement).injector().get('$translate').instant('APP.ACTION_LOGIN'));
    await check(nativeLogin!=='APP.ACTION_LOGIN' && nativeLogin!=='Login','Existing native Traditional Chinese translations remain available');
    if(process.env.GTM_SCREENSHOT_DIR) {
        await fs.mkdir(process.env.GTM_SCREENSHOT_DIR,{recursive:true});
        await zh.screenshot({path:process.env.GTM_SCREENSHOT_DIR+'/dashboard-zh-TW.png',fullPage:true});
    }
    await zhContext.close();
    await check(errors.length===0,'No unhandled browser JavaScript errors');
    console.log(JSON.stringify({status:'passed',checks,users:5,note:'Native protocol entry routes verified; remote protocol handshakes require real targets.'}));
} catch (error) {
    console.error('Browser acceptance failed at ' + stage + ' (' + error.name + '). Details suppressed to protect credentials.');
    process.exitCode = 1;
} finally { await browser.close(); }
