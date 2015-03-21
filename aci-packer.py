#!/usr/bin/env python
import datetime
import email.utils
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

def abort(msg):
    sys.stderr.write(msg + '\n')
    sys.exit(1)

def build(json_path, aci_path):
    manifest = {
        "acKind": "ImageManifest",
        "acVersion": "0.4.1",
        "labels": [
            { "name": "arch",    "value": "amd64"  },
            { "name": "os",      "value": "linux"  }
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
        'cmd': task_cmd
    }

    try:
        for step in steps:
            if 'type' not in step:
                abort('"type" key not found in build step')
            if step['type'] not in task_map:
                abort('build step type "{0}" is undefined'.format(step['type']))
            task_map[step['type']](workdir, rootfs, **step)

        with open(manifest_path, 'w') as f:
            json.dump(manifest, f)
        subprocess.call(['tar', '--numeric-owner', '-czf', aci_path, 'manifest', 'rootfs'], cwd=workdir)
    finally:
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
        print(target, dst)
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
    mount_dirs = []
    remove_files = [inventory_path]
    try:
        if copy_resolvconf:
            resolvcnf = os.path.join(rootfs, 'etc/resolv.conf')
            os.rename(resolvcnf, resolvcnf + '.bk')
            shutil.copy2('/etc/resolv.conf', resolvcnf)
            remove_files.append(resolvcnf)
        if mount_proc:
            procpath = os.path.join(rootfs, 'proc')
            if subprocess.call(['mount', '-t', 'proc', 'proc', procpath]) != 0:
                abort('failed mount proc')
            mount_dirs.append(procpath)
        if mount_sys:
            syspath = os.path.join(rootfs, 'sys')
            if subprocess.call(['mount', '--rbind', '/sys', syspath]) != 0 or \
               subprocess.call(['mount', '--make-rslave', syspath]) != 0:
                abort('failed mount sys')
            mount_dirs.append(syspath)
        if mount_dev:
            devpath = os.path.join(rootfs, 'dev')
            if subprocess.call(['mount', '--rbind', '/dev', devpath]) != 0 or \
               subprocess.call(['mount', '--make-rslave', devpath]) != 0:
                abort('failed mount dev')
            mount_dirs.append(devpath)
        if make_debian_policy_rc:
            path = os.path.join(rootfs, 'usr/sbin/policy-rc.d')
            with open(path, 'w') as f:
                f.write('#!/bin/sh\nexit 101\n')
            os.chmod(path, 0o755)
            remove_files.append(path)
        
        if subprocess.call(['ansible-playbook', '-i', inventory_path, playbook]) != 0:
            abort('failed ansible execution')
    finally:
        for path in remove_files:
            os.unlink(path)
        for path in mount_dirs:
            try:
                subprocess.check_output(['umount', path], stderr=subprocess.STDOUT)
            except:
                try:
                    subprocess.check_output(['umount', '-l', path], stderr=subprocess.STDOUT)
                except:
                    pass
        if copy_resolvconf and resolvcnf:
            os.rename(resolvcnf + '.bk', resolvcnf)

def task_cmd(workdir, rootfs, path, args=[], copy=True, **kwargs):
    chroot_path = None
    if copy and os.path.isfile(path):
        fd, chroot_path = tempfile.mkstemp(dir=rootfs)
        with os.fdopen(fd, 'wb') as dst, open(path, 'rb') as src:
            shutil.copyfileobj(src, dst)
        os.chmod(chroot_path, 0o755)
        path = chroot_path[len(rootfs):]
    subprocess.call(['chroot', rootfs, path] + args)
    if chroot_path:
        os.unlink(chroot_path)

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

def exec_ldd(path):
    libs = set()
    result = subprocess.check_output(["ldd", path],
                                     stderr=subprocess.STDOUT).splitlines()
    for x in result:
        n = x.split()[0].decode('ascii')
        if n == 'linux-vdso.so.1':
            continue
        if n[0] == '/':
            n = os.path.basename(n)
        libs.add(n)
    return libs

def main():
    if len(sys.argv) != 3:
        print('usage: {0} <json-path> <aci-path>'.format(sys.argv[0]))
        sys.exit(0)

    json_path = sys.argv[1]
    aci_path = sys.argv[2]
    if not os.path.isfile(json_path):
        abort('{0} is not found\n'.format(json_path))
    build(json_path, aci_path)

if __name__ == '__main__':
    main()
