# 語源・接辞 v2 の dry-run

日時: 2026-10-13 12:45 +09:00。AnkiConnect の書き込みは呼んでいない。`--apply` は付けていない。

## 主張

表面から語源・接辞を外し、裏面の解答の後に1回だけ置ける。次の100件は既存100件と重ならず、省略のある既存ヒント63件と新100件は、語源・接辞フィールドだけの更新として出せる。

## データ

- backup: `013TOEIC英単語・意味` 1062ノート、`014TOEIC英単語・文脈` 1042ノート。Basic / Cloze の templates と styling を `backup_before.json` に保存した。
- select: 除外100件、選定100件。lapses は 4 が1件、2 が1件、1 が6件、0 が92件。同数は最近の失敗（ease=1 の review id）が新しい順。
- fields dry-run: 新規100件／修正63件／変更なし0件。末尾は `dry-run fields: not written`。
- 既存100件のうち、各要素に意味があり省略も無い37件は CSV に入れていない。空のまま上書きしないためである。
- pytest: `tests/test_toefl_etym_v2.py` は 7 件成功。

## テンプレート diff

Basic の Front から条件ブロックを除き、Back の `{{Back}}` の後へ移す。Cloze の Front からも除く。Cloze の Back はもともと本文の後に1回あるので、差分は出ない。

```diff
--- Basic/Card 1/Front (before)
+++ Basic/Card 1/Front (after)
@@ -1,2 +1 @@
- {{Front}}
-{{#語源・接辞}}<div class="etym-hint">語源・接辞: {{語源・接辞}}</div>{{/語源・接辞}}
+ {{Front}}
--- Basic/Card 1/Back (before)
+++ Basic/Card 1/Back (after)
@@ -2,4 +2,6 @@
 
 <hr id=answer>
 
-{{Back}}
+{{Back}}
+
+{{#語源・接辞}}<div class="etym-hint">語源・接辞: {{語源・接辞}}</div>{{/語源・接辞}}
```

```diff
--- Cloze/Cloze/Front (before)
+++ Cloze/Cloze/Front (after)
@@ -1,2 +1 @@
-{{edit:cloze:Text}}
-{{#語源・接辞}}<div class="etym-hint">語源・接辞: {{語源・接辞}}</div>{{/語源・接辞}}
+{{edit:cloze:Text}}
```

Cloze の Back は変更なし。`dry-run templates Basic: not written` と `dry-run templates Cloze: not written` を確認した。

## 論拠

Anki は Front テンプレートに条件ブロックがあると、答えを出す前に語源を描く。Basic の裏面は `{{FrontSide}}` を含むので、Front に残したままでは裏面だけにできない。Front から除き、`{{Back}}` の後に1回置けば、採点本文は `{{Front}}` と `{{Back}}` のまま、語源は解答の後に出る。Cloze は表面と裏面が別テンプレートなので、Front から除けば裏面の既存1回が残る。

フィールドの payload は `語源・接辞` だけである。Front / Back / Text / Back Extra を payload に入れないので、承認後の apply でも採点本文は書き換わらない。dry-run は `updateModelTemplates` と `updateNoteFields` を呼ぶ前に止まる。CSS は折返しの原因ではないので変えていない。
