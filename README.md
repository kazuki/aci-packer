# aci-packer

[App Container Specification](https://github.com/appc/spec)に
(たぶん)準拠したACIを作成するためのコマンドラインベースのツールです．
(ACIとかRocketとか，あんまり理解していないので...)

以下の方法を使ったACIの作成に対応しています．

* Ansible
* シェルスクリプト
* バイナリ・共有オブジェクトの依存関係の抽出
* Pythonの最低限の環境作成

## 使い方

manifestファイルに"-aci-packer-build-steps-"というキーを追加して，
その中に実行したいコマンド等を順番に記述していきます．
以下のJSONが記述の例です．("#"以降はコメントです)

```
{
  "name": "example.com/application",
  "labels": [
    {
      "name": "version",
      "value": "1.0.0"
    },
    {
      "name": "arch",
      "value": "amd64"
    },
    {
      "name": "os",
      "value": "linux"
    }
  ],
  ...(other manifest entries)...
  "-aci-packer-build-steps-": [
    {
      "type": "image",          # tarを展開します．pathまたはurlのどちらかを指定する必要があります
      "path": "<rootfs image>", # ローカルファイルを指定 (オプション)
      "url": "<rootfs url>",    # URLを指定 (オプション)
    },
    {
      "type": "setup_chroot",   # chroot環境をセットアップ (ansibleやcreate_python_envの前後では実行しないでね)
      "copy_resolvconf": <boolean>, # /etc/resolv.confをコピーするかどうか(オプション)
      "mount_proc": <boolean>, # /procをマウントするかどうか(オプション)
      "mount_dev": <boolean>,  # /devをマウントするかどうか(オプション)
      "mount_sys": <boolean>,  # /sysをマウントするかどうか(オプション)
      "make_debian_policy_rc": <boolean> # apt-get install後にサービスを起動しないようにする．
                                         # chroot環境だとinstallに失敗する場合は有効にする(オプション)
    },
    {
      "type": "ansible",        # ansible-playbookを実行します
      "playbook": "<playbook path>", # playbookのパス
      # その他，"setup_chroot" と同じオプションが指定できます
    },
    {
      "type": "cmd"  # 任意のコマンド・スクリプトを実行します
      "path": "<executable-file-path>", # コマンドやスクリプトのパス
      "args": [],    # コマンドやスクリプトに渡す引数 (オプション)
      "copy": True   # pathをコピーするかどうか(オプション．デフォルトTrue)
                     # スクリプトの場合はchroot内にコピーするためTrueを指定
                     # chroot内のコマンドを実行する場合はFalseを指定
    },
    {
      "type": "extract",        # 依存関係を抽出し，依存しないものを全て削除します
      "binaries": [             # 依存関係を検索するバイナリを指定
        "<executable path>",
        "<shared object path>", ...
      ],
      "keeps": [                # バイナリ以外で保持しておくファイル・フォルダの一覧を記述(オプション)
        "<keep directory path>",
        "<keep file path>", ...
      ]
    },
    {
      "type": "create_python_env", # pythonの環境を作ります．
                                   # 一番最初のstepであるひつようがあります
      "python_exe": "<python exe path>" # virtualenvの-pオプションと同じ意味です
    },
    {
      "type": "copy_host_files", # ホストのファイルをコピー
      "binaries": [], # コピーするバイナリのリスト
                      # lddを使って依存関係もコピーします
      "files": [      # ホストのファイルをACIの指定パスにコピー
        ['host path', 'aci path']
      ]
    }
  ]
}
```

ACIを作成する場合は，上記のようなmanifestを指定して以下のコマンドを実行します
```
$ ./aci-packer.py test.json output.aci
```

## 実行例

### Hello World (Python)

```
$ cat > hello_world.json <<EOF
{
  "name": "hello-world",
  "labels": [
    { "name": "version", "value": "1.0.0" }
  ],
  "app": {
    "exec": [
      "/usr/bin/python",
      "-c",
      "print('Hello World')"
    ],
    "user": "root",
    "group": "root"
  },
  "-aci-packer-build-steps-": [
    {
      "type": "create_python_env"
    }
  ]
}
EOF
$ sudo python ./aci-packer.py hello_world.json hello_world.aci
$ ls -lh hello_world.aci
-rw-r--r-- 1 root root 28M Mar 22 11:59 hello_world.aci
$ sudo python ./aci-packer.py -C xz hello_world.json hello_world.aci
$ ls -lh hello_world.aci
-rw-r--r-- 1 root root 17M Mar 22 12:00 hello_world.aci
$ sudo rkt run ./hello_world.aci
/etc/localtime is not a symlink, not updating container timezone.
Hello World
Sending SIGTERM to remaining processes...
Sending SIGKILL to remaining processes...
Unmounting file systems.
Unmounting /opt/stage2/sha512-96537d599b3e35bed2b79065e751f224/rootfs/dev/shm.
Unmounting /opt/stage2/sha512-96537d599b3e35bed2b79065e751f224/rootfs/sys.
Unmounting /opt/stage2/sha512-96537d599b3e35bed2b79065e751f224/rootfs/proc.
Unmounting /opt/stage2/sha512-96537d599b3e35bed2b79065e751f224/rootfs/dev/console.
Unmounting /opt/stage2/sha512-96537d599b3e35bed2b79065e751f224/rootfs/dev/tty.
Unmounting /opt/stage2/sha512-96537d599b3e35bed2b79065e751f224/rootfs/dev/urandom.
Unmounting /opt/stage2/sha512-96537d599b3e35bed2b79065e751f224/rootfs/dev/random.
Unmounting /opt/stage2/sha512-96537d599b3e35bed2b79065e751f224/rootfs/dev/full.
Unmounting /opt/stage2/sha512-96537d599b3e35bed2b79065e751f224/rootfs/dev/zero.
Unmounting /opt/stage2/sha512-96537d599b3e35bed2b79065e751f224/rootfs/dev/null.
Unmounting /opt/stage2/sha512-96537d599b3e35bed2b79065e751f224/rootfs.
Unmounting /proc/sys/kernel/random/boot_id.
All filesystems unmounted.
Halting system.
```

### Web Server (nginx, Ubuntu 14.04 LTS)

```
$ cat > nginx.json <<EOF
{
  "name": "nginx",
  "labels": [
    { "name": "version", "value": "1.0.0" }
  ],
  "app": {
    "exec": [
      "/usr/sbin/nginx",
      "-g",
      "daemon off;"
    ],
    "user": "root",
    "group": "root",
    "ports": [
      {
        "name": "http",
        "port": 80,
        "protocol": "tcp"
      }
    ]
  },
  "-aci-packer-build-steps-": [
    {
      "type": "image",
      "url": "http://cloud-images.ubuntu.com/trusty/current/trusty-server-cloudimg-amd64-root.tar.gz"
    },
    {
      "type": "setup_chroot",
      "make_debian_policy_rc": true
    },
    {
      "type": "cmd",
      "copy": false,
      "path": "/usr/bin/apt-get",
      "args": [
        "install",
        "-y",
        "nginx"
      ]
    },
    {
      "type": "cmd",
      "copy": false,
      "path": "/usr/bin/apt-get",
      "args": [
        "clean"
      ]
    }
  ]
}
EOF
$ sudo python ./aci-packer.py -C xz nginx.json nginx.aci
$ ls -lh nginx.aci
-rw-r--r-- 1 root   root   108M Mar 22 12:44 nginx.aci
$ sudo rkt run ./nginx.aci
sudo rkt --debug run ./nginx.aci
2015/03/22 12:52:53 Preparing stage1
2015/03/22 12:52:53 Wrote filesystem to /var/lib/rkt/containers/prepare/f4fd244d-050d-4db1-80c0-1d61f51b16b8
2015/03/22 12:52:53 Loading image sha512-ceb50483638cec8df10f37be5709a7e85162b5252ca701e2af60335848c37e64
2015/03/22 12:52:59 Writing container manifest
2015/03/22 12:52:59 Pivoting to filesystem /var/lib/rkt/containers/run/f4fd244d-050d-4db1-80c0-1d61f51b16b8
2015/03/22 12:52:59 Execing /init
Spawning container rootfs on /var/lib/rkt/containers/run/f4fd244d-050d-4db1-80c0-1d61f51b16b8/stage1/rootfs.
Press ^] three times within 1s to kill container.
/etc/localtime is not a symlink, not updating container timezone.
systemd 215 running in system mode. (-PAM -AUDIT -SELINUX +IMA -SYSVINIT +LIBCRYPTSETUP -GCRYPT -ACL -XZ +SECCOMP -APPARMOR)
Detected virtualization 'systemd-nspawn'.
Detected architecture 'x86-64'.

Welcome to Linux!

Initializing machine ID from container UUID.
[  OK  ] Created slice -.slice.
[  OK  ] Created slice system.slice.
         Starting Graceful exit watcher...
[  OK  ] Started Graceful exit watcher.
[  OK  ] Created slice system-prepare\x2dapp.slice.
         Starting Prepare minimum environment for chrooted applications...
[  OK  ] Reached target Rocket apps target.
[  OK  ] Started Prepare minimum environment for chrooted applications.
         Starting nginx...
[  OK  ] Started nginx.
```

### Web Server (tornado, python minimal)

```
$ wget https://raw.githubusercontent.com/tornadoweb/tornado/master/demos/helloworld/helloworld.py
$ cat > tornado.json <<EOF
{
  "name": "tornado",
  "app": {
    "exec": [
      "/usr/bin/python",
      "/helloworld.py"
    ],
    "user": "root",
    "group": "root",
    "ports": [
      {
        "name": "http",
        "port": 8888,
        "protocol": "tcp"
      }
    ]
  },
  "-aci-packer-build-steps-": [
    {
      "type": "create_python_env"
    },
    {
      "type": "cmd",
      "copy": false,
      "path": "/usr/bin/pip",
      "args": [
        "install",
        "tornado"
      ]
    },
    {
      "type": "copy_host_files",
      "files": [
        ["helloworld.py", "/helloworld.py"]
      ]
    }
  ]
}
EOF
$ sudo python ./aci-packer.py -C xz tornado.json tornado.aci
Collecting tornado
  Downloading tornado-4.1.tar.gz (332kB)
    100% |################################| 335kB 1.4MB/s
Collecting certifi (from tornado)
  Downloading certifi-14.05.14.tar.gz (168kB)
    100% |################################| 172kB 1.8MB/s
    /usr/lib64/python3.3/site-packages/setuptools/dist.py:283: UserWarning: The version specified requires normalization, consider using '14.5.14' instead of '14.05.14'.
      self.metadata.version,
Installing collected packages: certifi, tornado
  Running setup.py install for certifi
    /usr/lib64/python3.3/site-packages/setuptools/dist.py:283: UserWarning: The version specified requires normalization, consider using '14.5.14' instead of '14.05.14'.
      self.metadata.version,
  Running setup.py install for tornado
    building 'tornado.speedups' extension
    x86_64-pc-linux-gnu-gcc -pthread -fPIC -I/usr/include/python3.3 -c tornado/speedups.c -o build/temp.linux-x86_64-3.3/tornado/speedups.o
    command 'x86_64-pc-linux-gnu-gcc' failed with exit status 1
    /pip-build-r5r69e/tornado/setup.py:93: UserWarning:
    ********************************************************************
    WARNING: The tornado.speedups extension module could not
    be compiled. No C extensions are essential for Tornado to run,
    although they do result in significant speed improvements for
    websockets.
    The output above this warning shows how the compilation failed.
    Here are some hints for popular operating systems:
    If you are seeing this message on Linux you probably need to
    install GCC and/or the Python development package for your
    version of Python.
    Debian and Ubuntu users should issue the following command:
        $ sudo apt-get install build-essential python-dev
    RedHat, CentOS, and Fedora users should issue the following command:
        $ sudo yum install gcc python-devel
    If you are seeing this message on OSX please read the documentation
    here:
    http://api.mongodb.org/python/current/installation.html#osx
    ********************************************************************
      "The output above "
Successfully installed certifi-14.5.14 tornado-4.1
$ ls -lh tornado.aci
-rw-r--r-- 1 root   root    18M Mar 22 13:10 tornado.aci
$  sudo rkt --debug run tornado.aci
2015/03/22 13:11:11 Preparing stage1
2015/03/22 13:11:11 Wrote filesystem to /var/lib/rkt/containers/prepare/b5440d86-109d-4699-b53c-e21a57c12e9a
2015/03/22 13:11:11 Loading image sha512-a7e406332387ca6ec028e663da0fec16c3f791838064b4177245c4709204b27d
2015/03/22 13:11:12 Writing container manifest
2015/03/22 13:11:12 Pivoting to filesystem /var/lib/rkt/containers/run/b5440d86-109d-4699-b53c-e21a57c12e9a
2015/03/22 13:11:12 Execing /init
Spawning container rootfs on /var/lib/rkt/containers/run/b5440d86-109d-4699-b53c-e21a57c12e9a/stage1/rootfs.
Press ^] three times within 1s to kill container.
/etc/localtime is not a symlink, not updating container timezone.
systemd 215 running in system mode. (-PAM -AUDIT -SELINUX +IMA -SYSVINIT +LIBCRYPTSETUP -GCRYPT -ACL -XZ +SECCOMP -APPARMOR)
Detected virtualization 'systemd-nspawn'.
Detected architecture 'x86-64'.

Welcome to Linux!

Initializing machine ID from container UUID.
[  OK  ] Created slice -.slice.
[  OK  ] Created slice system.slice.
         Starting Graceful exit watcher...
[  OK  ] Started Graceful exit watcher.
[  OK  ] Created slice system-prepare\x2dapp.slice.
         Starting Prepare minimum environment for chrooted applications...
[  OK  ] Reached target Rocket apps target.
[  OK  ] Started Prepare minimum environment for chrooted applications.
         Starting tornado...
[  OK  ] Started tornado.
[I 150322 04:11:19 web:1825] 200 GET / (::1) 1.05ms
[W 150322 04:11:19 web:1825] 404 GET /favicon.ico (::1) 0.66ms
[W 150322 04:11:19 web:1825] 404 GET /favicon.ico (::1) 0.62ms
```

### BusyBoxとBash

```
$ cat > bash.json <<EOF
{
  "name": "bash",
  "app": {
    "exec": [
      "/bin/bash"
    ],
    "user": "root",
    "group": "root"
  },
  "-aci-packer-build-steps-": [
    {
      "type": "copy_host_files",
      "binaries": [
        "/bin/bash",
        "/bin/busybox"
      ]
    },
    {
      "type": "cmd",
      "copy": false,
      "path": "/bin/busybox",
      "args": [
        "--install",
        "-s",
        "/bin"
      ]
    }
  ]
}
EOF
$  sudo python ./aci-packer.py -C xz bash.json bash.aci
$  ls -lh bash.aci
-rw-r--r-- 1 root root 1.7M Mar 22 18:44 bash.aci
$  sudo rkt run --interactive bash.aci
/etc/localtime is not a symlink, not updating container timezone.
bash-4.2# ls -l /lib64/
total 2448
-rwxr-xr-x    1 0        0           140624 Mar  5 14:28 ld-linux-x86-64.so.2
-rwxr-xr-x    1 0        0          1705232 Mar  5 14:28 libc.so.6
-rwxr-xr-x    1 0        0            14520 Mar  5 14:28 libdl.so.2
-rwxr-xr-x    1 0        0           353952 Dec 17 15:31 libncurses.so.5
-r-xr-xr-x    1 0        0           279888 Dec 17 15:31 libreadline.so.6
```
