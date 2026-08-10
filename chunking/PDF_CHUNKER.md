Run using

```
python pdf_chunker.py <pdf_path> [--source-url URL] [--generation legacy|2025] [--doc-type rule]
```

## Metadata per chunk

- `page` / `page_start` / `page_end`
- `section_path`, `section_title`, `section_level`, `headers`, `header_id`
- `source_file`, `source_name`, `source_url`, `generation`, `doc_type`
- `type` (`text` | `table_row`), `chunk_index`

Content is prefixed with `[section > path]` for better BM25 matching.

## Knowledge index

```
python chunking/build_knowledge_index.py --recreate
```

Indexes CoS PDFs from `sources/cos_sources.json` plus curriculum JSON into Qdrant collection `knowledge`.
