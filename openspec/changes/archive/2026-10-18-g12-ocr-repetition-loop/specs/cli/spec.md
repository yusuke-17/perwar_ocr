## ADDED Requirements

### Requirement: 環境確認での Ollama バージョンの表示
システムは `prewar check` で、接続できた Ollama サーバーのバージョンを表示しなければならない（SHALL）。
バージョンが取得できなくても、環境確認を不合格にしてはならない（MUST NOT）。

#### Scenario: Ollama に接続できる
- **WHEN** Ollama が起動している環境で `prewar check` を実行する
- **THEN** Ollama の接続確認の結果とともに、サーバーのバージョン（例: 0.40.2）が表示される

#### Scenario: バージョンが取得できない
- **WHEN** Ollama には接続できるが、バージョンの問い合わせに失敗する
- **THEN** バージョンは「不明」と表示され、他の項目がすべて揃っていれば環境確認は合格になる
