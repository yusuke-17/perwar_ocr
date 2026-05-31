"""
環境構築の動作確認スクリプト

確認項目:
  1. Python バージョン
  2. 依存パッケージのインポート
  3. Ollama サーバーへの接続
  4. GLM-OCR モデルの存在確認 & 簡易テスト
  5. Surya OCR の読み込み確認
"""

import sys


def check_python_version():
    """Python 3.13 以上かチェック"""
    v = sys.version_info
    print(f"  Python {v.major}.{v.minor}.{v.micro}")
    if (v.major, v.minor) >= (3, 13):
        return True
    print("  ✗ Python 3.13 以上が必要です")
    return False


def check_packages():
    """依存パッケージがインポートできるかチェック"""
    packages = {
        "ollama": "ollama",
        "cv2": "opencv-python-headless",
        "PIL": "Pillow",
        "numpy": "numpy",
    }
    all_ok = True
    for module, name in packages.items():
        try:
            __import__(module)
            print(f"  ✓ {name}")
        except ImportError:
            print(f"  ✗ {name} がインポートできません → uv add {name}")
            all_ok = False
    return all_ok


def check_ollama_connection():
    """Ollama サーバーが起動しているかチェック"""
    try:
        import ollama

        models = ollama.list()
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
    print("  → 簡易テスト実行中...")
    try:
        import ollama

        response = ollama.chat(
            model=model_name,
            messages=[{"role": "user", "content": "「東京」という漢字を読んでください。"}],
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
    """Surya OCR がインポートできるかチェック"""
    try:
        from surya.recognition import RecognitionPredictor

        print("  ✓ surya-ocr インポートOK")
        print("  ※ モデルの初回ダウンロードは初回実行時に自動で行われます")
        return True
    except ImportError:
        print("  ✗ surya-ocr がインポートできません → uv add surya-ocr")
        return False
    except Exception as e:
        print(f"  △ surya-ocr インポート時に警告: {e}")
        return True


def main():
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

    print("\n[5/5] Surya OCR")
    results["surya"] = check_surya()

    # 結果サマリー
    print("\n" + "=" * 50)
    print("結果サマリー")
    print("=" * 50)
    labels = {
        "python": "Python バージョン",
        "packages": "依存パッケージ",
        "ollama": "Ollama 接続",
        "glm_ocr": "GLM-OCR モデル",
        "surya": "Surya OCR",
    }
    all_ok = True
    for key, label in labels.items():
        status = "✓" if results[key] else "✗"
        print(f"  {status} {label}")
        if not results[key]:
            all_ok = False

    if all_ok:
        print("\n🎉 すべてのチェックをパスしました！ Step 2 に進めます。")
    else:
        print("\n⚠ 上記の ✗ の項目を修正してから再実行してください。")

    return 0 if all_ok else 1


def run(args=None) -> int:
    """統合CLI（prewar check）用アダプタ。引数は受け取るが使用しない。"""
    return main()


if __name__ == "__main__":
    sys.exit(main())
