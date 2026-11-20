# AI eval set

`text_to_sql.jsonl` will hold ~30 questions with known answers (one JSON object per line):

```json
{"id": "q001", "question": "What was Apple's revenue in fiscal 2023?", "expected_sql": "SELECT ...", "expected_answer": [[383285000000]]}
```

CI runs the eval whenever files in `src/finxplore/ai/` change, and tracks accuracy over time
(target: 90%+). Used to pick the Bedrock model (see the open questions in `docs/ARCHITECTURE.md`).
