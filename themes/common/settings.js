/* SPDX-License-Identifier: Apache-2.0
 * Version-pinned chrome for Guacamole 1.6.0 native settings/editors.
 * Forms, authorization, validation and persistence remain native.
 */
(function () {
    'use strict';
    var app = angular.module('index');
    app.factory('guacThemePreferences', ['$injector', function ($injector) {
        var auth = $injector.get('authenticationService');
        var root = $injector.get('$rootScope');
        var cachedKey, cached, pendingView;
        function key() {
            return 'guac-theme:v1:' + JSON.stringify([location.pathname, auth.getDataSource(), auth.getCurrentUsername()]);
        }
        function get() {
            var current = key();
            if (cachedKey === current && cached) return cached;
            var value = {};
            try { value = JSON.parse(localStorage.getItem(current) || '{}') || {}; } catch (ignore) {}
            cachedKey = current;
            cached = {
                palette: ['librenms', 'dark', 'light', 'default'].indexOf(value.palette) >= 0 ? value.palette : window.GuacThemeDefaultPalette || 'librenms',
                favorites: Array.isArray(value.favorites) ? value.favorites.filter(function (v) { return typeof v === 'string'; }).slice(0, 10000) : [],
                storageError: false
            };
            return cached;
        }
        function set(value) {
            var state = get();
            if (['librenms', 'dark', 'light', 'default'].indexOf(value.palette) >= 0) state.palette = value.palette;
            if (Array.isArray(value.favorites)) state.favorites = value.favorites.slice(0, 10000);
            try { localStorage.setItem(key(), JSON.stringify({palette: state.palette, favorites: state.favorites})); }
            catch (ignore) { state.storageError = true; }
            root.$broadcast('guacThemePreferencesChanged');
            return state;
        }
        return {get: get, set: set,
            goHome: function (view) { pendingView = {key: key(), view: view}; },
            takeHomeView: function () { var next = pendingView; pendingView = null; return next && next.key === key() ? next.view : null; }};
    }]);

    app.directive('guacThemeSettings', [function () {
        return {
            restrict: 'E', scope: {}, controllerAs: 'chrome',
            templateUrl: 'app/ext/' + window.GuacThemeNamespace + '/html/settings-chrome.html',
            controller: ['$scope', '$element', '$injector', function ($scope, $element, $injector) {
                var chrome = this, host = $element.parent();
                var prefs = $injector.get('guacThemePreferences');
                var location = $injector.get('$location');
                var auth = $injector.get('authenticationService');
                chrome.pages = []; chrome.history = []; chrome.mobileOpen = false;
                chrome.version = window.GuacThemeVersion;
                chrome.username = auth.getCurrentUsername();
                chrome.pageLabel = function (page) { return Array.isArray(page.name) ? page.name[0] : page.name; };
                chrome.sourceLabel = function (page) {
                    var match = page.url.match(/^\/settings\/([^/]+)\//);
                    return match ? decodeURIComponent(match[1]) : '';
                };
                chrome.isCurrent = function (page) {
                    var path = location.path();
                    if (path === page.url) return true;
                    var editor = path.match(/^\/manage\/([^/]+)\/([^/]+)/);
                    if (!editor) return false;
                    var tab = editor[2] === 'connectionGroups' || editor[2] === 'sharingProfiles' ? 'connections' : editor[2];
                    return page.url === '/settings/' + editor[1] + '/' + tab || page.url === '/settings/' + tab;
                };
                var editor = location.path().match(/^\/(manage|import)\/([^/]+)\/([^/]+)/);
                chrome.backHref = '#/';
                if (editor && !(editor[1] === 'import' && editor[2] === 'connection')) {
                    var tab = editor[3];
                    chrome.backHref = '#/settings/' + ((tab === 'users' || tab === 'userGroups') ? tab : editor[2] + '/connections');
                }
                function sync() {
                    var state = prefs.get(); chrome.palette = state.palette; chrome.storageError = state.storageError;
                    // Update classes after native ngClass has applied its loading
                    // state. Never make the theme own a native loading indicator.
                    $scope.$$postDigest(function () {
                        if ($scope.$$destroyed) return;
                        host.toggleClass('gtm', chrome.palette !== 'default');
                        host.toggleClass('gtm-native-page', chrome.palette !== 'default');
                        host.attr('data-palette', chrome.palette);
                    });
                }
                chrome.applyPalette = function () { prefs.set({palette: chrome.palette}); };
                chrome.goHome = function (view) { prefs.goHome(view); };
                sync();
                $scope.$on('guacThemePreferencesChanged', sync);
                $injector.get('userPageService').getSettingsPages().then(function (pages) {
                    if ($scope.$$destroyed) return;
                    chrome.pages = pages.filter(function (p) { return !/\/history$/.test(p.url); });
                    chrome.history = pages.filter(function (p) { return /\/history$/.test(p.url); });
                }, angular.noop);
                $scope.$on('$destroy', function () { host.removeClass('gtm gtm-native-page'); host.removeAttr('data-palette'); });
            }]
        };
    }]);

    app.directive('guacThemeAppearance', [function () {
        return {restrict: 'E', scope: {}, controllerAs: 'appearance',
            template: '<div class="gtm gtm-appearance" data-palette="{{appearance.palette}}"><label>{{"GTM.PALETTE" | translate}} ' +
                '<select ng-model="appearance.palette" ng-change="appearance.save()" aria-label="{{\'GTM.PALETTE\' | translate}}">' +
                '<option value="librenms">LibreNMS</option><option value="dark">Dark</option><option value="light">Light</option>' +
                '<option value="default">{{"GTM.DEFAULT" | translate}}</option></select></label><p>{{"GTM.APPEARANCE_HELP" | translate}}</p></div>',
            controller: ['$scope', 'guacThemePreferences', function ($scope, prefs) {
                var vm = this;
                vm.palette = prefs.get().palette;
                vm.save = function () { prefs.set({palette: vm.palette}); };
                $scope.$on('guacThemePreferencesChanged', function () { vm.palette = prefs.get().palette; });
            }]};
    }]);
}());
