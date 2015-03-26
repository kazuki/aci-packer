import argparse
import email.utils
import os
import os.path
import json
import shutil
import subprocess
import tempfile
import time

try:
    # python3
    from urllib.request import urlopen
    from urllib.request import Request
except:
    # python2
    from urllib2 import urlopen
    from urllib2 import Request
    FileNotFoundError = IOError

MAGIC_KEY = '-aci-packer-build-steps-'
COMPRESSION_TYPE = {
    'none': '',
    'xz': 'J',
    'gzip': 'z',
    'bzip2': 'j'
}

class Builder(object):
    def __init__(self):
        self.seq_backup = 0
        self.mounts = set()
        self.reverts = {}
        self.default_manifest = {
            'acKind': 'ImageManifest',
            'acVersion': '0.4.1',
            'labels': [
                {'name': 'arch', 'value': 'amd64'},
                {'name': 'os', 'value': 'linux'}
            ]
        }

    def build_aci(self, json_path, aci_path, compression, debug):
        self.debug = debug
        if compression not in COMPRESSION_TYPE:
            raise ValueError('"{0}" is not supported compression type'
                             .format(compression))
        with open(json_path) as json_file:
            manifest = json.load(json_file)
        if MAGIC_KEY not in manifest:
            raise ValueError('"{0}" not found in json'.format(MAGIC_KEY))
        steps = manifest[MAGIC_KEY]
        manifest = self._merge_manifest(manifest)

        if not os.path.isabs(aci_path):
            aci_path = os.path.abspath(aci_path)
        self.workdir = tempfile.mkdtemp()
        self.rootfs = os.path.join(self.workdir, 'rootfs')
        os.mkdir(self.rootfs, 0o755)

        step_map = dict([(name[5:], self.__getattribute__(name))
                         for name in dir(self) if name.startswith('step_')])
        try:
            idx = 1
            for step in steps:
                if 'step' not in step or step['step'] not in step_map:
                    raise ValueError('"step" key not found in build step '
                                     'or unknown step type')
                if 'name' in step:
                    name = step['name']
                else:
                    name = 'step={0}'.format(step['step'])
                print('{0}: {1}'.format(idx, name))
                step_map[step['step']](**step)
                idx += 1
            print('cleanup')
            self._cleanup()
            print('writing manifest')
            with open(os.path.join(self.workdir, 'manifest'), 'w') as f:
                json.dump(manifest, f)
            print('compressing')
            self._subprocess_call(['tar', '--numeric-owner', '-c{0}f'
                                   .format(COMPRESSION_TYPE[compression]),
                                   aci_path, 'manifest', 'rootfs'],
                                  cwd=self.workdir)
            print('done')
        finally:
            self._cleanup()
            shutil.rmtree(self.workdir)

    def step_image(self, url=None, path=None, **kwargs):
        if (url and path) or (not url and not path):
            raise ValueError('"image" step required url or path parameter')
        if url:
            path = os.path.basename(url)
            self._fetch_url(url, path)
        elif path:
            if not os.path.isfile(path):
                raise FileNotFoundError('{0} is not found'.format(path))
        if self._subprocess_call(['tar', 'xf', path, '-C', self.rootfs]) != 0:
            raise Exception('tar extraction error')

    def step_setup_chroot(self, copy_resolvconf=True,
                          copy_hosts=True,
                          mount_proc=True,
                          mount_dev=True,
                          mount_sys=True,
                          make_debian_policy_rc=False,
                          **kwargs):
        def copy(src, dst, dst_bk):
            if not os.path.exists(os.path.dirname(dst)):
                os.makedirs(os.path.dirname(dst))
            if os.path.exists(dst) or os.path.islink(dst):
                os.rename(dst, dst_bk)
                shutil.copy2(src, dst)
                self._add_revert_entry(dst, dst_bk)
            else:
                shutil.copy2(src, dst)
                self._add_remove_entry(dst)
        def mount(mountpoint, bindpoint=None, isproc=False):
            if mountpoint in self.mounts:
                return
            if not os.path.exists(mountpoint):
                os.makedirs(mountpoint)
            if bindpoint:
                cmd = ['mount', '--rbind', bindpoint, mountpoint]
            elif isproc:
                cmd = ['mount', '-t', 'proc', 'proc', mountpoint]
            if self._subprocess_call(cmd) != 0:
                raise Exception('mount failed: {0}'.format(cmd))
            self._add_mount_entry(mountpoint)
            if bindpoint:
                self._subprocess_call(['mount', '--make-rslave', mountpoint])

        if copy_resolvconf:
            dst = os.path.join(self.rootfs, 'etc/resolv.conf')
            copy('/etc/resolv.conf',
                 dst, dst + self._backup_suffix())
        if copy_hosts:
            dst = os.path.join(self.rootfs, 'etc/hosts')
            copy('/etc/hosts',
                 dst, dst + self._backup_suffix())
        if mount_proc:
            mount(os.path.join(self.rootfs, 'proc'), isproc=True)
        if mount_dev:
            mount(os.path.join(self.rootfs, 'dev'), bindpoint='/dev')
        if mount_sys:
            mount(os.path.join(self.rootfs, 'sys'), bindpoint='/sys')
        if make_debian_policy_rc:
            if not os.path.exists(os.path.join(self.rootfs, 'usr/sbin')):
                os.makedirs(os.path.join(self.rootfs, 'usr/sbin'))
            path = os.path.join(self.rootfs, 'usr/sbin/policy-rc.d')
            with open(path, 'w') as f:
                f.write('#!/bin/sh\nexit 101\n')
            os.chmod(path, 0o755)
            self._add_remove_entry(path)

    def step_ansible(self, playbook, **kwargs):
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            inventory_path = f.name
            f.write('[aci]\n{0}  ansible_connection=chroot\n'.format(self.rootfs))
        self._add_remove_entry(inventory_path)
        if self._subprocess_call(['ansible-playbook', '-i', inventory_path, playbook]) != 0:
            raise Exception('failed ansible execution')

    def step_cmd(self, path, args=[], **kwargs):
        if self._subprocess_call(['chroot', self.rootfs, path] + args) != 0:
            raise Exception('failed cmd execution')

    def step_shell(self, cmd, **kwargs):
        env = {'ROOTFS': self.rootfs}
        if self._subprocess_call(cmd, env=env, shell=True) != 0:
            raise Exception('failed cmd execution')

    def step_copy(self, binaries=[], find_executable=[], files=[], excludes=[], **kwargs):
        def is_exclude(path):
            for prefix in excludes:
                if path.startswith(prefix):
                    return True
            return False
        libs = set(binaries)
        for path in binaries:
            libs |= self._ldd(path, return_abspath=True)
        for path in find_executable:
            for dirpath, dirnames, filenames in os.walk(path):
                if is_exclude(dirpath):
                    continue
                for name in filenames:
                    path = os.path.join(dirpath, name)
                    stat = os.stat(path)
                    if (stat.st_mode & 0o111) != 0:
                        libs.add(path)
                        libs |= self._ldd(path, return_abspath=True)
        if len(binaries) < len(libs):
            libs |= set(self._get_glibc_dylibs())
        for path in libs:
            files.append([path, path])
        for src, dst in files:
            if is_exclude(src):
                continue
            dst = os.path.abspath(self.rootfs + dst)
            dstd = os.path.dirname(dst)
            if not os.path.islink(dstd) and not os.path.exists(dstd):
                os.makedirs(dstd)
            if os.path.isdir(src):
                self._copytree_overwrite(src, dst, exclude_func=is_exclude)
            else:
                shutil.copy2(src, dst)

    def step_symlink(self, links=[], **kwargs):
        for target, linkname in links:
            linkname = os.path.abspath(self.rootfs + '/' + linkname)
            dirname = os.path.dirname(linkname)
            if not os.path.exists(dirname):
                os.makedirs(dirname)
            else:
                self._unlink_if_exists(linkname)
            os.symlink(target, linkname)

    def step_write(self, path, contents, **kwargs):
        path = os.path.abspath(self.rootfs + '/./' + path)
        with open(path, 'w') as f:
            f.write(contents)

    def step_delete(self, files, **kwargs):
        for name in files:
            path = os.path.abspath(self.rootfs + '/./' + name)
            if os.path.isfile(path):
                os.unlink(path)
            elif os.path.isdir(path):
                shutil.rmtree(path)

    def step_mkdir(self, dirs, **kwargs):
        if isinstance(dirs, str):
            dirs = [dirs]
        for path in dirs:
            path = os.path.abspath(self.rootfs + '/./' + path)
            if not os.path.exists(path):
                os.makedirs(path)
            
    def _fetch_url(self, url, path):
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

    def _ldd(self, path, return_abspath = False):
        libs = set()
        try:
            result = subprocess.check_output(['ldd', path],
                                             stderr=subprocess.STDOUT)
            result = result.decode('ascii').splitlines()
        except:
            return libs
        for x in result:
            items = x.split()
            n = items[0]
            if n == 'linux-vdso.so.1':
                continue
            if return_abspath:
                if len(items) == 4 and items[1] == '=>' and items[2][0] == '/':
                    libs.add(items[2])
                elif len(items) == 2 and n[0] == '/':
                    libs.add(n)
            else:
                if n[0] == '/':
                    n = os.path.basename(n)
                libs.add(n)
        return libs

    def _get_glibc_dylibs(self):
        targets = [
            'libnss_compat.so',
            'libnss_dns.so',
            'libnss_files.so',
            'libresolv.so'
        ]
        def is_target(name):
            for t in targets:
                if name.startswith(t):
                    return True
            return False
        libs = []
        cached = subprocess.check_output(['/sbin/ldconfig', '-p'])
        for lib in cached.decode('ascii').splitlines():
            lib = lib.strip()
            if '/lib32/' in lib or not '=>' in lib: continue
            if not is_target(lib): continue
            lib = lib[lib.index('=>')+2:].strip()
            if not os.path.exists(lib): continue
            libs.append(lib)
        return libs

    def _cleanup(self):
        mounts = set(self.mounts)
        for path in mounts:
            try:
                subprocess.check_output(['umount', path], stderr=subprocess.STDOUT)
            except:
                subprocess.check_output(['umount', '-l', path], stderr=subprocess.STDOUT)
            self.mounts.remove(path)
        reverts = dict(self.reverts)
        for path, backup_path in reverts.items():
            if os.path.exists(path):
                os.unlink(path)
            if backup_path:
                os.rename(backup_path, path)
            del self.reverts[path]

    def _merge_manifest(self, manifest):
        if MAGIC_KEY in manifest:
            del manifest[MAGIC_KEY]
        if 'labels' in manifest and 'labels' in self.default_manifest:
            labels = dict([(x['name'], x['value'])
                           for x in self.default_manifest['labels']])
            labels.update(dict([(x['name'], x['value'])
                                for x in manifest['labels']]))
            manifest['labels'] = [{'name': name, 'value': value}
                                  for name, value in labels.items()]
        new_manifest = dict(self.default_manifest)
        new_manifest.update(manifest)
        return new_manifest

    def _add_mount_entry(self, mount_point):
        self.mounts.add(mount_point)

    def _add_revert_entry(self, path, backup_path):
        if path in self.reverts:
            self._unlink_if_exists(backup_path)
            return
        self.reverts[path] = backup_path

    def _add_remove_entry(self, path, force=False):
        if path in self.reverts:
            if not force:
                return
            self._unlink_if_exists(self.reverts[path])
        self.reverts[path] = None

    def _unlink_if_exists(self, path):
        if path and os.path.isfile(path):
            os.unlink(path)

    def _backup_suffix(self):
        seq = self.seq_backup
        self.seq_backup += 1
        return '.bk-{0}'.format(seq)

    def _copytree_overwrite(self, src, dst, exclude_func=None):
        if os.path.isfile(src):
            self._unlink_if_exists(dst)
            shutil.copy2(src, dst)
            return
        if not os.path.exists(dst):
            os.makedirs(dst)
        for dirpath, dirnames, filenames in os.walk(src):
            if exclude_func and exclude_func(dirpath):
                continue
            dirpath2 = os.path.abspath(dst + '/' + dirpath[len(src):])
            if not os.path.exists(dirpath2):
                os.mkdir(dirpath2)
                shutil.copystat(dirpath, dirpath2)
            for name in filenames:
                if exclude_func:
                    path = os.path.join(dirpath, name)
                    if exclude_func(path):
                        continue
                path = os.path.join(dirpath2, name)
                self._unlink_if_exists(path)
                shutil.copy2(os.path.join(dirpath, name), path)

    def _subprocess_call(self, args, **kwargs):
        if self.debug:
            return subprocess.call(args, **kwargs)
        try:
            subprocess.check_output(args, stderr=subprocess.STDOUT, **kwargs)
            return 0
        except:
            return 1

def main():
    parser = argparse.ArgumentParser(description='App container image builder')
    parser.add_argument('--compression', '-C', action='store', default='gzip',
                        choices=('gzip', 'xz', 'none', 'bzip2'),
                        help='use compression algorithm (default: gzip)')
    parser.add_argument('--debug', action='store_true',
                        help='enable debug mode')
    parser.add_argument('json_path', action='store', type=str,
                        help='manifest(json) path')
    parser.add_argument('aci_path', action='store', type=str,
                        help='output aci path')
    args = parser.parse_args()
    if not os.path.isfile(args.json_path):
        raise FileNotFoundError('{0} is not found\n'.format(args.json_path))

    builder = Builder()
    builder.build_aci(args.json_path, args.aci_path,
                      args.compression, args.debug)

if __name__ == '__main__':
    main()
