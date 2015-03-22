#!/usr/bin/env python
import argparse
import datetime
import email.utils
import glob
import json
import os.path
import shutil
import subprocess
import sys
import time
import tempfile
try:
    from urllib.request import urlopen
    from urllib.request import Request
except:
    from urllib2 import urlopen
    from urllib2 import Request

MAGIC_KEY = '-aci-packer-build-steps-'

_mount_dirs = []
_backup_files = []

def abort(msg):
    sys.stderr.write(msg + '\n')
    sys.exit(1)

def build(json_path, aci_path, compression):
    manifest = {
        "acKind": "ImageManifest",
        "acVersion": "0.4.1",
        "labels": [
            { "name": "arch", "value": "amd64" },
            { "name": "os",   "value": "linux" }
        ],
    }
    with open(json_path) as f:
        user_manifest = json.load(f)
    if MAGIC_KEY not in user_manifest:
        abort('"{0}" not found in json'.format(MAGIC_KEY))
    steps = user_manifest[MAGIC_KEY]
    del user_manifest[MAGIC_KEY]
    manifest.update(user_manifest)

    if not os.path.isabs(aci_path):
        aci_path = os.path.abspath(aci_path)
    workdir = tempfile.mkdtemp()
    manifest_path = os.path.join(workdir, 'manifest')
    rootfs  = os.path.join(workdir, 'rootfs')
    os.mkdir(rootfs, 0o755)

    task_map = {
        'image': task_image,
        'extract': task_extract,
        'ansible': task_ansible,
        'cmd': task_cmd,
        "create_python_env": task_create_python_env,
        "copy_host_files": task_copy_host_files
    }

    try:
        for step in steps:
            if 'type' not in step:
                abort('"type" key not found in build step')
            if step['type'] not in task_map:
                abort('build step type "{0}" is undefined'.format(step['type']))
            task_map[step['type']](workdir, rootfs, **step)
        cleanup_chroot_env()
        with open(manifest_path, 'w') as f:
            json.dump(manifest, f)

        if compression == 'xz':
            compression = 'J'
        else:
            compression = 'z'
        subprocess.call(['tar', '--numeric-owner', '-c{0}f'.format(compression),
                         aci_path, 'manifest', 'rootfs'], cwd=workdir)
    finally:
        cleanup_chroot_env()
        shutil.rmtree(workdir)

def task_image(workdir, rootfs, url = None, path = None, prefix = None, **kwargs):
    if url:
        path = os.path.basename(url)
        fetch_url(url, path)
    elif path:
        if not os.path.isfile(path):
            abort('{0} is not found'.format(path))
    else:
        abort('"image" step required url or path parameter')
    subprocess.call(['tar', 'xf', path, '-C', rootfs])

def task_extract(workdir, rootfs, binaries=[], keeps=[], **kwargs):
    def rename_link(src, oldprefix, newprefix):
        target = os.readlink(src)
        if os.path.isabs(target):
            target = os.path.abspath(oldprefix + target)
        else:
            target = os.path.abspath(os.path.join(os.path.dirname(src), target))
        if not os.path.exists(target):
            return
        if os.path.islink(target):
            rename_link(target, oldprefix, newprefix)
        dst = os.path.abspath(newprefix + '/' + target[len(oldprefix):])
        os.renames(target, dst)
        
    libs = set()
    keeps = set(keeps) | set(binaries)
    keeps = set([os.path.abspath(os.path.join(rootfs, './' + x)) for x in keeps])
    for b in binaries:
        chroot_path = os.path.abspath(os.path.join(rootfs, './' + b))
        libs |= exec_ldd(chroot_path)
        while os.path.islink(chroot_path):
            new_path = os.readlink(chroot_path)
            if os.path.isabs(new_path):
                chroot_path = os.path.abspath(rootfs + new_path)
            else:
                chroot_path = os.path.abspath(
                    os.path.join(os.path.dirname(chroot_path),
                                 new_path))
            if os.path.isfile(chroot_path):
                keeps.add(chroot_path)

    new_rootfs = os.path.join(workdir, 'rootfs2')
    if os.path.isdir(new_rootfs): shutil.rmtree(new_rootfs)
    os.mkdir(new_rootfs)
    for k in keeps:
        dst = os.path.abspath(new_rootfs + '/' + k[len(rootfs):])
        os.renames(k, dst)
    for dirpath, dirnames, filenames in os.walk(rootfs):
        new_dirpath = None
        for n in filenames:
            if n in libs:
                if not new_dirpath:
                    new_dirpath = os.path.abspath(
                        new_rootfs + '/' + dirpath[len(rootfs):])
                if os.path.islink(os.path.join(dirpath, n)):
                    rename_link(os.path.join(dirpath, n), rootfs, new_rootfs)
                os.renames(os.path.join(dirpath, n),
                           os.path.join(new_dirpath, n))

    shutil.rmtree(rootfs)
    os.rename(new_rootfs, rootfs)
    subprocess.call(['ls', '-lR', rootfs])

