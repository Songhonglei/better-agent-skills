"""init-hooks 安全回归测试（对应 v1.0.2 修的两处审计问题）。

1. 校验失败必须"失败关闭"，不得把上一轮的旧脚本顶上来执行。
2. 解包不允许经符号链接/硬链接/越界路径写到目标目录之外。
"""

import importlib.util
import io
import shutil
import subprocess
import tarfile
import zipfile
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[1] / 'skills' / 'init-hooks'
spec = importlib.util.spec_from_file_location('init_hooks_under_test', SKILL / 'scripts/manage.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


# ── 构造恶意/正常压缩包 ────────────────────────────────────────────────
def _tar(path: Path, members):
    """members: [(name, kind, payload)]，kind = file / sym / link / dir"""
    with tarfile.open(path, 'w:gz') as tf:
        for name, kind, payload in members:
            ti = tarfile.TarInfo(name)
            if kind == 'sym':
                ti.type = tarfile.SYMTYPE
                ti.linkname = payload
                tf.addfile(ti)
            elif kind == 'link':
                ti.type = tarfile.LNKTYPE
                ti.linkname = payload
                tf.addfile(ti)
            elif kind == 'dir':
                ti.type = tarfile.DIRTYPE
                tf.addfile(ti)
            else:
                data = payload.encode()
                ti.size = len(data)
                ti.mode = 0o755
                tf.addfile(ti, io.BytesIO(data))
    return path


def _zip(path: Path, members):
    with zipfile.ZipFile(path, 'w') as zf:
        for name, kind, payload in members:
            if kind == 'sym':
                info = zipfile.ZipInfo(name)
                info.external_attr = (0o120777 << 16) | 0o20
                zf.writestr(info, payload)
            else:
                zf.writestr(name, payload)
    return path


# ── 问题 2：解包不得越界 ───────────────────────────────────────────────
def test_tar_symlink_escape_rejected(tmp_path):
    outside = tmp_path / 'outside'
    outside.mkdir()
    dest = tmp_path / 'dest'
    pkg = _tar(tmp_path / 'evil.tar.gz', [
        ('link', 'sym', str(outside)),
        ('link/pwn.sh', 'file', 'echo PWNED\n'),
    ])
    with tarfile.open(pkg) as tf:
        with pytest.raises(ValueError):
            m._safe_extract_tar(tf, dest)
    assert list(outside.iterdir()) == []


def test_tar_hardlink_escape_rejected(tmp_path):
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'target.sh').write_text('echo T\n')
    dest = tmp_path / 'dest'
    pkg = _tar(tmp_path / 'hard.tar.gz', [
        ('h', 'link', str(outside / 'target.sh')),
    ])
    with tarfile.open(pkg) as tf:
        with pytest.raises(ValueError):
            m._safe_extract_tar(tf, dest)


@pytest.mark.parametrize('name', ['../evil.sh', '/abs/evil.sh', 'a/../../evil.sh'])
def test_tar_traversal_and_absolute_rejected(tmp_path, name):
    dest = tmp_path / 'dest'
    pkg = _tar(tmp_path / 'trav.tar.gz', [(name, 'file', 'echo X\n')])
    with tarfile.open(pkg) as tf:
        with pytest.raises(ValueError):
            m._safe_extract_tar(tf, dest)
    assert not (tmp_path / 'evil.sh').exists()


def test_tar_rejects_write_through_residual_symlink(tmp_path):
    """目标目录里残留的符号链接目录，不能成为写出跳板。"""
    outside = tmp_path / 'outside'
    outside.mkdir()
    dest = tmp_path / 'dest'
    dest.mkdir()
    (dest / 'sub').symlink_to(outside)
    pkg = _tar(tmp_path / 'resid.tar.gz', [('sub/x.sh', 'file', 'echo X\n')])
    with tarfile.open(pkg) as tf:
        with pytest.raises(ValueError):
            m._safe_extract_tar(tf, dest)
    assert list(outside.iterdir()) == []


def test_tar_normal_package_extracts(tmp_path):
    dest = tmp_path / 'dest'
    pkg = _tar(tmp_path / 'ok.tar.gz', [
        ('dir', 'dir', None),
        ('dir/run.sh', 'file', 'echo OK\n'),
    ])
    with tarfile.open(pkg) as tf:
        m._safe_extract_tar(tf, dest)
    assert (dest / 'dir' / 'run.sh').read_text() == 'echo OK\n'


