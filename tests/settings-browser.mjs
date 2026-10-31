/* SPDX-License-Identifier: Apache-2.0. Uses tests/seed.py's isolated DB only. */
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
const {chromium}=await import(process.env.GTM_PLAYWRIGHT_MODULE || 'playwright');
const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
const password=process.env.GTM_TEST_PASSWORD;
assert(password);
let checks=0,stage='starting',lastPage,consoleFailures=[];
async function check(condition,message) {stage=message;assert(condition,message);checks++;}
async function login(role,language='en') {
    stage='login '+role;
    const context=await browser.newContext({locale:language==='en'?'en-US':'zh-TW',viewport:{width:1440,height:1000},acceptDownloads:true});
    await context.addInitScript(({language})=>localStorage.setItem('GUAC_PREFERENCES',JSON.stringify({language})),{language});
    const page=await context.newPage();let errors=0;
    lastPage=page;
    page.on('pageerror',()=>errors++);
    page.on('console',msg=>{
        if(msg.type()==='error') {
            const match=msg.text().match(/(?:TypeError|ReferenceError|SyntaxError):[^\n]*/);
            if(match)consoleFailures.push(match[0].replaceAll(password,'[REDACTED]').replace(/[A-Za-z0-9_-]{24,}/g,'[REDACTED]'));
        }
    });
    await page.goto(process.env.GTM_TEST_URL);
    await page.locator('input[name="username"]').fill('gtm-'+role);
    await page.locator('input[name="password"]').fill(password);
    await page.locator('input.login[type="submit"]').click();
    await page.locator('.gtm-shell').waitFor({timeout:30000});
    return {page,context,errorCount:()=>errors};
}
async function route(page,path,selector) {
    stage='route '+path;
    await page.evaluate(path=>{location.hash='#'+path;},path);
    await page.locator('.gtm-native-page').waitFor();
    await page.locator(selector).waitFor();
    await page.waitForFunction(()=>!document.querySelector('.gtm-native-page.loading'));
    await check(await page.locator('guac-theme-settings .gtm-sidebar').isVisible(),'Native page retains themed navigation: '+path);
}
async function save(page,path) {
    await page.locator('.gtm-native-page .action-buttons button.save').click();
    await page.waitForURL(url=>url.hash==='#'+path);
    await page.locator('.gtm-native-page').waitFor();
    await page.locator('.settings.section').first().waitFor();
    await page.waitForFunction(()=>!document.querySelector('.gtm-native-page .settings.section.loading'));
}
async function remove(page,path) {
    stage='delete confirmation';
    await page.locator('.gtm-native-page .action-buttons button.delete').click();
    await page.locator('.global-status-modal .notification').waitFor();
    const above=await page.evaluate(()=>{
        const el=document.elementFromPoint(15,100);
        return !el.closest('.gtm-sidebar');
    });
    await check(above,'Native delete confirmation covers sidebar');
    await page.locator('.global-status-modal button.danger').click();
    await page.waitForURL(url=>url.hash==='#'+path);
    await page.locator('.settings.section').first().waitFor();
    await page.waitForFunction(()=>!document.querySelector('.gtm-native-page .settings.section.loading'));
}
try {
    const reader=await login('reader'),page=reader.page;
    await page.locator('.gtm-sidebar a[href="#/settings/preferences"]').click();
    await page.locator('.gtm-native-page .preferences').waitFor();
    await check(await page.locator('guac-theme-settings .gtm-sidebar a[href="#/settings/users"]').count()===0,'Reader cannot see user management');
    await check(await page.locator('guac-theme-settings .gtm-sidebar a[href$="/history"]').count()===0,'Reader cannot see global history');
    const recent=page.locator('input[ng-model="preferences.showRecentConnections"]');
    await recent.uncheck();
    await page.locator('guac-theme-appearance select').selectOption('dark');
    await check(await page.locator('.gtm-native-page').getAttribute('data-palette')==='dark','Preference palette immediately affects settings');
    await route(page,'/settings/sessions','.sessions');
    await check(await page.locator('.gtm-native-page').getAttribute('data-palette')==='dark','Palette survives changing settings pages');
    await route(page,'/settings/preferences','.preferences');
    await check(!await recent.isChecked(),'Native preferences remain functional');
    await page.locator('guac-theme-appearance select').selectOption('default');
    await check(await page.locator('.gtm-native-page').count()===0,'Default appearance restores native settings layout');
    await page.locator('guac-theme-settings .gtm-native-switch select').selectOption('light');
    await page.locator('.gtm-native-page').waitFor();
    await page.reload();await page.locator('.gtm-native-page').waitFor();
    await check(await page.locator('.gtm-native-page').getAttribute('data-palette')==='light','Palette persists across reload');
    await page.setViewportSize({width:390,height:844});
    await page.locator('guac-theme-settings .gtm-menu-toggle').click();
    await check(await page.locator('guac-theme-settings .gtm-sidebar').evaluate(e=>e.getBoundingClientRect().left===0),'Mobile settings navigation opens');
    await check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Mobile settings do not overflow the viewport');
    await page.setViewportSize({width:1440,height:1000});
    await page.locator('guac-theme-settings .gtm-sidebar a').filter({hasText:'All devices'}).click();
    await page.locator('.gtm-shell').waitFor();
    await check(await page.locator('.gtm h1').innerText()==='All devices','Settings returns to correct dashboard view');
    await check(await page.locator('.gtm').getAttribute('data-palette')==='light','Palette is shared with dashboard');
    await check(reader.errorCount()===0,'Reader navigation has no unhandled JavaScript errors');
    await reader.context.close();

    const editor=await login('editor');
    await route(editor.page,'/manage/postgresql/connections/1','.manage-connection input[ng-model="connection.name"]');
    await editor.page.locator('input[ng-model="connection.name"]').fill('Windows Lab Edited');
    await save(editor.page,'/settings/postgresql/connections');
    await editor.page.locator('.settings-connection').first().waitFor();
    await check(await editor.page.locator('.settings-connection .name').filter({hasText:'Windows Lab Edited'}).count()===1,'Native connection editor saves through backend');
    await route(editor.page,'/manage/postgresql/connections/1','.manage-connection input[ng-model="connection.name"]');
    await editor.page.locator('input[ng-model="connection.name"]').fill('Windows Lab');
    await save(editor.page,'/settings/postgresql/connections');
    await check(editor.errorCount()===0,'Connection editor has no unhandled JavaScript errors');
    await editor.context.close();

    const admin=await login('admin'),a=admin.page;
    for(const [path,selector] of [['/settings/users','.users'],['/settings/userGroups','.user-groups'],
        ['/settings/postgresql/connections','.connections'],['/settings/postgresql/history','.connectionHistory'],
        ['/settings/sessions','.sessions'],['/settings/preferences','.preferences']]) {
        await route(a,path,selector);
        await a.locator('guac-theme-settings a[aria-current="page"]').waitFor();
        await check(await a.locator('guac-theme-settings a[aria-current="page"]').count()===1,'Sidebar highlights current settings page');
    }
    await route(a,'/settings/postgresql/history','.connectionHistory');
    await a.locator('.connectionHistory input.search-string').fill('Windows Lab');
    await a.locator('.connectionHistory input.search-button').click();
    await a.locator('.history-list tbody tr').first().waitFor();
    await check(await a.locator('.history-list').innerText().then(x=>x.includes('Windows Lab')),'History searches real API records');
    const downloadPromise=a.waitForEvent('download');
    await a.locator('.connectionHistory button').filter({hasText:'Download'}).click();
    const download=await downloadPromise;
    await check(download.suggestedFilename().endsWith('.csv'),'History CSV download remains available');
    await route(a,'/manage/postgresql/users/','.manage-user input[ng-model="user.username"]');
    await a.locator('input[ng-model="user.username"]').fill('gtm-created');
    await a.locator('input[ng-model="user.password"]').fill(password);
    await a.locator('input[ng-model="passwordMatch"]').fill(password);
    await save(a,'/settings/users');
    await check(await a.locator('a[href="#/manage/postgresql/users/gtm-created"]').count()===1,'Native user creation succeeds');
    await route(a,'/manage/postgresql/users/gtm-created','.manage-user');
    await remove(a,'/settings/users');
    await check(await a.locator('a[href="#/manage/postgresql/users/gtm-created"]').count()===0,'Native user deletion succeeds');
    await route(a,'/manage/postgresql/userGroups/','.manage-user-group input[ng-model="userGroup.identifier"]');
    await a.locator('input[ng-model="userGroup.identifier"]').fill('gtm-created-group');
    await save(a,'/settings/userGroups');
    await check(await a.locator('a[href="#/manage/postgresql/userGroups/gtm-created-group"]').count()===1,'Native user-group creation succeeds');
    await route(a,'/manage/postgresql/userGroups/gtm-created-group','.manage-user-group');
    await remove(a,'/settings/userGroups');
    await route(a,'/manage/postgresql/connectionGroups/','.manage-connection-group input[ng-model="connectionGroup.name"]');
    await a.locator('input[ng-model="connectionGroup.name"]').fill('GTM New Group');
    await save(a,'/settings/postgresql/connections');
    const groupLink=a.locator('a[href*="/connectionGroups/"]').filter({hasText:'GTM New Group'});
    await groupLink.waitFor();await groupLink.click();
    await a.locator('.gtm-native-page.manage-connection-group').waitFor();
    await remove(a,'/settings/postgresql/connections');
    await route(a,'/manage/postgresql/sharingProfiles/?parent=1','.manage-sharing-profile');
    await route(a,'/import/postgresql/connection','.drop-target');
    await route(a,'/import/connection/file-format-help','.import.help');
    await route(a,'/settings/users','.users');
    await a.locator('guac-theme-settings .gtm-palette-label select').selectOption('dark');
    if(process.env.GTM_SCREENSHOT_DIR) {
        await fs.mkdir(process.env.GTM_SCREENSHOT_DIR,{recursive:true});
        await a.screenshot({path:process.env.GTM_SCREENSHOT_DIR+'/settings-users-dark.png',fullPage:true});
    }
    await check(admin.errorCount()===0,'Admin forms have no unhandled JavaScript errors');
    await admin.context.close();
    const zh=await login('admin','zh_TW');
    await route(zh.page,'/settings/preferences','.preferences');
    await check(await zh.page.locator('guac-theme-appearance').innerText().then(x=>x.includes('外觀')&&!x.includes('GTM.')),'Traditional Chinese settings labels resolve');
    if(process.env.GTM_SCREENSHOT_DIR)await zh.page.screenshot({path:process.env.GTM_SCREENSHOT_DIR+'/settings-preferences-zh-TW.png',fullPage:true});
    await route(zh.page,'/manage/postgresql/connections/','.manage-connection');
    for(const label of ['同時連線限制','同時連線數上限：','每位使用者的同時連線數上限：',
        '負載平衡','連線權重：','僅用於故障轉移：','Guacamole 代理伺服器參數（guacd）',
        '主機名稱：','加密方式：','連接埠：']) {
        await check(await zh.page.locator('.manage-connection .attributes').getByText(label,{exact:true}).isVisible(),
            'Traditional Chinese JDBC connection label: '+label);
    }
    await check(await zh.page.locator('.manage-connection .attributes').innerText().then(
        x=>!/(Concurrency Limits|Load Balancing|Maximum number of connections|Connection weight|Use for failover only)/i.test(x)),
        'Connection attributes have no English fallback labels');
    await route(zh.page,'/manage/postgresql/connectionGroups/','.manage-connection-group');
    for(const label of ['同時連線限制（負載平衡群組）','同時連線數上限：',
        '每位使用者的同時連線數上限：','啟用工作階段親和性：']) {
        await check(await zh.page.locator('.manage-connection-group .attributes').getByText(label,{exact:true}).isVisible(),
            'Traditional Chinese JDBC connection group label: '+label);
    }
    await route(zh.page,'/manage/postgresql/users/gtm-reader','.manage-user');
    for(const label of ['帳號限制','密碼已到期：','每日允許登入的開始時間：','每日允許登入的結束時間：',
        '使用者時區：','帳號啟用日期：','帳號停用日期：','個人資料']) {
        await check(await zh.page.locator('.manage-user .attributes').getByText(label,{exact:true}).isVisible(),
            'Traditional Chinese JDBC user label: '+label);
    }
    await zh.context.close();
    await check(consoleFailures.length===0,'No caught Angular controller errors');
    console.log(JSON.stringify({status:'passed',suite:'settings',checks,nativeCRUD:true}));
}catch(error){
    console.error('Settings acceptance failed at '+stage+' ('+error.name+'). Details suppressed to protect credentials.');
    if(lastPage)try {
        const diagnostic=await lastPage.evaluate(()=>{
            const root=angular.element(document.documentElement).injector().get('$rootScope');
            let scopes=[root],states=[];
            while(scopes.length){const s=scopes.pop();for(let c=s.$$childHead;c;c=c.$$nextSibling)scopes.push(c);
                if(Object.hasOwn(s,'managementPermissions')&&Object.hasOwn(s,'isLoaded'))states.push({loaded:!!s.isLoaded(),dataLoaded:s.connection!==null&&s.userGroups!==null});
            }
            const i=angular.element(document.documentElement).injector(),route=i.get('$route');
            return {states,nativeLoadingCount:document.querySelectorAll('.gtm-native-page.loading').length,
                controller:route.current && route.current.controller,
                pendingRequests:i.get('$http').pendingRequests.length};
        });
        console.error('Settings readiness diagnostic: '+JSON.stringify({...diagnostic,consoleFailures}));
    }catch(ignore){}
    if(process.env.GTM_SCREENSHOT_DIR && lastPage) {
        await fs.mkdir(process.env.GTM_SCREENSHOT_DIR,{recursive:true});
        await lastPage.screenshot({path:process.env.GTM_SCREENSHOT_DIR+'/settings-failure.png',fullPage:true}).catch(()=>{});
    }
    process.exitCode=1;
}finally{await browser.close();}
