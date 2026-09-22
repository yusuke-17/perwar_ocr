"""
環境構築の動作確認スクリプト

確認項目:
  1. Python バージョン
  2. 依存パッケージのインポート
  3. Ollama サーバーへの接続
  4. GLM-OCR モデルの存在確認 & 簡易テスト
  5. Surya OCR の導入有無（任意。未導入でも不合格にしない）

合否（終了コード）は必須項目（1〜4）だけで決める。
"""

import importlib.util
import sys

# 確認する必須パッケージ（import 名 → パッケージ名）。
# pyproject.toml の dependencies のうち、コードが実際に import するものにそろえる。
REQUIRED_PACKAGES = {
    "ollama": "ollama",                       # OCR・口語化
    "httpx": "httpx",                         # タイムアウト例外の捕捉
    "cv2": "opencv-python-headless",          # 画像前処理
    "numpy": "numpy",                         # 画像前処理
    "jaconv": "jaconv",                       # 全角正規化
    "senzen_word": "senzen-word",             # 旧字体・仮名変換
    "questionary": "questionary",             # 対話メニュー
    "rich": "rich",                           # 進捗表示
}


def check_python_version():
    """Python 3.13 以上かチェック"""
    v = sys.version_info
    print(f"  Python {v.major}.{v.minor}.{v.micro}")
    if (v.major, v.minor) >= (3, 13):
        return True
    print("  ✗ Python 3.13 以上が必要です")
    return False


def check_packages():
    """必須パッケージがインポートできるかチェック"""
    all_ok = True
    for module, name in REQUIRED_PACKAGES.items():
        try:
            __import__(module)
            print(f"  ✓ {name}")
        except ImportError:
            # 依存は pyproject.toml に宣言済みなので、足りないのは「同期漏れ」
            print(f"  ✗ {name} がインポートできません → uv sync を実行してください")
            all_ok = False
    return all_ok


def check_ollama_connection():
    """Ollama サーバーが起動しているかチェック"""
    try:
        from utils.ollama_client import list_client, list_timeout, ollama_errors

        # timeout 付きで問い合わせる（Ollamaが固まっていても永久に待たない）
        with ollama_errors("", list_timeout()):
            models = list_client().list()
        model_names = [m.model for m in models.models]
        print(f"  ✓ Ollama 接続OK（{len(model_names)} モデル検出）")
        for name in model_names:
            print(f"    - {name}")
        return True, model_names
    except Exception as e:
        print(f"  ✗ Ollama に接続できません: {e}")
        print("  → Ollama.app を起動してください（メニューバーにアイコンが出ます）")
        return False, []


def check_glm_ocr(model_names: list[str]):
    """GLM-OCR モデルがダウンロード済みかチェックし、簡易テストを実行"""
    # モデル名の確認（glm-ocr:latest や glm-ocr:0.9b などにマッチ）
    found = [n for n in model_names if "glm-ocr" in n.lower()]
    if not found:
        print("  ✗ GLM-OCR モデルが見つかりません")
        print("  → ollama pull glm-ocr を実行してください")
        return False

    model_name = found[0]
    print(f"  ✓ モデル検出: {model_name}")

    # テキストのみの簡易テスト（画像なし）
    # 初回はモデルのメモリロードで数十秒かかるのが普通なので、
    # 短い専用timeoutは設けず生成用の設定を共有し、待ち上限だけ画面に出す。
    from utils.ollama_client import chat_client, generate_timeout, ollama_errors

    limit = generate_timeout()
    suffix = f"（最大 {limit:.0f} 秒待ちます）" if limit else ""
    print(f"  → 簡易テスト実行中...{suffix}")
    try:
        with ollama_errors(model_name, limit):
            response = chat_client().chat(
                model=model_name,
                messages=[
                    {"role": "user", "content": "「東京」という漢字を読んでください。"}
                ],
            )
        reply = response.message.content.strip()
        # 長すぎる場合は省略
        if len(reply) > 100:
            reply = reply[:100] + "..."
        print(f"  ✓ GLM-OCR 応答: {reply}")
        return True
    except Exception as e:
        print(f"  ✗ GLM-OCR テスト失敗: {e}")
        return False


def check_surya():
    """Surya OCR（任意の追加依存）が導入済みかチェック

    import はせず有無だけを見る（import すると torch ごと読み込んで数秒かかるため）。
    未導入でも False を返すだけで、合否には影響しない（main() 側で任意項目として扱う）。
    """
    if importlib.util.find_spec("surya") is not None:
        print("  ✓ surya-ocr 導入済み")
        return True
    print("  - 未導入（任意）。使う場合は uv sync --extra surya を実行してください")
    return False


# 合否に使う必須項目と、表示だけする任意項目（キー → 表示名）
REQUIRED_CHECKS = {
    "python": "Python バージョン",
    "packages": "依存パッケージ",
    "ollama": "Ollama 接続",
    "glm_ocr": "GLM-OCR モデル",
}
OPTIONAL_CHECKS = {
    "surya": "Surya OCR（任意）",
}


def main():
    """環境を確認して結果を表示する。必須項目がすべて合格なら 0、それ以外は 1。"""
    print("=" * 50)
    print("戦前日本語OCR — 環境チェック")
    print("=" * 50)

    results = {}

    print("\n[1/5] Python バージョン")
    results["python"] = check_python_version()

    print("\n[2/5] 依存パッケージ")
    results["packages"] = check_packages()

    print("\n[3/5] Ollama サーバー接続")
    ollama_ok, model_names = check_ollama_connection()
    results["ollama"] = ollama_ok

    print("\n[4/5] GLM-OCR モデル")
    if ollama_ok:
        results["glm_ocr"] = check_glm_ocr(model_names)
    else:
        print("  - スキップ（Ollama 未接続）")
        results["glm_ocr"] = False

    print("\n[5/5] Surya OCR（任意）")
    results["surya"] = check_surya()

    # 結果サマリー
    print("\n" + "=" * 50)
    print("結果サマリー")
    print("=" * 50)
    all_ok = True
    for key, label in REQUIRED_CHECKS.items():
        status = "✓" if results[key] else "✗"
        print(f"  {status} {label}")
        if not results[key]:
            all_ok = False
    # 任意項目は未導入でも ✗ にせず、合否にも数えない
    for key, label in OPTIONAL_CHECKS.items():
        status = "✓" if results[key] else "−（未導入）"
        print(f"  {status} {label}")

    if all_ok:
        print("\n🎉 すべてのチェックをパスしました！ Step 2 に進めます。")
    else:
        print("\n⚠ 上記の ✗ の項目を修正してから再実行してください。")

    return 0 if all_ok else 1


def run(args=None) -> int:
    """統合CLI（prewar check）用アダプタ。引数は受け取るが使用しない。"""
    return main()