def task_ansible(workdir, rootfs, playbook = None, copy_resolvconf = False,
                 mount_proc = False, mount_sys = False, mount_dev = False,
                 make_debian_policy_rc = False, **kwargs):
    with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
        inventory_path = f.name
        f.write('[aci]\n{0}  ansible_connection=chroot\n'.format(rootfs))
    _backup_files.append((inventory_path, None))
    setup_chroot_env(rootfs, copy_resolvconf=copy_resolvconf, mount_proc=mount_proc,
                     mount_sys=mount_sys, mount_dev=mount_dev,
                     make_debian_policy_rc=make_debian_policy_rc)
    if subprocess.call(['ansible-playbook', '-i', inventory_path, playbook]) != 0:
        abort('failed ansible execution')

def task_cmd(workdir, rootfs, path, args=[], copy=True, **kwargs):
    chroot_path = None
    if copy and os.path.isfile(path):
        fd, chroot_path = tempfile.mkstemp(dir=rootfs)
        with os.fdopen(fd, 'wb') as dst, open(path, 'rb') as src:
            shutil.copyfileobj(src, dst)
        os.chmod(chroot_path, 0o755)
        path = chroot_path[len(rootfs):]
    if subprocess.call(['chroot', rootfs, path] + args) != 0:
        abort('failed cmd execution')
    if chroot_path:
        os.unlink(chroot_path)

