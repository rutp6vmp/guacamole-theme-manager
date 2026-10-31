/* SPDX-License-Identifier: Apache-2.0 */
const test = require('node:test');
const assert = require('node:assert/strict');
const m = require('../themes/common/model.js');
const roots = {
    primary: {childConnections: [{identifier: '1', name: 'Windows', protocol: 'rdp'}], childConnectionGroups: [
        {identifier:'network', name:'Network', type:'ORGANIZATIONAL', childConnections:[{identifier:'2',name:'Router',protocol:'ssh'}]},
        {identifier:'linux', name:'Servers', childConnectionGroups:[{identifier:'nested',name:'Nested',childConnections:[{identifier:'3',name:'Linux',protocol:'ssh'}]}]},
        {identifier:'balanced',name:'Pool',type:'BALANCING',childConnections:[]}
    ]},
    secondary: {childConnections: [{identifier:'1',name:'VNC',protocol:'vnc'}]}
};
test('flattens only returned authorized trees and keeps balancing connections', () => {
    const {rows,groups}=m.flatten(roots);
    assert.equal(rows.length,5); assert.equal(groups.length,4);
    assert.equal(rows.find(r=>r.name==='Pool').type,'g');
    assert.equal(rows.find(r=>r.name==='Router').category,'network');
    assert.equal(rows.find(r=>r.name==='Linux').category,'linux');
});
test('IDs cannot collide across data sources or object types',()=>{
    const rows=m.flatten(roots).rows;
    assert.equal(new Set(rows.map(r=>r.key)).size,5);
    assert.notEqual(m.key('primary','c','1'),m.key('secondary','c','1'));
    assert.notEqual(m.key('primary','c','1'),m.key('primary','g','1'));
});
test('search matches names, sources, protocols and nested groups',()=>{
    const rows=m.flatten(roots).rows;
    assert.equal(m.filter(rows,{query:'LiNuX'},[]).length,1);
    assert.equal(m.filter(rows,{query:'nested'},[]).length,1);
    assert.equal(m.filter(rows,{query:'secondary'},[]).length,1);
    assert.equal(m.filter(rows,{category:'network'},[])[0].name,'Router');
});
test('group filter includes descendants and favorites are limited to current authorized rows',()=>{
    const rows=m.flatten(roots).rows;
    assert.equal(m.filter(rows,{group:m.key('primary','g','linux')},[])[0].name,'Linux');
    assert.equal(m.filter(rows,{favorites:true},[rows[0].key,'unreadable']).length,1);
});
test('host requires UPDATE on that exact connection or system ADMINISTER',()=>{
    const row=m.flatten(roots).rows.find(r=>r.id==='2');
    assert.equal(m.canReadHost(null,row),false);
    assert.equal(m.canReadHost({connectionPermissions:{'2':['READ']}},row),false);
    assert.equal(m.canReadHost({connectionPermissions:{'3':['UPDATE']}},row),false);
    assert.equal(m.canReadHost({connectionPermissions:{'2':['UPDATE']}},row),true);
    assert.equal(m.canReadHost({systemPermissions:['AUDIT']},row),false);
    assert.equal(m.canReadHost({systemPermissions:['ADMINISTER']},row),true);
    assert.equal(m.canReadHost({systemPermissions:['ADMINISTER']},{...row,type:'g'}),false);
});
test('empty data produces an empty inventory, never demonstration data',()=>{
    assert.deepEqual(m.flatten(null),{rows:[],groups:[]});
});
