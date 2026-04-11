Run using

```
python pdf_chunker.py <pdf_path>
```

Example:

```
python pdf_chunker.py ../sources/ocs_timeline.pdf
```

## Output

Wud print down all the chunks, each having metdata and content

### Metdata

- metadata mentions the src path, the type i.e. table/text, page number, chunk index, headers, table_ids etc.

# TODOs

- overlap debug
- hindi chunking
- header footer chunking removal
- add headers to chunks
- embed these chunks using apporporatie models and vector size
- create function for deleting all the embeddings of a given document
- create a function to list down all documents used in the database
- create api for all the three functions 