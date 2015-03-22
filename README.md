# aci-packer

[App Container Specification](https://github.com/appc/spec)に
(たぶん)準拠したACIを作成するためのコマンドラインベースのツールです．
(ACIとかRocketとか，あんまり理解していないので...)

以下の方法を使ったACIの作成に対応しています．

* Ansible
* シェルスクリプト
* バイナリ・共有オブジェクトの依存関係の抽出
* Pythonの最低限の環境作成


This is a command-line tool to build ACI based on
[App Container Specification](https://github.com/appc/spec).

This CLI support to create ACI using the following methods.

* Ansible
* Shell script
* Extract dependencies from binary and shared object
* Create minimum Python environment

## 使い方 / Usage

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
