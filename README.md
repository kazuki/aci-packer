# acipacker

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
      "step": "image",          # tarを展開します．pathまたはurlのどちらかを指定する必要があります
      "path": "<rootfs image>", # ローカルファイルを指定 (オプション)
      "url": "<rootfs url>",    # URLを指定 (オプション)
    },
    {
      "step": "setup_chroot",  # chroot環境をセットアップ
      "copy_resolvconf": <boolean>, # /etc/resolv.confをコピーするかどうか(オプション)
      "copy_hosts": <boolean>, # /etc/hostsをコピーするかどうか(オプション)
      "mount_proc": <boolean>, # /procをマウントするかどうか(オプション)
      "mount_dev": <boolean>,  # /devをマウントするかどうか(オプション)
      "mount_sys": <boolean>,  # /sysをマウントするかどうか(オプション)
      "make_debian_policy_rc": <boolean> # apt-get install後にサービスを起動しないようにする．
                                         # chroot環境だとinstallに失敗する場合は有効にする(オプション)
    },
    {
      "step": "ansible",            # ansible-playbookを実行します
      "playbook": "<playbook path>" # playbookのパス
    },
    {
      "step": "cmd"  # rootfsでchrootし，任意のコマンドを実行します
      "path": "<executable-file-path>", # コマンドやスクリプトのパス
      "args": [],    # コマンドやスクリプトに渡す引数 (オプション)
    },
    {
      "step": "shell" # ROOTFS環境変数にコンテナのrootfsのパスを設定してシェル経由でコマンドを実行します
      "cmd": "<executable-file-path>", # コマンド(パイプ等も利用可能)
    },
    {
      "step": "copy", # ホストのファイルをコピー
      "binaries": [], # コピーするバイナリのリスト
                      # lddを使って依存関係もコピーします
      "find_executable": [], # 指定したパスに含まれるすべての実行可能ファイルを検索し
                             # "binaries"に指定した場合と同じ処理を行います
      "files": [      # ホストのファイル/ディレクトリをACIの指定パスにコピー
        ['host path', 'aci path']
      ],
      "excludes": [   # 除外するパスのリスト
        "/exclude-prefix"
      ]
    },
    {
      "step": "symlink", # targetを指すシンボリックリンクをsymlink-pathに作成します
      "links": [
        ["target", "symlink-path"]
      ]
    },
    {
      "step": "write", # テキストファイルを書き出します
      "path": "<output file path>",
      "contents": "1st-line\n2nd-line\n"
    },
    {
      "step": "delete", # ファイル・ディレクトリを削除します
      "files": [
        "/delete-file-path"
      ]
    }
  ]
}
```

ACIを作成する場合は，上記のようなmanifestを指定して以下のコマンドを実行します
```
$ python ./acipacker.py test.json output.aci
```

## 実行例

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
      "step": "image",
      "url": "http://cloud-images.ubuntu.com/trusty/current/trusty-server-cloudimg-amd64-root.tar.gz"
    },
    {
      "step": "setup_chroot",
      "make_debian_policy_rc": true
    },
    {
      "step": "cmd",
      "path": "/usr/bin/apt-get",
      "args": [
        "install",
        "-y",
        "nginx"
      ]
    },
    {
      "step": "cmd",
      "path": "/usr/bin/apt-get",
      "args": [
        "clean"
      ]
    }
  ]
}
EOF
$ sudo python ./acipacker.py -C xz nginx.json nginx.aci
1: step=image
2: step=setup_chroot
3: step=cmd
Reading package lists... Done
Building dependency tree
Reading state information... Done
The following package was automatically installed and is no longer required:
  os-prober
Use 'apt-get autoremove' to remove it.
The following extra packages will be installed:
  fontconfig-config fonts-dejavu-core libfontconfig1 libgd3 libjbig0
  libjpeg-turbo8 libjpeg8 libtiff5 libvpx1 libxpm4 libxslt1.1 nginx-common
  nginx-core
(中略)
4: step=cmd
cleanup
writing manifest
compressing
done
$ ls -lh nginx.aci
-rw-r--r-- 1 root   root   109M Mar 25 22:21 nginx.aci
$ sudo rkt --debug run ./nginx.aci
2015/03/25 22:28:04 Preparing stage1
2015/03/25 22:28:04 Wrote filesystem to /var/lib/rkt/containers/prepare/65c9dfc4-a3b7-4295-b87c-d0da0d90445c
2015/03/25 22:28:04 Loading image sha512-f821d026fb3d5833ac348bf3661b194bc949710392b9cea834975f10bcd6f62a
2015/03/25 22:28:09 Writing container manifest
2015/03/25 22:28:09 Pivoting to filesystem /var/lib/rkt/containers/run/65c9dfc4-a3b7-4295-b87c-d0da0d90445c
2015/03/25 22:28:09 Execing /init
Spawning container rootfs on /var/lib/rkt/containers/run/65c9dfc4-a3b7-4295-b87c-d0da0d90445c/stage1/rootfs.
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
      "step": "copy",
      "binaries": [
        "/bin/bash",
        "/bin/busybox"
      ]
    },
    {
      "step": "cmd",
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
$  sudo python ./acipacker.py -C xz bash.json bash.aci
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
