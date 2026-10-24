"""
環境構築の動作確認スクリプト

確認項目:
  1. Python バージョン
  2. 依存パッケージのインポート
  3. Ollama サーバーへの接続（バージョンも表示。口語化に使う）
  4. 選ばれた OCR エンジン（[models] ocr）
     - NDLOCR-Lite: ソースとモデルの有無・import・版（モデルは読み込まない）
     - Ollama のモデル（GLM-OCR など）: モデルの存在確認 & 簡易テスト
  5. 選ばれていない方の OCR エンジンの導入有無（任意。未導入でも不合格にしない）

合否（終了コード）は必須項目（1〜4）だけで決める。
"""

import sys

from utils.config import CONFIG
from utils.ndlocr_client import NDLOCR_ENGINE

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
    # 以下は NDLOCR-Lite（vendor/ndlocr-lite）の実行に要る
    "onnxruntime": "onnxruntime",
    "PIL": "pillow",
    "yaml": "pyyaml",
    "lxml": "lxml",
    "networkx": "networkx",
    "tqdm": "tqdm",
}

# OCR エンジンを Ollama で動かすときの既定のモデル（任意項目の表示に使う）
_GLM_OCR = "glm-ocr"


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
        print(f"    バージョン: {_ollama_version_or_unknown()}")
        for name in model_names:
            print(f"    - {name}")
        return True, model_names
    except Exception as e:
        print(f"  ✗ Ollama に接続できません: {e}")
        print("  → Ollama.app を起動してください（メニューバーにアイコンが出ます）")
        return False, []


def _ollama_version_or_unknown() -> str:
    """Ollama のバージョン。取れなければ「不明」（合否には影響させない）

    Ollama.app は自動更新されるため、OCR の挙動が変わったときの切り分けに表示する（G12）。
    """
    from utils.ollama_client import ollama_version

    try:
        return ollama_version()
    except Exception:
        return "不明"


def _find_model(model_names: list[str], model: str) -> list[str]:
    """取得済みのモデルのうち、指定の名前に当たるもの（glm-ocr は glm-ocr:latest などにも当たる）"""
    return [n for n in model_names if model.lower() in n.lower()]


def check_glm_ocr(model_names: list[str], model: str = _GLM_OCR):
    """OCR に使う Ollama のモデル（既定 GLM-OCR）がダウンロード済みかチェックし、簡易テストを実行"""
    found = _find_model(model_names, model)
    if not found:
        print(f"  ✗ OCR モデル '{model}' が見つかりません")
        print(f"  → ollama pull {model} を実行してください")
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


def check_ndlocr(required: bool = True) -> bool:
    """NDLOCR-Lite が使える状態か（ソースとモデルの有無・import）を確かめ、版を表示する

    モデルの読み込み（数秒かかる）と画像の認識はしない。
    required=False（選ばれていないエンジン）のときは、導入済みか未導入かを短く表示するだけ。
    """
    from utils.ndlocr_client import NdlocrNotInstalledError, read_ndlocr_version, verify_installation

    try:
        root = verify_installation()
    except NdlocrNotInstalledError as e:
        if required:
            print(f"  ✗ {e}")
        else:
            print("  - 未導入（任意）。使う場合は git submodule update --init --depth 1 を実行してください")
        return False
    print(f"  ✓ NDLOCR-Lite 導入済み（{root}）")
    print(f"    版: {read_ndlocr_version(root)}")
    return True


def check_glm_ocr_installed(model_names: list[str]) -> bool:
    """GLM-OCR が取得済みかだけを表示する（選ばれていないときの任意項目。簡易テストはしない）"""
    found = _find_model(model_names, _GLM_OCR)
    if found:
        print(f"  ✓ 取得済み: {found[0]}")
        return True
    print(f"  - 未取得（任意）。使う場合は ollama pull {_GLM_OCR} を実行してください")
    return False


def _engine_label(engine: str) -> str:
    return "NDLOCR-Lite" if engine == NDLOCR_ENGINE else f"OCR モデル {engine}"


def main():
    """環境を確認して結果を表示する。必須項目がすべて合格なら 0、それ以外は 1。

    必須項目は選ばれた OCR エンジン（[models] ocr）によって変わる。選ばれていない方は任意項目。
    """
    engine = CONFIG.get("models.ocr") or NDLOCR_ENGINE
    ndlocr_selected = engine == NDLOCR_ENGINE
    other_engine = _GLM_OCR if ndlocr_selected else NDLOCR_ENGINE

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

    print(f"\n[4/5] OCR エンジン: {_engine_label(engine)}（選択中）")
    if ndlocr_selected:
        results["ocr_engine"] = check_ndlocr()
    elif ollama_ok:
        results["ocr_engine"] = check_glm_ocr(model_names, engine)
    else:
        print("  - スキップ（Ollama 未接続）")
        results["ocr_engine"] = False

    print(f"\n[5/5] OCR エンジン: {_engine_label(other_engine)}（任意）")
    if not ndlocr_selected:
        results["other_engine"] = check_ndlocr(required=False)
    elif ollama_ok:
        results["other_engine"] = check_glm_ocr_installed(model_names)
    else:
        print("  - スキップ（Ollama 未接続）")
        results["other_engine"] = False

    # 合否に使う必須項目と、表示だけする任意項目（キー → 表示名）
    required_checks = {
        "python": "Python バージョン",
        "packages": "依存パッケージ",
        "ollama": "Ollama 接続",
        "ocr_engine": _engine_label(engine),
    }
    optional_checks = {"other_engine": f"{_engine_label(other_engine)}（任意）"}

    # 結果サマリー
    print("\n" + "=" * 50)
    print("結果サマリー")
    print("=" * 50)
    all_ok = True
    for key, label in required_checks.items():
        status = "✓" if results[key] else "✗"
        print(f"  {status} {label}")
        if not results[key]:
            all_ok = False
    # 任意項目は未導入でも ✗ にせず、合否にも数えない
    for key, label in optional_checks.items():
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
