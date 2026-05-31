"""
画面スクショ撮影モジュール（macOS専用）

macOS標準の `screencapture -i`（範囲選択）を使い、資料の本文だけを
ドラッグで囲って撮影する。撮影＝クロップで完結するため、ブラウザUIや
周辺本文がOCR対象に写り込まない。

「撮りためる → セッション単位で蓄積 → 最後に一括処理」という動線のうち、
撮影部分を担う。撮った画像は input/session_{日時}/pNNN.png に
読む順（＝ページ順）の連番で保存される。

使い方:
    from utils.screen_capture import is_supported, shoot_session

    if is_supported():
        images = shoot_session(Path("input"))  # list[Path] | None
"""

import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import questionary

# ---------- 定数 ----------

_TZ_JST = ZoneInfo("Asia/Tokyo")
_SCREENCAPTURE_BIN = "screencapture"


# ---------- 例外 ----------


class ScreenCaptureError(Exception):
    """画面撮影に関するエラー（非macOS実行・screencapture不在など）"""


# ---------- 公開関数 ----------


def is_supported() -> bool:
    """この環境で範囲スクショ撮影が使えるか判定する

    screencapture は macOS 専用のため darwin のみ True を返す。
    """
    return sys.platform == "darwin"


def create_session_dir(input_dir: Path) -> Path:
    """撮影セッションの一時置き場 input/session_{日時}/ を作成して返す

    日時は JST（Asia/Tokyo）。フォーマットは session_YYYY-MM-DD_HHMMSS。
    """
    timestamp = datetime.now(_TZ_JST).strftime("%Y-%m-%d_%H%M%S")
    session_dir = input_dir / f"session_{timestamp}"
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir


def capture_one(dest: Path) -> bool:
    """範囲スクショを1枚撮影し、dest に保存する

    `screencapture -i` を実行する。ユーザーが範囲選択を Esc でキャンセル
    すると画像ファイルが作られないため、実行後に dest の存在で成否を判定する。

    Returns:
        撮影できたら True、キャンセルされたら False

    Raises:
        ScreenCaptureError: 非macOS環境、または screencapture が見つからない場合
    """
    if not is_supported():
        raise ScreenCaptureError(
            "範囲スクショ撮影は macOS 専用です（screencapture が使えません）"
        )

    try:
        subprocess.run([_SCREENCAPTURE_BIN, "-i", str(dest)], check=True)
    except FileNotFoundError as e:
        raise ScreenCaptureError(
            f"{_SCREENCAPTURE_BIN} コマンドが見つかりません"
        ) from e
    except subprocess.CalledProcessError as e:
        raise ScreenCaptureError(f"スクショ撮影に失敗しました: {e}") from e

    # Esc キャンセル時はファイルが作られない
    return dest.exists()


def shoot_session(input_dir: Path) -> list[Path] | None:
    """範囲スクショを繰り返し撮影し、セッションフォルダに連番保存する

    1枚撮るごとに「次を撮る／撮り直す／終了」を対話的に選べる。
    撮った順 = ページ順として p001.png, p002.png ... と連番で保存する。

    Returns:
        撮影した画像パスのソート済みリスト（1枚以上）。
        1枚も撮らずに終了した場合は空のセッションフォルダを削除して None。

    Raises:
        ScreenCaptureError: 非macOS環境、または screencapture が見つからない場合
    """
    if not is_supported():
        raise ScreenCaptureError(
            "範囲スクショ撮影は macOS 専用です（screencapture が使えません）"
        )

    session_dir = create_session_dir(input_dir)
    print(f"\n📷 撮影セッション開始: {session_dir}/")
    print("  範囲をドラッグで囲って本文だけを撮ってください。")

    captured: list[Path] = []
    counter = 1

    while True:
        dest = session_dir / f"p{counter:03d}.png"
        print(f"\n[{counter}枚目] 範囲を選択してください（Esc でキャンセル）...")

        ok = capture_one(dest)
        if ok:
            print(f"  ✓ 保存: {dest.name}")
            captured.append(dest)
            counter += 1
            action = questionary.select(
                "次は？",
                choices=["次を撮る", "終了して処理へ"],
            ).ask()
        else:
            # キャンセルされた（ファイルなし）
            print("  － キャンセルしました")
            action = questionary.select(
                "次は？",
                choices=["撮り直す", "終了して処理へ"],
            ).ask()

        # Ctrl+C で選択を抜けた場合も終了扱い
        if action is None or action == "終了して処理へ":
            break

    if not captured:
        # 1枚も撮らずに終了 → 空フォルダを片付ける
        shutil.rmtree(session_dir, ignore_errors=True)
        print("\n撮影なしで終了しました。")
        return None

    print(f"\n✓ {len(captured)}枚 撮影しました: {session_dir}/")
    return sorted(captured)