def test_zip_symlink_and_traversal_rejected(tmp_path):
    outside = tmp_path / 'outside'
    outside.mkdir()
    dest = tmp_path / 'dest'
    link_pkg = _zip(tmp_path / 'link.zip', [('slink', 'sym', str(outside))])
    with zipfile.ZipFile(link_pkg) as zf:
        with pytest.raises(ValueError):
            m._safe_extract_zip(zf, dest)

    trav_pkg = _zip(tmp_path / 'trav.zip', [('../../evil.sh', 'file', 'echo X\n')])
    with zipfile.ZipFile(trav_pkg) as zf:
        with pytest.raises(ValueError):
            m._safe_extract_zip(zf, dest)
    assert not (tmp_path / 'evil.sh').exists()


def test_zip_normal_package_extracts(tmp_path):
    dest = tmp_path / 'dest'
    pkg = _zip(tmp_path / 'ok.zip', [('run.sh', 'file', 'echo OK\n')])
    with zipfile.ZipFile(pkg) as zf:
        m._safe_extract_zip(zf, dest)
    assert (dest / 'run.sh').read_text() == 'echo OK\n'


def test_extract_never_uses_extractall(tmp_path):
    """回归护栏：解包实现不得退回 tarfile/zipfile 的 extractall。"""
    src = (SKILL / 'scripts' / 'manage.py').read_text()
    assert '.extractall(' not in src


# ── 问题 1：校验失败必须失败关闭 ───────────────────────────────────────
@pytest.fixture()
def hooks_env(tmp_path, monkeypatch):
    base = tmp_path / '.init-hooks'
    base.mkdir()
    monkeypatch.setattr(m, 'HOOKS_DIR', base)
    monkeypatch.setattr(m, 'HOOKS_JSON', base / 'hooks.json')
    monkeypatch.setattr(m, 'DISPATCHER', base / 'dispatcher.sh')
    monkeypatch.setattr(m, 'LOG_FILE', base / 'last-run.log')
    monkeypatch.setattr(m, 'DOWNLOAD_DIR', base / 'downloads')
    (base / 'downloads').mkdir()
    return base


def _write_hook(base: Path, hook: dict):
    import json
    (base / 'hooks.json').write_text(json.dumps({'version': 1, 'hooks': [hook]}, ensure_ascii=False))


def test_dispatcher_does_not_run_stale_script_on_checksum_failure(hooks_env):
    base = hooks_env
    marker = base / 'stale-ran.txt'
    stale = base / 'downloads' / 'hook_1.sh'
    stale.write_text(f'echo stale >> "{marker}"\n')

    _write_hook(base, {
        'id': 1, 'name': 'bad', 'type': 'script', 'enabled': True, 'order': 10,
        'url': f'file://{base}/nonexistent.tar.gz',
        'sha256': '0' * 64,
    })
    m.generate_dispatcher(m.load_hooks())

    proc = subprocess.run(['bash', str(base / 'dispatcher.sh')],
                          capture_output=True, text=True, timeout=60)
    assert not marker.exists(), '校验失败后仍执行了上一轮的旧脚本'
    assert '❌ #1 失败' in proc.stdout
    assert not stale.exists(), '失败时必须清掉可执行入口（失败关闭）'


def test_dispatcher_condition_is_chained(hooks_env):
    _write_hook(hooks_env, {
        'id': 1, 'name': 'bad', 'type': 'script', 'enabled': True, 'order': 10,
        'url': 'https://example.invalid/pkg.tar.gz', 'sha256': '1' * 64,
    })
    m.generate_dispatcher(m.load_hooks())
    text = (hooks_env / 'dispatcher.sh').read_text()
    assert 'rm -f "$DOWNLOAD_DIR/hook_1.sh"' in text
    assert 'if _ih_download ' in text
    assert text.count('_ih_extract "$DOWNLOAD_DIR/hook_1_archive"') == 1
    # 解压必须是 if 条件链的一环，而不是独立语句
    idx = text.index('_ih_extract "$DOWNLOAD_DIR/hook_1_archive"')
    assert text[idx - 1:idx] == ' '  # 续行缩进
    assert text[:idx].rstrip().endswith('&&')
