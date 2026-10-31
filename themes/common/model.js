/* SPDX-License-Identifier: Apache-2.0 */
(function (root, factory) {
    'use strict';
    if (typeof module === 'object' && module.exports) module.exports = factory();
    else root.GuacThemeModel = factory();
}(typeof window !== 'undefined' ? window : globalThis, function () {
    'use strict';
    function key(source, type, id) { return JSON.stringify([source, type, String(id)]); }
    function flatten(roots) {
        var rows = [], groups = [];
        Object.keys(roots || {}).forEach(function (source) {
            function walk(group, path, ancestry, depth) {
                if (!group || depth > 100) return;
                var nextPath = path, nextAncestry = ancestry;
                if (depth) {
                    nextPath = path.concat([group.name]);
                    nextAncestry = ancestry.concat([key(source, 'g', group.identifier)]);
                    groups.push({key: key(source, 'g', group.identifier), name: nextPath.join(' / '), source: source});
                    if (group.type === 'BALANCING') add(group, 'g', 'BALANCING', nextPath, nextAncestry);
                }
                (group.childConnections || []).forEach(function (c) { add(c, 'c', c.protocol || '', nextPath, nextAncestry); });
                (group.childConnectionGroups || []).forEach(function (g) { walk(g, nextPath, nextAncestry, depth + 1); });
            }
            function add(c, type, protocol, path, ancestry) {
                var group = path.join(' / '), category = 'other';
                if (/network|switch|router|firewall|網路|交換器|路由器|防火牆/i.test(group)) category = 'network';
                else if (protocol === 'rdp') category = 'windows';
                else if (protocol === 'ssh') category = 'linux';
                rows.push({key: key(source, type, c.identifier), id: String(c.identifier), source: source,
                    type: type, name: c.name, protocol: protocol, group: group, ancestry: ancestry,
                    category: category, hostname: null, hostState: 'hidden'});
            }
            walk(roots[source], [], [], 0);
        });
        rows.sort(function (a, b) { return String(a.name).localeCompare(String(b.name)); });
        return {rows: rows, groups: groups};
    }
    function filter(rows, options, favorites) {
        var query = (options.query || '').toLocaleLowerCase();
        return rows.filter(function (r) {
            return (!options.category || r.category === options.category)
                && (!options.group || r.ancestry.indexOf(options.group) !== -1)
                && (!options.favorites || favorites.indexOf(r.key) !== -1)
                && (!query || [r.name, r.protocol, r.group, r.source, r.hostname || ''].join(' ').toLocaleLowerCase().indexOf(query) !== -1);
        });
    }
    function canReadHost(permissions, row) {
        return row.type === 'c' && !!permissions && ((permissions.systemPermissions || []).indexOf('ADMINISTER') !== -1
            || ((permissions.connectionPermissions || {})[row.id] || []).indexOf('UPDATE') !== -1);
    }
    return {key: key, flatten: flatten, filter: filter, canReadHost: canReadHost};
}));
