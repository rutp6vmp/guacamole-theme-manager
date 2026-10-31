/* SPDX-License-Identifier: Apache-2.0
 * Adapter for the Apache Guacamole 1.6.0 AngularJS application.
 * These application services are version-pinned internals, not a public UI API.
 */
(function () {
    'use strict';
    if (!window.angular || !window.GuacThemeModel) return;
    angular.module('index').controller('GuacThemeController', ['$scope', '$injector', '$element',
        function ($scope, $injector, $element) {
            var tm = this, model = window.GuacThemeModel;
            var auth = $injector.get('authenticationService');
            var client = $injector.get('ClientIdentifier');
            var permissions = $injector.get('permissionService');
            var userPages = $injector.get('userPageService');
            var $q = $injector.get('$q');
            var prefs = $injector.get('guacThemePreferences');
            var home = $element.parent();
            var alive = true, permissionSets = Object.create(null);
            var stored = prefs.get();
            tm.rows = []; tm.groups = []; tm.result = []; tm.visible = [];
            tm.settings = []; tm.history = []; tm.page = 0; tm.pageSize = 25;
            tm.query = ''; tm.category = ''; tm.group = null; tm.view = prefs.takeHomeView() || 'dashboard';
            tm.mobileOpen = false; tm.error = false; tm.storageError = false;
            tm.palette = ['librenms', 'dark', 'light', 'default'].indexOf(stored.palette) >= 0
                ? stored.palette : (window.GuacThemeDefaultPalette || 'librenms');
            tm.favorites = Array.isArray(stored.favorites) ? stored.favorites.filter(function (x) { return typeof x === 'string'; }).slice(0, 10000) : [];
            tm.username = auth.getCurrentUsername();
            function save() {
                tm.storageError = prefs.set({palette: tm.palette, favorites: tm.favorites}).storageError;
            }
            tm.applyPalette = function () {
                home.toggleClass('gtm-ready', tm.palette !== 'default' && tm.loaded);
                save();
            };
            $scope.$on('guacThemePreferencesChanged', function () {
                var state = prefs.get(); tm.palette = state.palette; tm.favorites = state.favorites;
                home.toggleClass('gtm-ready', tm.palette !== 'default' && tm.loaded);
            });
            tm.setView = function (view, category) {
                tm.view = view; tm.category = category || ''; tm.group = null; tm.query = '';
                tm.mobileOpen = false; tm.update();
            };
            tm.update = function (keepPage) {
                if (!keepPage) tm.page = 0;
                tm.result = model.filter(tm.rows, {query: tm.query, category: tm.category,
                    group: tm.group, favorites: tm.view === 'favorites'}, tm.favorites);
                tm.pages = Math.max(1, Math.ceil(tm.result.length / tm.pageSize));
                tm.page = Math.min(tm.page, tm.pages - 1);
                tm.visible = tm.result.slice(tm.page * tm.pageSize, (tm.page + 1) * tm.pageSize);
            };
            tm.turn = function (delta) { tm.page += delta; tm.update(true); };
            tm.isFavorite = function (row) { return tm.favorites.indexOf(row.key) !== -1; };
            tm.favorite = function (row) {
                var index = tm.favorites.indexOf(row.key);
                if (index === -1) tm.favorites.push(row.key);
                else tm.favorites.splice(index, 1);
                save(); tm.update(true);
            };
            tm.count = function (category) { return tm.rows.filter(function (r) { return !category || r.category === category; }).length; };
            tm.canReadHost = function (row) { return model.canReadHost(permissionSets[row.source], row); };
            tm.readHost = function (row) {
                if (!tm.canReadHost(row) || row.hostState === 'loading') return;
                row.hostState = 'loading';
                // Unlike connectionService, this request is deliberately not cached.
                // The authorized endpoint returns all parameters; retain only hostname.
                auth.request({method: 'GET', cache: false,
                    url: 'api/session/data/' + encodeURIComponent(row.source) + '/connections/' + encodeURIComponent(row.id) + '/parameters'})
                .then(function (data) {
                    if (!alive) return;
                    row.hostname = typeof data.hostname === 'string' ? data.hostname : '';
                    row.hostState = row.hostname ? 'shown' : 'empty';
                }, function () {
                    if (!alive) return;
                    row.hostname = null; row.hostState = 'denied';
                });
            };
            tm.pageLabel = function (page) { return Array.isArray(page.name) ? page.name[0] : page.name; };
            tm.sourceLabel = function (page) {
                var match = page.url.match(/^\/settings\/([^/]+)\//);
                return match ? decodeURIComponent(match[1]) : '';
            };
            $scope.$watch('rootConnectionGroups', function (roots) {
                if (!roots) return;
                try {
                    var result = model.flatten(roots);
                    tm.rows = result.rows; tm.groups = result.groups;
                    tm.rows.forEach(function (row) {
                        row.href = '#/client/' + client.toString({dataSource: row.source, type: row.type, id: row.id});
                    });
                    tm.loaded = true; tm.update(); tm.applyPalette();
                } catch (ignore) {
                    tm.error = true; home.removeClass('gtm-ready');
                }
            });
            // Fail closed per data source. No guessed permissions or admin links.
            auth.getAvailableDataSources().forEach(function (source) {
                permissions.getEffectivePermissions(source, tm.username).then(function (p) {
                    if (alive) permissionSets[source] = p;
                }, angular.noop);
            });
            $q.when(userPages.getSettingsPages()).then(function (pages) {
                if (!alive) return;
                tm.history = pages.filter(function (p) { return /\/history$/.test(p.url); });
                tm.settings = pages.filter(function (p) { return !/\/history$/.test(p.url); });
            }, angular.noop);
            $scope.$on('$destroy', function () {
                alive = false;
                tm.rows.forEach(function (r) { r.hostname = null; });
                home.removeClass('gtm-ready');
            });
        }]);
}());
