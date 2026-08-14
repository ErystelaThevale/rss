# RSS Relay Explorer 設計ノート

- **このファイルは現在有効な設計のみを記す。** 設計変更の経緯・実装時に発見したバグ・レビューで指摘された不整合などの時系列記録は `DESIGN_HISTORY.md` を参照。
- ステータス: 取得層（本ドキュメントの対象）のみ実装済み。フィード選定を絞り込むための照合・relay判定層は未着手。

---

## 1. 全体構成（取得層のパイプライン）

```
rss_feeds.csv（購読フィード一覧: platform, label, url, category）
      ↓ load_feed_targets → _group_targets_by_url（同一urlの行を1グループに束ねる。§2.1）
グループ単位でfeedparserで取得（core/fetch_feed.py、1グループ=1リクエスト）
      ↓ プラットフォーム別にlink/comments/published_atを正規化（§2）
      ↓ Redditのみ: linkからサブレ名を逆引きし、正しい行のlabelへ差し替え（§2.1）
days_back日以内のものだけ残す
      ↓ Redditのみ: サブレ単位で件数上限（reddit_max_per_subreddit引数）をかける（§2.1）
translate=Trueならタイトルを DeepL で一括翻訳（core/translator.py）、Falseならtitle_original をそのままtitle_translatedに使う（§2.2）
      ↓
rss_items.csvへ保存（core/acquisition.py、§3のスキーマで全件洗い替え）
      ↓
Streamlit UI（ui/feed_tab.py）でテーブル表示（§4）
```

- `run_acquisition(days_back, translate=True, reddit_max_per_subreddit=REDDIT_MAX_PER_SUBREDDIT)`が上記全体を1回で実行し、`rss_items.csv`を**毎回全件上書き**する（過去分との差分保持はしない）。
- Fetchボタンを押す前（またはボタンを押さずに開いた直後）は、`load_saved_items()`が前回保存済みの`rss_items.csv`をそのまま表示する。
- **フィルタ・上限は翻訳より前で行う**（DeepL APIコストは翻訳に回した件数に比例するため、粗い母集団のうちに絞ってから翻訳する。§2.1参照）。

### 2.2 翻訳のオプション化

`translate`引数（既定`True`）でDeepL呼び出しをスキップできる。`False`の場合、`title_translated`列には`title_original`と同じ値がそのまま入る（DeepL APIを一切呼ばないため、この場合に限り`DEEPL_TOKEN`未設定でも動作する）。UI（§4）ではチェックボックスの初期値を`bool(DEEPL_TOKEN)`にしている——トークンが設定されていればデフォルトON、無ければデフォルトOFFで、いずれも実行時にユーザーが上書きできる。

---

## 2. プラットフォーム別の取得仕様（`core/fetch_feed.py`）

`FeedItem`（title / link / published_at / comments）は`fetch_feed_items(platform, label, url)`が生成する。取得元フィールドはプラットフォームごとに異なる（2026-08-14、実地確認済み）。

| platform | title | link | comments | 備考 |
|---|---|---|---|---|
| `hn`（hnrss.org） | `entry.title` | `entry.comments`（HN本体のitemページ。無ければ`entry.link`にフォールバック） | `entry.summary`内の`# Comments: N`を正規表現抽出 | `entry.link`はHN本体ではなく記事本文が指す外部URL（Article URL）。HNへコメントを返す用途では使えないため、コメント可能なHN本体スレッドを`link`として採用する |
| `lemmy` | `entry.title` | `entry.link`（Lemmyの投稿ページ＝コメント欄そのもの） | `entry.summary`内の`\| <a href=...>N comments</a>`を正規表現抽出 | `entry.summary`（CDATA）に投稿本文全体も含まれるため、`\|`直後のアンカー要素に絞って抽出しないと本文中の数字を誤検出しうる |
| `reddit` | `entry.title` | `entry.link`（Redditのコメントページ） | **取得不可（対象外）** | 未認証`.rss`にはコメント数を示すフィールドが一切存在しない（フィード全文を確認して確定）。取得するには認証付きAPI（OAuth）か投稿ごとの追加リクエストが必要になり、「RSSを軽く取得するだけ」という設計から外れるため、ユーザー方針により対象外とした。ただし§2.1の`hot`ソートが実質的な活性度シグナルの代替になっている |

- `comments`は現在のスレッドの活性度の指標として保持する。値が取れないプラットフォーム（Reddit）・投稿（コメント0件のHN/Lemmy）はそれぞれ`None`/`0`として区別される。
- `published_at`は`published_parsed`優先、無ければ`updated_parsed`にフォールバック（tz-aware UTCに正規化）。
- title・link・published_atのいずれかが欠けている entry はスキップする（`comments`はNone許容、必須項目には含めない）。

### 2.1 Redditの結合フィード取得（`core/acquisition.py`）

**背景**: 未認証`.rss`はサブレディット名に関係なく、**IPごとに45〜60秒に1回しかリクエストを通さない時間窓ベースのレート制限**がかかっている（2026-08-14実測。DESIGN_HISTORY.md「M4・M5」参照）。サブレ単位で1リクエストずつ叩く旧方式では、購読数が増えるほど失敗率が上がる構造的な欠陥があった。