def task_create_python_env(workdir, rootfs, python_exe = None, **kwargs):
    venv_dir = os.path.join(workdir, 'pyvenv')
    cmd = ['virtualenv']
    if python_exe:
        cmd += ['-p', python_exe]
    cmd += [venv_dir]
    subprocess.check_output(cmd, stderr=subprocess.STDOUT)
    prefix = os.path.join(rootfs, 'usr')
    os.makedirs(prefix)
    for dirpath, dirnames, filenames in os.walk(venv_dir):
        new_dirpath = os.path.abspath(os.path.join(prefix, './' + dirpath[len(venv_dir):]))
        for n in dirnames:
            old_path = os.path.join(dirpath, n)
            new_path = os.path.join(new_dirpath, n)
            if os.path.islink(old_path):
                linkpath = os.readlink(old_path)
                if os.path.isabs(linkpath):
                    shutil.copytree(linkpath, new_path)
                else:
                    os.symlink(linkpath, new_path)
            else:
                os.mkdir(new_path)
        for n in filenames:
            old_path = os.path.join(dirpath, n)
            new_path = os.path.join(new_dirpath, n)
            if os.path.islink(old_path) and not os.path.isabs(os.readlink(old_path)):
                os.symlink(os.readlink(old_path), new_path)
            else:
                shutil.copyfile(old_path, new_path)
            shutil.copystat(old_path, new_path)
    shutil.rmtree(venv_dir)

    for path in glob.glob(os.path.join(prefix, 'bin/activate*')):
        os.unlink(path)
    pip_path = os.path.join(prefix, 'bin/pip')
    for path in glob.glob(pip_path + '*'):
        if not path.endswith('/pip'):
            os.unlink(path)
            os.symlink('pip', path)
    pip_src = open(pip_path).read().splitlines()
    pip_src[0] = '#!/usr' + pip_src[0][pip_src[0].rindex('/bin/'):]
    with open(pip_path, 'w') as f:
        f.write('\n'.join(pip_src))

    # workaround
    py_ver = os.path.basename(glob.glob(os.path.join(prefix, 'lib/python*'))[0])
    py_home = os.path.join('/usr/lib', py_ver)
    new_py_home = os.path.join(prefix, 'lib/' + py_ver)
    os.unlink(os.path.join(new_py_home, 'site.py'))
    if os.path.exists(os.path.join(new_py_home, '__pycache__')):
        shutil.rmtree(os.path.join(new_py_home, '__pycache__'))
    shutil.rmtree(os.path.join(new_py_home, 'distutils'))
    for name in os.listdir(py_home):
        old_path = os.path.join(py_home, name)
        new_path = os.path.join(new_py_home, name)
        if os.path.exists(new_path): continue
        if os.path.isdir(old_path):
            if '-packages' in name: continue
            shutil.copytree(old_path, new_path)
        else:
            shutil.copy2(old_path, new_path)
    if os.path.exists(os.path.join(new_py_home, 'test')):
        shutil.rmtree(os.path.join(new_py_home, 'test'))

    libs = subprocess.check_output(['find', prefix, '-name', '*.so*', '-and', '-executable']).decode('ascii').splitlines()
    libs.append('/usr/bin/env')
    libs.append(os.path.join(prefix, 'bin/python'))
    for lib in subprocess.check_output(['/sbin/ldconfig', '-p']).decode('ascii').splitlines():
        if 'libnss_' not in lib: continue
        if 'compat' not in lib and 'dns' not in lib and 'file' not in lib: continue
        if '/lib32/' in lib: continue
        if not '=>' in lib: continue
        lib = lib[lib.index('=>')+2:].strip()
        if not os.path.exists(lib): continue
        libs.append(lib)
    task_copy_host_files(workdir, rootfs, binaries=libs)

    if not os.path.exists(os.path.join(rootfs, 'etc')):
        os.makedirs(os.path.join(rootfs, 'etc'))
    with open(os.path.join(rootfs, 'etc/passwd'), 'w') as f:
        f.write('root:x:0:0:root:/:/bin/sh\n')
    with open(os.path.join(rootfs, 'etc/group'), 'w') as f:
        f.write('root:x:0:root\n')
    setup_chroot_env(rootfs)

def task_copy_host_files(workdir, rootfs, binaries=[], files=[], **kwargs):
    global _backup_files
    libs = set()
    for path in binaries:
        if not path.startswith(rootfs):
            libs.add(path)
        libs |= exec_ldd(path, return_abspath=True)
    for path in libs:
        dst = os.path.abspath(rootfs + path)
        dstd = os.path.dirname(dst)
        if not os.path.exists(dstd):
            os.makedirs(dstd)
        shutil.copyfile(path, dst)
        shutil.copystat(path, dst)

    remove_backup_idx = set()
    for (path, dst) in files:
        dst = os.path.abspath(rootfs + dst)
        if os.path.isdir(path):
            shutil.copytree(path, dst)
        else:
            shutil.copy2(path, dst)
        for i in range(len(_backup_files)):
            p1,p2 = _backup_files[i]
            if p1 == dst:
                remove_backup_idx.add(i)
                break
    if len(remove_backup_idx) > 0:
        backup_files = []
        for i in range(len(_backup_files)):
            if i in remove_backup_idx: continue
            backup_files.append(_backup_files[i])
        _backup_files = backup_files

def fetch_url(url, path):
    if os.path.isfile(path):
        try:
            req = Request(url, method='HEAD') # py3 only
        except:
            req = Request(url)
            req.get_method = lambda : 'HEAD'
        header = urlopen(req).info()
        stat = os.stat(path)
        changed = False
        if 'content-length' in header:
            changed |= (stat.st_size != int(header['content-length']))
        if 'last-modified' in header:
            remote_gm_time = time.mktime(
                email.utils.parsedate(header['last-modified']))
            local_gm_time = stat.st_mtime + time.timezone
            changed |= (local_gm_time < remote_gm_time)
        if not changed:
            return
        os.unlink(path)
    res = urlopen(Request(url))
    with open(path, 'wb') as f:
        shutil.copyfileobj(res, f)

