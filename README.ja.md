# linux-screen-reader

[English](README.md) · [Português](README.pt-BR.md) · [Español](README.es.md) · [中文](README.zh-CN.md) · **日本語** · [Русский](README.ru.md) · [हिन्दी](README.hi.md)

NVDA と同じ操作感で使える Linux 用スクリーンリーダーです。NVDA キー（Insert または Caps Lock）、デスクトップ／ラップトップ配列、Web のブラウズモードとフォーカスモード、入力ヘルプ、`gestures.ini`、アドオンに対応しています。Python 3 で書かれており、AT-SPI2、evdev/uinput、Speech Dispatcher、BrlAPI の上で動作します。

パッケージ名とコマンド名は `nvda-linux` です。このプロジェクトは **NV Access および公式の NVDA とは関係ありません**。Windows で NVDA に慣れている人のために、同じ使い方を再現しているだけです。

> ⚠️ **実験版（0.1.0.dev0）。** まだ日常の利用には向きません。仮想マシン上の Fedora 45 + GNOME 51 で動作しましたが、視覚障害のある方が日常的に使ったことはまだなく、サウンドのあるマシンで実際に音声を聞いた確認もまだです。

## すでに動作する機能

実機で確認済み（Fedora 45、GNOME 51、Firefox）：

- Speech Dispatcher による読み上げと入力エコー（パスワード欄では「アスタリスク」）；
- evdev/uinput によるキーボードの取得、NVDA キー、NVDA+T（タイトル）、フォーカスの読み上げ；
- Firefox のブラウズモード：ページ読み込み時の自動読み上げ、H/B（次の見出し／ボタン）、矢印キーによる行ごとの移動。

自動テスト（279 件）で確認済みだが実機ではまだ未確認：読み上げに合わせてカーソルが移動する「すべて読み上げ」、クイックナビゲーション全般（K、F、T、D、1–6…）、表、要素リスト、点字、GTK 4 の GUI、アドオン。

## インストール

PyGObject 3.50 以降が必要です：**Debian 13、Ubuntu 25.04 以降、Fedora 41+、openSUSE Tumbleweed、Arch**。Ubuntu 24.04 はまだ対応していません。

いちばん簡単なのは [Releases](https://github.com/manoslv06-maker/linux-screen-reader/releases) ページにある一体型インストーラーです。ディストリビューションを自動で判別し、apt、dnf、zypper、pacman のいずれかを使います：

```sh
sh nvda-linux-instalador-0.1.0.dev0.run          # インストール（input グループを変更する前に確認します）
sh nvda-linux-instalador-0.1.0.dev0.run --help
sh nvda-linux-instalador-0.1.0.dev0.run --uninstall
```

ソースからインストーラーを作成する方法は[パッケージのビルド](#パッケージのビルド)を参照してください。

### 初めて試す前に

スクリーンリーダーはキーボード全体を取得します。**予備のログイン手段**（SSH や別のテキストコンソール）を用意し、次を覚えておいてください：**Ctrl+Alt+Shift+Esc** でスクリーンリーダーが終了し、キーボードが戻ります。

```sh
sudo usermod -aG input $USER      # その後、ログアウトして再ログインしてください
nvda-linux --check-permissions    # 診断
nvda-linux --debug                # ターミナルで詳細ログ付きで実行
systemctl --user enable --now nvda-linux.service   # セッションと一緒に起動（任意）
```

ログは `~/.local/state/nvda-linux/nvda.log` にあります。

## 開発

```sh
pip install -e ".[dev,audio]"
PYTHONPATH=src python -m pytest -q
PYTHONPATH=src python -m mypy --strict src/nvda_linux
ruff check src tests
```

テストは偽のオブジェクトを使うため、AT-SPI2、音声、キーボードは不要です。Linux で実行してください（Windows では一部のテストが動きません）。

ドキュメント（ポルトガル語）：

- [docs/ROADMAP.md](docs/ROADMAP.md)：予定しているフェーズとバージョン；
- [docs/platform/README.md](docs/platform/README.md)：イベントループ、音声、キーボード、点字、パッケージング；
- [docs/semantics/README.md](docs/semantics/README.md)：AT-SPI2、イベント、ブラウズモード、GUI；
- [docs/semantics/ADDONS.md](docs/semantics/ADDONS.md)：アドオン；
- [CLAUDE.md](CLAUDE.md)：現在の状況と次のステップ。

### パッケージのビルド

各スクリプトは対応するディストリビューション上で実行し、`dist/` に出力します：

| スクリプト | 生成物 |
|---|---|
| `packaging/build-packages.sh` | `.deb` とソースの `.tar.gz`（Debian/Ubuntu） |
| `packaging/build-rpm.sh` | `.rpm`（実行したマシンに応じて Fedora または openSUSE） |
| `packaging/build-arch.sh` | `.pkg.tar.zst`（Arch、一般ユーザーで実行） |
| `packaging/build-installer.sh` | 上記すべてを含む `nvda-linux-instalador-<バージョン>.run` |

## ライセンス

[GPL-2.0-or-later](LICENSE)。