**対策（`rss_feeds.csv`の構成）**: Reddit分の各行（1行=1サブレ、`label`・`category`はサブレごとに個別）は、**全行が同一の結合URL**を`url`列に持つ:
```
https://www.reddit.com/r/{sub1}+{sub2}+.../hot/.rss?limit=100
```
- ソートは`new`ではなく**`hot`**を使う。`new`は投稿頻度の高いサブレが枠を独占する（実測: 25件中LocalLLaMAが10件）。`top`はさらに悪化する（実測: 週間topでEconomicsが25件中14件）。`hot`は各コミュニティ内でスコアと経過時間を正規化してランキングするため、結合フィードでも17サブレ中15〜17サブレが自然に分散して現れる（実測）。
- `limit=100`で1リクエストの取得件数を増やすことで、購読中の全サブレが（投稿頻度に関わらず）100件の中に現れる可能性を上げている（実測: 17/17サブレ全て出現）。

**取得側の処理（`_group_targets_by_url`・`_resolve_reddit_label`）**:
1. `load_feed_targets()`が返す全行を`url`でグルーピングする（`_group_targets_by_url`）。urlを共有する行（＝Reddit全サブレ）は1グループになり、**1回のfetchで済む**（26行→10フェッチグループ、うちReddit 17行→1グループ）。
2. 取得した各`FeedItem`は、`fetch_feed_items`呼び出し時点では暫定的にグループ先頭行のlabelを持つ。グループの行数が2以上（＝Reddit結合フィードの場合のみ）、`item.link`からサブレ名を正規表現で逆引きし（`_resolve_reddit_label`）、対応する行の正しい`label`に差し替える。CSV未収載のサブレが結合フィードに紛れ込んだ場合は`r/{サブレ名}`をそのまま生成してフォールバックする。
3. `days_back`日フィルタの後、**Redditのみサブレ単位で件数上限（`reddit_max_per_subreddit`引数、既定値は`REDDIT_MAX_PER_SUBREDDIT`=5、UI側で実行時に変更可能。§4）**をかける。`hot`順で返ってきた並びをそのまま使うため、事実上「サブレごとの上位N件（hot順）」を残す形になる。この上限は翻訳（DeepL）に送る前に適用する（翻訳コスト抑制が目的。ユーザー提案）。

**効果（2026-08-14実測）**: リクエスト数26→10、Reddit分は17リクエスト（12件が429で失敗）→1リクエスト（100件取得、17/17サブレ出現）。日付フィルタ＋上限後もReddit全17サブレが最終結果に残る（実測: 各サブレ1〜5件）。

---

## 3. 保存スキーマ（`rss_items.csv`）

`core/acquisition.py`の`_COLUMNS`が正:

| 列 | 内容 |
|---|---|
| platform | `hn` / `reddit` / `lemmy` |
| source | フィードのlabel（例: `r/philosophy`） |
| title_translated | DeepLで`TARGET_LANG`（既定`JA`）へ翻訳したタイトル |
| title_original | 原文タイトル |
| comments | 現在のコメント数（§2参照。Reddit行は常に空） |
| published_at | 投稿日時（ISO8601、UTC） |
| link | §2の基準で選んだ、コメント可能なページのURL |
| fetched_at | このバッチの取得日時（ISO8601、UTC。行ごとではなくバッチ単位で同一値） |

**列が増減した場合の後方互換**: UI側（§4）は`reindex`で表示列を組み立てるため、保存済みCSVに新しい列が無くてもクラッシュしない（欠けている列はNaN補完）。ただし内容自体（例: 旧HN行のlinkが記事URLのまま）は再Fetchするまで更新されない。

---

## 4. UI表示（`ui/feed_tab.py`）

- Fetch実行前の入力: `Days back`（既定`DEFAULT_DAYS_BACK`）・`Translate titles`チェックボックス（既定`bool(DEEPL_TOKEN)`、§2.2）・`Reddit: max/sub`数値入力（既定`REDDIT_MAX_PER_SUBREDDIT`、§2.1）。いずれも`run_acquisition`へそのまま渡す。
- 表示列: `source, comments, title_translated, published_at, link`（この順）。
- `df.reindex(columns=display_columns)`で選択する。**単純な`df[[...]]`による列選択は使わない**——保存済みCSVのスキーマがコードの期待と食い違うと`KeyError`で画面全体がクラッシュする（2026-08-14に実際に発生。DESIGN_HISTORY.md参照）。`reindex`なら不足列はNaN埋めで表示自体は継続する。
- `link`列は`st.column_config.LinkColumn`で「Open」ボタン表示。
- `comments`列は`NumberColumn`。ソートやフィルタは現状UI側で提供していない（テーブルの列ソートはStreamlit標準機能でユーザー側が行える）。

---

## 5. 環境変数・設定（`core/config.py`）

| 変数 | 内容 |
|---|---|
| `DEEPL_TOKEN` | DeepL APIキー（`.env`必須、無いと翻訳時に`RuntimeError`） |
| `RSS_TARGET_LANG` | 翻訳先言語コード（既定`JA`） |

- `FETCH_DELAY_SEC`: Redditのみ15秒間隔（未認証`.rss`が連続リクエストで429を返す実測に基づく）。§2.1の結合フィード化により実際にReddit分でこの間隔を使うのは1グループのみ。
- 429時は`RETRY_ON_429_WAIT_SEC`（既定50秒、実測の時間窓に合わせた値）待って再試行、最大`RETRY_ON_429_MAX_ATTEMPTS`（既定3）回まで。
- `REDDIT_MAX_PER_SUBREDDIT`（既定5）: §2.1のReddit結合フィードで、日付フィルタ後・翻訳前にサブレ単位でかける件数上限。
