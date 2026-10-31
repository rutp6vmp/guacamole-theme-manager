#!/usr/bin/env python3
"""Build reproducible static JARs, theme ZIPs, and an installable offline release."""
import hashlib
import importlib.machinery
import importlib.util
import io
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent.parent
loader = importlib.machinery.SourceFileLoader('guac_theme', str(ROOT / 'bin/guac-theme'))
spec = importlib.util.spec_from_loader(loader.name, loader)
gtm = importlib.util.module_from_spec(spec)
loader.exec_module(gtm)


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()


def zip_bytes(files):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(name, (2025, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (0o100755 if name.endswith('.sh') or name.endswith('/guac-theme') else 0o100644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)
    return output.getvalue()


def build():
    dist = ROOT / 'dist'
    dist.mkdir(exist_ok=True)
    artifacts = {}
    for name in ['librenms', 'dark']:
        folder = ROOT / 'themes' / name
        meta = json.loads((folder / 'theme.json').read_bytes())
        manifest = (folder / 'guac-manifest.json').read_bytes()
        files = {'guac-manifest.json': manifest, 'theme-marker.json': json_bytes({'id': name, 'version': meta['version']})}
        common = ROOT / 'themes/common'
        for src, dest in {'dashboard.css': 'css/dashboard.css', 'model.js': 'js/model.js',
                          'dashboard.js': 'js/dashboard.js', 'dashboard.html': 'html/dashboard.html',
                          'settings.js': 'js/settings.js', 'settings.css': 'css/settings.css',
                          'settings-patch.html': 'html/settings-patch.html',
                          'appearance-patch.html': 'html/appearance-patch.html',
                          'settings-chrome.html': 'html/settings-chrome.html',
                          'en.json': 'translations/en.json', 'zh_TW.json': 'translations/zh_TW.json'}.items():
            files[dest] = (common / src).read_bytes()
        files['js/default.js'] = ('window.GuacThemeDefaultPalette = ' + json.dumps(name) + ';\n' +
            'window.GuacThemeNamespace = ' + json.dumps('gtm-' + name) + ';\n' +
            'window.GuacThemeVersion = ' + json.dumps(meta['version']) + ';\n').encode()
        jar = zip_bytes(files)
        meta['sha256'] = {meta['entry']: gtm.digest(jar)}
        package = {'theme.json': json_bytes(meta), meta['entry']: jar}
        package['SHA256SUMS'] = ''.join(gtm.digest(data) + '  ' + path + '\n' for path, data in sorted(package.items())).encode()
        packed = zip_bytes(package)
        gtm.validate_package(packed)
        artifacts[meta['entry']] = jar
        artifacts['guac-theme-' + name + '-' + meta['version'] + '.zip'] = packed
    # Independent language overlay also works with the native interface.
    language = ROOT / 'themes/jdbc-zh-tw'
    artifacts['guacamole-jdbc-zh-tw-1.0.0.jar'] = zip_bytes({
        'guac-manifest.json': (language / 'guac-manifest.json').read_bytes(),
        'translations/zh_TW.json': (language / 'zh_TW.json').read_bytes(),
    })
    # Source and prebuilt packages are distributed together; no compiler required.
    release_files = {}
    for group in ['bin', 'scripts', 'themes', 'docs', 'tests', 'modules', '.github']:
        for p in sorted((ROOT / group).rglob('*')):
            if p.is_file() and '__pycache__' not in p.parts:
                release_files['guacamole-theme-manager/' + p.relative_to(ROOT).as_posix()] = p.read_bytes()
    for name in ['README.md', 'README.en.md', 'LICENSE', 'NOTICE', '.gitignore']:
        if (ROOT / name).exists():
            release_files['guacamole-theme-manager/' + name] = (ROOT / name).read_bytes()
    for name, data in artifacts.items():
        release_files['guacamole-theme-manager/dist/' + name] = data
    inner_sums = ''.join(gtm.digest(data) + '  ' + name + '\n' for name, data in sorted(artifacts.items())).encode()
    release_files['guacamole-theme-manager/dist/SHA256SUMS'] = inner_sums
    artifacts['guacamole-theme-manager-' + gtm.VERSION + '.zip'] = zip_bytes(release_files)
    for name, data in artifacts.items():
        (dist / name).write_bytes(data)
    (dist / 'SHA256SUMS').write_text(''.join(gtm.digest(data) + '  ' + name + '\n' for name, data in sorted(artifacts.items())))
    print('Built and validated ' + str(len(artifacts)) + ' release artifacts in dist/')


if __name__ == '__main__':
    build()