def exec_ldd(path, return_abspath = False):
    libs = set()
    try:
        result = subprocess.check_output(["ldd", path],
                                         stderr=subprocess.STDOUT).splitlines()
    except:
        return libs
    for x in result:
        items = x.split()
        n = items[0].decode('ascii')
        if n == 'linux-vdso.so.1':
            continue
        if return_abspath:
            if len(items) == 4 and items[1] == b'=>':
                libs.add(items[2].decode('ascii'))
            elif len(items) == 2 and n[0] == '/':
                libs.add(n)
        else:
            if n[0] == '/':
                n = os.path.basename(n)
            libs.add(n)
    return libs

def setup_chroot_env(rootfs,
                     copy_resolvconf = True,
                     copy_hosts = True,
                     mount_proc = True,
                     mount_sys = True,
                     mount_dev = True,
                     make_debian_policy_rc = False):
    if copy_resolvconf:
        resolvcnf = os.path.join(rootfs, 'etc/resolv.conf')
        if os.path.exists(resolvcnf):
            os.rename(resolvcnf, resolvcnf + '.bk')
            shutil.copy2('/etc/resolv.conf', resolvcnf)
            _backup_files.append((resolvcnf + '.bk', resolvcnf))
        else:
            shutil.copy2('/etc/resolv.conf', resolvcnf)
            _backup_files.append((resolvcnf, None))
    if copy_hosts:
        hosts = os.path.join(rootfs, 'etc/hosts')
        if os.path.exists(hosts):
            os.rename(hosts, hosts + '.bk')
            shutil.copy2('/etc/hosts', hosts)
            _backup_files.append((hosts + '.bk', hosts))
        else:
            shutil.copy2('/etc/hosts', hosts)
            _backup_files.append((hosts, None))
    if mount_proc:
        procpath = os.path.join(rootfs, 'proc')
        if not os.path.exists(procpath):
            os.makedirs(procpath)
        if subprocess.call(['mount', '-t', 'proc', 'proc', procpath]) != 0:
            abort('failed mount proc')
        _mount_dirs.append(procpath)
    if mount_sys:
        syspath = os.path.join(rootfs, 'sys')
        if not os.path.exists(syspath):
            os.makedirs(syspath)
        if subprocess.call(['mount', '--rbind', '/sys', syspath]) != 0 or \
           subprocess.call(['mount', '--make-rslave', syspath]) != 0:
            abort('failed mount sys')
        _mount_dirs.append(syspath)
    if mount_dev:
        devpath = os.path.join(rootfs, 'dev')
        if not os.path.exists(devpath):
            os.makedirs(devpath)
        if subprocess.call(['mount', '--rbind', '/dev', devpath]) != 0 or \
           subprocess.call(['mount', '--make-rslave', devpath]) != 0:
            abort('failed mount dev')
        _mount_dirs.append(devpath)
    if make_debian_policy_rc:
        if not os.path.exists(os.path.join(rootfs, 'usr/sbin')):
            os.makedirs(os.path.join(rootfs, 'usr/sbin'))
        path = os.path.join(rootfs, 'usr/sbin/policy-rc.d')
        with open(path, 'w') as f:
            f.write('#!/bin/sh\nexit 101\n')
        os.chmod(path, 0o755)
        _backup_files.append((path, None))

def cleanup_chroot_env():
    for path in _mount_dirs:
        try:
            subprocess.check_output(['umount', path], stderr=subprocess.STDOUT)
        except:
            try:
                subprocess.check_output(['umount', '-l', path], stderr=subprocess.STDOUT)
            except:
                pass
    for src, dst in _backup_files:
        if dst:
            if os.path.exists(dst):
                os.unlink(dst)
            os.rename(src, dst)
        else:
            os.unlink(src)
    del _mount_dirs[:]
    del _backup_files[:]

def main():
    parser = argparse.ArgumentParser(description='App container image builder')
    parser.add_argument('--compression', '-C', action='store', default='gzip',
                        choices=('gzip', 'xz'),
                        help='use compression algorithm (default: gzip)')
    parser.add_argument('json_path', action='store', type=str,
                        help='manifest(json) path')
    parser.add_argument('aci_path', action='store', type=str,
                        help='output aci path')
    args = parser.parse_args()
    if not os.path.isfile(args.json_path):
        abort('{0} is not found\n'.format(args.json_path))
    build(args.json_path, args.aci_path, args.compression)

if __name__ == '__main__':
    main()
