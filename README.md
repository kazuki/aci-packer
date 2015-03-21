aci-packer
==========

[App Container Specification](https://github.com/appc/spec)に
(たぶん)準拠したACIを作成するためのコマンドラインベースのツールです．
(ACIとかRocketとか，あんまり理解していないので...)

以下の方法を使ったACIの作成に対応しています．

* Ansible
* シェルスクリプト
* バイナリ・共有オブジェクトの依存関係の抽出


This is a command-line tool to build ACI based on
[App Container Specification](https://github.com/appc/spec).

This CLI support to create ACI using the following methods.

* Ansible
* Shell script
* Extract dependencies from binary and shared object

使い方 / Usage
--------------

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
      "type": "ansible",        # ansible-playbookを実行します
      "playbook": "<playbook path>", # playbookのパス
      "copy_resolvconf": <boolean>, # /etc/resolv.confをコピーするかどうか(オプション)
      "mount_proc": <boolean>, # /procをマウントするかどうか(オプション)
      "mount_dev": <boolean>,  # /devをマウントするかどうか(オプション)
      "mount_sys": <boolean>,  # /sysをマウントするかどうか(オプション)
      "make_debian_policy_rc": <boolean> # apt-get install後にサービスを起動しないようにする．
                                         # chroot環境だとinstallに失敗する場合は有効にする(オプション)
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
    }
  ]
}
```

ACIを作成する場合は，上記のようなmanifestを指定して以下のコマンドを実行します
```
$ ./aci-packer.py test.json output.aci
```
