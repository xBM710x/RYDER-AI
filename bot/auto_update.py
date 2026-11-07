"""Mac background owner: staged, offline-tested fast-forward updates. Paper only."""
import fcntl
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time

BOT = Path(__file__).resolve().parent
ROOT = BOT.parent
PY = str(BOT / '.venv/bin/python')
STOP = False
CHILD = None
TESTS = ['test_paper_account', 'test_app_upgrades', 'test_source_performance', 'test_auto_update', 'test_mission_control', 'test_market_lab', 'test_decision_review', 'test_desk_five', 'test_reliability', 'test_volume_research', 'test_session_research', 'test_paper_entry_window', 'test_discovery_worker', 'test_strategy_desk','test_intelligence','test_decision_ops','test_desk_insights']


def state(value):
    import json
    try:
        data = dict(ts=time.time(), state=value)
        try: data['commit'] = git('rev-parse', 'HEAD')
        except Exception: pass
        tmp = BOT/'updater-status.json.tmp'
        tmp.write_text(json.dumps(data)); os.replace(tmp, BOT/'updater-status.json')
    except OSError: pass


def log(message):
    state(message)
    print(time.strftime('%Y-%m-%d %H:%M:%S'), message, flush=True)


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args], stderr=subprocess.DEVNULL, timeout=90).decode().strip()


def allowed(paths):
    # Do not accept updates to secrets, runtime ledgers or dependency sets.
    for path in paths:
        p = Path(path)
        if p.name == 'requirements.txt' or p.name == '.env' or p.suffix in ('.db', '.jsonl'):
            return False
        if path.startswith('bot/') and p.suffix not in ('.py', '.sh', '.md', '.plist', '.bat'):
            return False
    return True


def validate(stage, python=PY):
    bot = Path(stage)/'bot'
    # Compile without executing the trading runner; never use the real state directory.
    result = subprocess.run([python, '-m', 'compileall', '-q', str(bot)], timeout=60, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if result.returncode: return False
    env = dict(os.environ)
    env.pop('PYTHONPATH', None)
    for name in list(env):
        if 'TOKEN' in name or 'SECRET' in name: env.pop(name, None)
    env['RYDER_SHARED_PAPER_ACCOUNT'] = '1'
    result = subprocess.run([python, '-m', 'unittest', *TESTS], cwd=bot, env=env, timeout=120, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return result.returncode == 0


def backup():
    db = BOT/'desk.db'
    if not db.exists(): return
    dest = BOT/'update-backups';dest.mkdir(exist_ok=True, mode=0o700)
    path = dest/('desk-'+str(time.time_ns())+'.db')
    with sqlite3.connect(db.as_uri()+'?mode=ro', uri=True) as source, sqlite3.connect(str(path)) as target:
        source.backup(target)
        if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise RuntimeError('backup integrity check failed')
    os.chmod(path, 0o600)
    import json
    path.with_name(path.name+'.checked.json').write_text(json.dumps(dict(integrity='ok',ts=time.time())))


def stop_child():
    global CHILD
    if CHILD is None: return
    # start.sh/caffeinate, supervisor and workers share this private process group.
    try: os.killpg(CHILD.pid, signal.SIGTERM)
    except ProcessLookupError: pass
    try: CHILD.wait(timeout=20)
    except subprocess.TimeoutExpired:
        os.killpg(CHILD.pid, signal.SIGKILL); CHILD.wait(timeout=5)
    CHILD = None


def start_child():
    global CHILD
    CHILD = subprocess.Popen(['/bin/bash', str(BOT/'start.sh')], cwd=BOT, start_new_session=True, stdin=subprocess.DEVNULL)


def update():
    if git('branch', '--show-current') != 'main': return False
    if git('status', '--porcelain', '--untracked-files=no'):
        log('Update held: tracked local changes; running version retained');return False
    if git('remote', 'get-url', 'origin') not in ('https://github.com/xBM710x/RYDER-AI.git', 'git@github.com:xBM710x/RYDER-AI.git'):
        log('Update held: unexpected repository origin');return False
    git('fetch', 'origin', 'main')
    state('checked remote main')
    old = git('rev-parse', 'HEAD'); new = git('rev-parse', 'origin/main')
    if old == new:
        state('checked; up to date');return False
    git('merge-base', '--is-ancestor', old, new)
    paths = git('diff', '--name-only', old, new).splitlines()
    if not allowed(paths):
        log('Update held: dependencies or runtime-file changes need manual review');return False
    # Publishing data.json alone should not interrupt scanning.
    if not any(p.startswith('bot/') for p in paths):
        git('merge', '--ff-only', new);state('dashboard refreshed; bot code unchanged');return False
    with tempfile.TemporaryDirectory(prefix='ryder-check-') as td:
        # Archive via git checkout-index into isolated worktree; no state or .env copied.
        archive = Path(td)/'candidate.tar'
        subprocess.run(['git','-C',str(ROOT),'archive','--format=tar','-o',str(archive),new],check=True,timeout=30,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        import tarfile
        with tarfile.open(archive) as tar:
            # Repository-controlled tree; reject escaping paths and links before extraction.
            members=tar.getmembers()
            if any(Path(m.name).is_absolute() or '..' in Path(m.name).parts or m.issym() or m.islnk() for m in members):
                log('Update held: unsafe archive entry');return False
            tar.extractall(td, members=members)
        if not validate(td):
            log('Update held: candidate checks failed; running version retained');return False
    if STOP: return False
    stop_child()
    try:
        backup()
        git('merge', '--ff-only', new)
    except Exception:
        # Never reset or overwrite local files; restart retained checkout on failure.
        start_child();raise
    log('Installed tested update '+new[:8]+'; restarting background owner')
    # Reload updater itself too. launchd handles unexpected exits.
    os.execv(PY, [PY, '-u', str(BOT/'auto_update.py')])


def shutdown(signum, frame):
    global STOP
    STOP = True


def main():
    global STOP
    os.chdir(BOT)
    lock = open(BOT/'auto-update.lock', 'a')
    try: fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError: return
    # Release lock automatically on exec; replacement process acquires it anew.
    signal.signal(signal.SIGTERM, shutdown);signal.signal(signal.SIGINT, shutdown)
    try:
        start_child(); state('background owner started'); next_check = time.monotonic()+60
        while not STOP:
            if CHILD.poll() is not None:
                stop_child();start_child()
            if time.monotonic() >= next_check:
                try: update()
                except Exception as e: log('Update deferred ('+type(e).__name__+'); retrying later')
                next_check = time.monotonic()+300
            time.sleep(1)
    finally: stop_child()

if __name__ == '__main__': main()
