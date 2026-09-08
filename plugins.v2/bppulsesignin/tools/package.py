"""核对版本、联邦 CSS 并生成 MP 可直接安装的压缩包。"""
import ast
import json
import re
import zipfile
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
ROOT = PLUGIN.parent.parent
metadata = json.loads((ROOT / 'package.v2.json').read_text(encoding='utf-8'))['BpPulseSignin']
version = metadata['version']
assert re.fullmatch(r'\d+\.\d+\.\d+', version), '版本号格式错误'
source = ast.parse((PLUGIN / '__init__.py').read_text(encoding='utf-8'))
cls = next(n for n in source.body if isinstance(n, ast.ClassDef) and n.name == 'BpPulseSignin')
code_version = next(ast.literal_eval(n.value) for n in cls.body if isinstance(n, ast.Assign)
                    and any(isinstance(t,ast.Name) and t.id == 'plugin_version' for t in n.targets))
assert code_version == version, 'Python 与索引版本不一致'
assert json.loads((PLUGIN / 'package.json').read_text())['version'] == version, '前端版本不一致'
assert next(iter(metadata['history'])) == 'v'+version, '当前更新日志未置顶'
for file in PLUGIN.glob('*.py'):
    ast.parse(file.read_text(encoding='utf-8'), filename=str(file))
assets = PLUGIN / 'dist/assets'
assert (assets / 'remoteEntry.js').is_file(), '请先构建前端'
for file in assets.glob('*.css'):
    text = file.read_text(encoding='utf-8')
    assert 'vuetify' not in file.name.lower(), f'包含全局框架 CSS：{file.name}'
    assert not re.search(r'(?:^|[{},])\s*(?:html\b|body\b|:root\b|\.v-|\.mdi-|\.rounded-|\.elevation-)', text), f'包含全局 CSS 选择器：{file.name}'
for file in assets.glob('*.js'):
    text = file.read_text(encoding='utf-8')
    assert 'X-Test-Admin' not in text and 'localhost:8791' not in text, '测试宿主误入生产包'
output = ROOT / '.release'
output.mkdir(exist_ok=True)
archive = output / f'bppulsesignin_v{version}.zip'
files = list(PLUGIN.glob('*.py')) + [PLUGIN / 'README.md'] + [p for p in assets.rglob('*') if p.is_file()]
with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as package:
    for file in sorted(files):
        package.write(file, file.relative_to(PLUGIN).as_posix())
print(archive)
print(f'版本、源码与 CSS 检查通过，已打包 {len(files)} 个文件')
