"""Prepare the generated Android project without committing machine-specific files."""
from pathlib import Path
import os
import re
import shutil
import xml.etree.ElementTree as ET

project = Path(__file__).resolve().parents[1] / 'src-tauri/gen/android'
manifest = project / 'app/src/main/AndroidManifest.xml'
namespace = 'http://schemas.android.com/apk/res/android'
ET.register_namespace('android', namespace)
tree = ET.parse(manifest)
for permission in ('android.permission.ACCESS_WIFI_STATE', 'android.permission.CHANGE_WIFI_MULTICAST_STATE', 'android.permission.ACCESS_LOCAL_NETWORK'):
    if not any(node.get(f'{{{namespace}}}name') == permission for node in tree.getroot().findall('uses-permission')):
        ET.SubElement(tree.getroot(), 'uses-permission', {f'{{{namespace}}}name': permission})
activity = project / 'app/src/main/java/com/nautilus/validation/MainActivity.kt'
shutil.copyfile(Path(__file__).resolve().parents[1] / 'android/MainActivity.kt', activity)
credential_plugin = activity.with_name('CredentialPlugin.kt')
shutil.copyfile(Path(__file__).resolve().parents[1] / 'android/CredentialPlugin.kt', credential_plugin)

application = tree.getroot().find('application')
if application is None:
    raise SystemExit('Android manifest has no application')
application.set(f'{{{namespace}}}allowBackup', 'false')
application.set(f'{{{namespace}}}fullBackupContent', 'false')
application.set(f'{{{namespace}}}dataExtractionRules', '@xml/data_extraction_rules')
resources = manifest.parent / 'res/xml'
resources.mkdir(parents=True, exist_ok=True)
(resources / 'data_extraction_rules.xml').write_text('''<?xml version="1.0" encoding="utf-8"?>
<data-extraction-rules>
  <cloud-backup><exclude domain="root" path="."/><exclude domain="file" path="."/><exclude domain="database" path="."/><exclude domain="sharedpref" path="."/><exclude domain="external" path="."/></cloud-backup>
  <device-transfer><exclude domain="root" path="."/><exclude domain="file" path="."/><exclude domain="database" path="."/><exclude domain="sharedpref" path="."/><exclude domain="external" path="."/></device-transfer>
</data-extraction-rules>
''')
tree.write(manifest, encoding='utf-8', xml_declaration=True)

# CLI is shared with the existing frontend rather than installed in this directory.
for task in (project / 'buildSrc/src/main/java').rglob('BuildTask.kt'):
    source = task.read_text().replace(
        'listOf("tauri", "android", "android-studio-script")',
        'listOf("../../frontend/node_modules/@tauri-apps/cli/tauri.js", "android", "android-studio-script")',
    )
    task.write_text(source)

# Retain symbols in native/target for diagnosis, but strip them from the install APK.
gradle = project / 'app/build.gradle.kts'
source = re.sub(r'^\s*jniLibs\.keepDebugSymbols\.add\([^\n]*\)\n', '', gradle.read_text(), flags=re.MULTILINE)
source = source.replace('isJniDebuggable = true', 'isJniDebuggable = false')
if ndk := os.environ.get('NDK_HOME'):
    properties = (Path(ndk) / 'source.properties').read_text()
    revision = re.search(r'^Pkg.Revision\s*=\s*([0-9.]+)\s*$', properties, re.MULTILINE)
    if not revision:
        raise SystemExit('NDK version is unavailable')
    source = re.sub(r'^\s*ndkVersion\s*=.*\n', '', source, flags=re.MULTILINE)
    source = source.replace('android {\n', f'android {{\n    ndkVersion = "{revision[1]}"\n', 1)
gradle.write_text(source)

# Optional verified official Maven cache, for hosts whose Java HTTPS downloads fail.
if cache := os.environ.get('NAUTILUS_MAVEN_CACHE'):
    repositories = [f'maven {{ url = uri("{(Path(cache).resolve() / name).as_uri()}") }}' for name in ('google', 'central')]
    for relative in ('build.gradle.kts', 'buildSrc/build.gradle.kts'):
        gradle = project / relative
        source = gradle.read_text()
        for repository in repositories:
            source = source.replace(repository, '')
        source = source.replace('google()', '\n        '.join(repositories) + '\n        google()')
        gradle.write_text(source)
print('Android validation project prepared')
