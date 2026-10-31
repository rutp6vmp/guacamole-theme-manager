/* SPDX-License-Identifier: Apache-2.0
 * Private JSON-lines stdin/stdout protocol. Never echoes credentials or URLs.
 */
import readline from 'node:readline';
const {chromium} = await import(process.env.GTM_PLAYWRIGHT_MODULE || 'playwright');
const input = readline.createInterface({input:process.stdin, crlfDelay:Infinity});
let browser, page;
const pendingHTTP = [];
const httpReferences = new Map();
for await (const line of input) {
    let reply;
    try {
        const request = JSON.parse(line);
        if (request.op === 'init') {
            browser = await chromium.launch({headless:true,args:['--no-sandbox']});
            page = await browser.newPage();
            page.on('response', async response => {
                try {
                    const address = new URL(response.url());
                    if (!address.pathname.endsWith('/tunnel') || address.search !== '?connect') return;
                    const id = pendingHTTP.shift();
                    if (!id || response.status() !== 200) return;
                    const headers = await response.allHeaders();
                    const uuid = (await response.text()).trim();
                    const token = headers['guacamole-tunnel-token'];
                    if (token && /^[a-f0-9-]{36}$/.test(uuid)) httpReferences.set(id,{uuid,token});
                } catch { /* Never print HTTP responses or bearer credentials. */ }
            });
            await page.goto(request.url);
            await page.waitForFunction(() => typeof Guacamole !== 'undefined');
            await page.evaluate(() => { window.pamSessionClients = {}; });
            reply = {ready:true};
        } else if (request.op === 'open') {
            if (request.transport === 'HTTP') pendingHTTP.push(request.id);
            reply = await page.evaluate(({id,token,connectionId,source,kind,transport}) => {
                const tunnel = transport === 'HTTP' ? new Guacamole.HTTPTunnel('tunnel')
                    : new Guacamole.WebSocketTunnel('websocket-tunnel');
                const client = new Guacamole.Client(tunnel);
                const entry = {client,tunnel,connected:false,closed:false,code:null,frames:0};
                window.pamSessionClients[id] = entry;
                client.onstatechange = state => {
                    if (state === 3) entry.connected = true;
                    if (state === 5) entry.closed = true;
                };
                client.onerror = error => { entry.code = error.code; };
                tunnel.onerror = error => {
                    entry.code = error.code;
                    client.disconnect();
                };
                tunnel.onstatechange = state => {
                    if (state === Guacamole.Tunnel.State.CLOSED) {
                        entry.closed = true;
                        client.disconnect();
                    }
                };
                client.onsync = () => { entry.frames++; };
                client.connect(new URLSearchParams({token,GUAC_DATA_SOURCE:source || 'postgresql',
                    GUAC_TYPE:kind || 'c',GUAC_ID:connectionId,GUAC_WIDTH:'800',GUAC_HEIGHT:'600',GUAC_DPI:'96',
                    GUAC_IMAGE:'image/png',GUAC_TIMEZONE:'UTC'}).toString());
                return {started:true};
            }, request);
        } else if (request.op === 'state') {
            reply = await page.evaluate(id => {
                const entry = window.pamSessionClients[id];
                return {connected:entry.connected,closed:entry.closed,code:entry.code,frames:entry.frames};
            },request.id);
        } else if (request.op === 'send') {
            reply = await page.evaluate(({id,text}) => {
                const client = window.pamSessionClients[id].client;
                for (const char of text) {
                    const keysym = char === '\n' ? 0xff0d : char.codePointAt(0);
                    client.sendKeyEvent(1,keysym); client.sendKeyEvent(0,keysym);
                }
                return {sent:true};
            },request);
        } else if (request.op === 'recording') {
            reply = await page.evaluate(async ({path,token}) => {
                const response = await fetch(path,{headers:{'Guacamole-Token':token}});
                if (!response.ok) return {status:response.status};
                const blob = await response.blob();
                const recording = new Guacamole.SessionRecording(blob);
                let keys=0;
                recording.onkeyevents = events => { keys=events.length; };
                await new Promise((resolve,reject) => {
                    const timeout=setTimeout(()=>reject(new Error('Recording load deadline')),10000);
                    recording.onload=() => {clearTimeout(timeout);resolve();};
                    recording.onerror=() => {clearTimeout(timeout);reject(new Error('Recording load failed'));};
                });
                const duration=recording.getDuration();
                const digest=async () => {
                    await new Promise(resolve => recording.getDisplay().flush(resolve));
                    const canvas=recording.getDisplay().flatten();
                    const pixels=canvas.getContext('2d').getImageData(0,0,canvas.width,canvas.height).data;
                    const hash=await crypto.subtle.digest('SHA-256',pixels);
                    return {width:canvas.width,height:canvas.height,
                        hash:Array.from(new Uint8Array(hash)).map(b=>b.toString(16).padStart(2,'0')).join('')};
                };
                await new Promise(resolve => recording.seek(0,resolve));
                const first=await digest();
                recording.play();
                const limit=Date.now()+Math.min(duration+2500,12000);
                while (recording.getPosition()===0 && Date.now()<limit)
                    await new Promise(resolve=>setTimeout(resolve,50));
                const playedPosition=recording.getPosition();recording.pause();
                await new Promise(resolve => recording.seek(duration,resolve));
                const last=await digest();recording.abort();
                return {status:response.status,bytes:blob.size,duration,keys,playedPosition,first,last,
                    sha256:response.headers.get('X-PAM-Recording-SHA256')};
            },request);
        } else if (request.op === 'disconnect') {
            await page.evaluate(id => window.pamSessionClients[id].client.disconnect(),request.id);
            reply = {closed:true};
        } else if (request.op === 'http-reference') {
            // Private protocol only; caller must never include this in reports.
            const reference = httpReferences.get(request.id);
            if (!reference) throw new Error('HTTP reference unavailable');
            reply = reference;
        } else if (request.op === 'shutdown') {
            await browser.close();
            console.log(JSON.stringify({ok:true,result:{closed:true}}));
            break;
        } else throw new Error('unknown operation');
        console.log(JSON.stringify({ok:true,result:reply}));
    } catch {
        console.log(JSON.stringify({ok:false,error:'Browser fixture operation failed; details suppressed'}));
    }
}
if (browser) await browser.close();
