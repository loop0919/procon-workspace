## Procon Workspace

競技プログラミング用の便利なワークスペースです。

## 使い方（提出用 1 ファイル生成）

解答コードでライブラリを import しつつ、

```py
from lib.math.comb import Comb
```

提出前に bundle コマンドで `lib.*` の import を展開して 1 ファイルにします。

```bash
python -m lib.bundle path/to/main.py -o logs/bundled.py
```

`logs/bundled.py` には `class Comb: ...` のように必要な定義が埋め込まれ、`from lib...` は除去されます。

## Bash コマンド

`scripts/commands.sh` を読み込むと、提出やローカル実行が楽になります。

`prows bundle` / `prows run` は基本的にリポジトリ内の `.venv` を使って実行します（`.venv` が無い場合はシステムの `python` / `python3` にフォールバックします）。  
解答で `requirements.txt` のライブラリを使う場合や、`prows bundle` の自動整形（`black` / `isort`）を有効にしたい場合は、事前に仮想環境を作成して依存を入れてください。

```bash
./scripts/setup_venv.sh
```

```bash
# コマンドを読み込む
source scripts/commands.sh

# logs/bundled_YYYYMMDDhhmmss.py にバンドル & クリップボードにコピー
prows bundle main.py
# io/output.txt に出力
prows run main.py
```

## 開発環境

`prows bundle` は `black` と `isort` で生成物を自動整形します。
未インストールの場合は仮想環境を作って導入してください（`./scripts/setup_venv.sh` は `.venv` を作成し、`requirements.txt` をインストールします）。
