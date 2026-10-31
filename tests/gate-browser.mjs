/* SPDX-License-Identifier: Apache-2.0
 * Disposable fixture only. Credentials arrive through stdin; never traced.
 */
import fs from 'node:fs';
const fixture = JSON.parse(fs.readFileSync(0, 'utf8'));
const {chromium} = await import(process.env.GTM_PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({headless:true, args:['--no-sandbox']});
let stage = 'login';
let checks = 0;
let page;
try {
    const context = await browser.newContext();
    page = await context.newPage();
    let scriptError = false;
    page.on('pageerror', () => { scriptError = true; });
    await page.goto(fixture.url);
    stage = 'login form';
    await page.locator('input[name="username"]').fill('gtm-reader');
    await page.locator('input[name="password"]').fill(fixture.password);
    await page.locator('input.login[type="submit"]').click();
    stage = 'home after login';
    await page.locator('.home-view').waitFor({timeout:30000});
    checks++;
    for (const transport of ['HTTP', 'WebSocket']) {
        stage = transport + ' direct tunnel';
        const denied = await page.evaluate(async ({token, transport}) => {
            const tunnel = transport === 'HTTP'
                ? new Guacamole.HTTPTunnel('tunnel')
                : new Guacamole.WebSocketTunnel('websocket-tunnel');
            return await new Promise(resolve => {
                const timeout = setTimeout(() => { tunnel.disconnect(); resolve(false); }, 10000);
                tunnel.onerror = error => {
                    clearTimeout(timeout);
                    const matched = error.code === Guacamole.Status.Code.CLIENT_FORBIDDEN
                        && (transport === 'WebSocket' || error.message === 'PAM_PROBE_DENY_CONNECTION');
                    tunnel.disconnect();
                    resolve(matched);
                };
                tunnel.connect(new URLSearchParams({token, GUAC_DATA_SOURCE:'postgresql',
                    GUAC_TYPE:'c', GUAC_ID:'2', GUAC_WIDTH:'800', GUAC_HEIGHT:'600', GUAC_DPI:'96'}).toString());
            });
        }, {token:fixture.token, transport});
        if (!denied) throw new Error('gate denial missing');
        checks++;
    }
    stage = 'native client URL';
    function recordForbiddenClose() {
        window.__pamProbeForbiddenClose = false;
        const NativeSocket = window.WebSocket;
        window.WebSocket = class extends NativeSocket {
            constructor(...args) {
                super(...args);
                this.addEventListener('close', event => {
                    // Before tunnel creation, official server sends the status
                    // as close reason, without a Guacamole error instruction.
                    if (event.reason === String(Guacamole.Status.Code.CLIENT_FORBIDDEN))
                        window.__pamProbeForbiddenClose = true;
                });
            }
        };
    }
    await page.addInitScript(recordForbiddenClose);
    await page.evaluate(recordForbiddenClose);
    const identifier = Buffer.from('2\0c\0postgresql').toString('base64');
    await page.goto(fixture.url + '#/client/' + encodeURIComponent(identifier));
    await page.waitForFunction(() => window.__pamProbeForbiddenClose === true, {timeout:10000});
    checks++;
    if (scriptError) throw new Error('browser JavaScript failure');
    checks++;
    console.log(JSON.stringify({suite:'G01-browser', passed:checks, http:true, websocket:true, nativeURL:true}));
    await context.close();
} catch {
    console.error('Gate browser acceptance failed at ' + stage + '; private details suppressed.');
    if (page) {
        console.error('Gate browser state: '+JSON.stringify({
            login:await page.locator('input[name="username"]').count(),
            home:await page.locator('.home-view').count(),
            client:await page.locator('.client-view').count(),
            loading:await page.locator('.loading').count(),
            guac:await page.evaluate(() => typeof Guacamole !== 'undefined').catch(() => false),
            state:await page.evaluate(() => ({
                route: location.hash.split('/')[1]?.split('?')[0] || 'empty',
                modal:!!document.querySelector('.global-status-modal'),
                activeLookupDenied:document.body.textContent.includes('PAM_PROBE_DENY_ACTIVE_LOOKUP'),
                groupDenied:document.body.textContent.includes('PAM_PROBE_DENY_GROUP'),
            })).catch(() => null),
        }));
    }
    process.exitCode = 1;
} finally {
    await browser.close();
}
