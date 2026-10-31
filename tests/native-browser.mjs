/* SPDX-License-Identifier: Apache-2.0 */
import assert from 'node:assert/strict';
const {chromium}=await import(process.env.GTM_PLAYWRIGHT_MODULE || 'playwright');
const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
let checks=0;
try {
    for(const language of ['en','zh_TW']) {
        const context=await browser.newContext();
        await context.addInitScript(({language})=>localStorage.setItem('GUAC_PREFERENCES',JSON.stringify({language})),{language});
        const page=await context.newPage();
        await page.goto(process.env.GTM_TEST_URL);
        await page.locator('input[name="username"]').fill('gtm-reader');
        await page.locator('input[name="password"]').fill(process.env.GTM_TEST_PASSWORD);
        await page.locator('input.login[type="submit"]').click();
        await page.locator('.home-view .connection-list-ui').waitFor();
        assert.equal(await page.locator('.gtm').count(),0); checks++;
        const result=await page.evaluate(async()=>{
            const injector=angular.element(document.documentElement).injector();
            const auth=injector.get('authenticationService');
            const tree=await injector.get('connectionGroupService').getConnectionGroupTree(auth.getAvailableDataSources()[0],'ROOT');
            const walk=g=>(g.childConnections||[]).length+(g.childConnectionGroups||[]).reduce((n,x)=>n+walk(x),0);
            return {count:walk(tree),login:injector.get('$translate').instant('APP.ACTION_LOGIN')};
        });
        assert.equal(result.count,4); checks++;
        assert(language==='en'?result.login==='Login':result.login!=='Login' && result.login!=='APP.ACTION_LOGIN'); checks++;
        await context.close();
    }
    console.log(JSON.stringify({status:'passed',checks,mode:'native',note:'Login, authorized tree and existing Traditional Chinese without theme.'}));
} catch(error) {
    console.error('Native browser acceptance failed after '+checks+' checks ('+error.name+'). Details suppressed to protect credentials.');
    process.exitCode=1;
} finally {await browser.close();}
