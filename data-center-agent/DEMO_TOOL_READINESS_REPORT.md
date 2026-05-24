# Tool Readiness Report

## Implemented tools

- `find_data`
- `semantic_search`
- `get_variable_detail`
- `get_report_detail`
- `get_source_detail`
- `get_organization_detail`
- `compare_concepts`
- `list_available_filters`
- `job_status`
- `submit_feedback`

## Missing tools

- None from the requested demo-safe surface.

## Unsafe tools not exposed

- Arbitrary shell commands
- `ingest_excel`
- `process_source`
- `process_report`
- `process_ecosystem_org`
- `resolve_source`
- `generate_codebook`
- `create_extraction_batch`
- `import_extraction_batch`
- `create_review_batch`
- `import_review_batch`
- `build_search_index`
- `embed_search_index`
- `migrate`
- Deletion helpers

## Sample commands and outputs

```bash
python -m app.tools.demo find_data --args '{"query":"startup funding in Singapore","limit":3,"public_only":true}'
```

```json
{"ok": true, "tool": "find_data", "data": {"query": "startup funding in Singapore", "closest_variables": [], "closest_datasets": [], "relevant_reports": [], "source_links": [], "relevant_organizations": []}}
```

```bash
python -m app.tools.demo semantic_search --args '{"query":"VC deal count","object_types":["variable","dataset"],"limit":3}'
```

```json
{"ok": true, "tool": "semantic_search", "data": {"query": "VC deal count", "mode": "keyword_fallback", "results": []}}
```

```bash
python -m app.tools.demo get_variable_detail --args '{"variable_id":"<variable_uuid>"}'
python -m app.tools.demo get_report_detail --args '{"report_id":"<report_uuid>"}'
python -m app.tools.demo get_source_detail --args '{"source_id":"<source_uuid>"}'
python -m app.tools.demo get_organization_detail --args '{"organization_id":"<organization_uuid>"}'
python -m app.tools.demo compare_concepts --args '{"query_or_concept_id":"venture funding","report_ids":["<report_uuid>"]}'
python -m app.tools.demo list_available_filters --args '{}'
python -m app.tools.demo job_status --args '{"job_id":"<job_uuid>"}'
python -m app.tools.demo submit_feedback --args '{"answer_id":"answer-123","feedback_type":"thumbs_up","comment":"Useful result."}'
```

All tools return:

```json
{"ok": true, "tool": "<tool_name>", "data": {}}
```

Errors return:

```json
{"ok": false, "tool": "<tool_name>", "error": {"code": "invalid_args", "message": "query is required."}}
```
