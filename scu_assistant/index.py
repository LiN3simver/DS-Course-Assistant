import hashlib
import json
import os
from functools import cached_property
from threading import RLock

from .data import Record, load_records
from .settings import Settings

EMBEDDING_ID = 'BAAI/bge-small-zh-v1.5'
QUERY_PREFIX = '为这个句子生成表示以用于检索相关文章：'
SCHEMA = 2


class LocalIndex:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.lock = RLock()

    @cached_property
    def client(self):
        import chromadb
        from chromadb.config import Settings as ChromaSettings
        return chromadb.PersistentClient(path=str(self.settings.chroma_path),
            settings=ChromaSettings(anonymized_telemetry=False))

    @cached_property
    def encoder(self):
        os.environ.setdefault('HF_HUB_OFFLINE', '1')
        os.environ.setdefault('TRANSFORMERS_OFFLINE', '1')
        from sentence_transformers import SentenceTransformer
        if not (self.settings.embedding_path / 'model.safetensors').is_file():
            raise RuntimeError('找不到嵌入模型，請先執行 python scripts/download_embedding.py。')
        model = SentenceTransformer(str(self.settings.embedding_path),
            device=self.settings.embedding_device, local_files_only=True)
        if model.get_embedding_dimension() != 512:
            raise RuntimeError('目前索引需要 bge-small-zh-v1.5 的 512 維向量；更換模型需建立另一個 collection。')
        return model

    def collection(self):
        try:
            collection = self.client.get_collection(self.settings.collection, embedding_function=None)
        except Exception as exc:
            raise RuntimeError('找不到可用的檢索索引，請先執行 python build_vectordb_Chroma.py。') from exc
        meta = collection.metadata or {}
        if meta.get('schema_version') != SCHEMA or meta.get('embedding_model') != EMBEDDING_ID or not meta.get('ready'):
            raise RuntimeError('索引版本不符或建置尚未完成，請重新執行 python build_vectordb_Chroma.py。')
        return collection

    def chunks(self, records: list[Record]) -> list[Record]:
        from langchain_text_splitters import RecursiveCharacterTextSplitter
        # Reserve token space for the identity header. Character counts can
        # otherwise silently truncate Chinese passages at BGE's 512-token limit.
        tokenizer = self.encoder.tokenizer
        splitter = RecursiveCharacterTextSplitter(
            length_function=lambda text: len(tokenizer.encode(text, add_special_tokens=False, verbose=False)),
            chunk_size=380, chunk_overlap=80,
            separators=['\n\n', '\n', '。', '！', '？', ' ', ''])
        chunks = []
        for record in records:
            header = f"來源：{record.metadata['name']}"
            if record.metadata['source'] == 'course':
                header += f"；學期：{record.metadata['semester']}；代碼：{record.metadata['course_code']}；教師：{record.metadata['teacher']}"
            for number, content in enumerate(splitter.split_text(record.content)):
                text = header + '\n' + content
                if len(tokenizer.encode(text, verbose=False)) > self.encoder.max_seq_length:
                    raise RuntimeError('資料區塊超過嵌入模型長度，請縮小 chunk_size。')
                chunks.append(Record(f'{record.id}:{number}', text,
                                     dict(record.metadata, chunk=number)))
        return chunks

    def build(self) -> dict:
        records = load_records()
        if not records:
            raise RuntimeError('沒有可建置的 JSON 資料。')
        chunks = self.chunks(records)
        fingerprint = hashlib.sha256(json.dumps([(c.id, c.content, c.metadata) for c in chunks], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        metadata = {'embedding_model': EMBEDDING_ID, 'schema_version': SCHEMA,
                    'corpus_hash': fingerprint, 'ready': False}
        collection = self.client.get_or_create_collection(self.settings.collection,
            embedding_function=None, metadata=metadata, configuration={'hnsw': {'space': 'cosine'}})
        existing_meta = collection.metadata or {}
        if existing_meta.get('embedding_model') != EMBEDDING_ID or existing_meta.get('schema_version') != SCHEMA:
            raise RuntimeError('collection 已存在且使用其他模型；請另設 CHROMA_COLLECTION，避免覆蓋舊向量。')
        if existing_meta.get('ready') and existing_meta.get('corpus_hash') == fingerprint and collection.count() == len(chunks):
            return {'records': len(records), 'chunks': len(chunks), 'changed': False}
        encoder = self.encoder
        collection.modify(metadata=metadata)
        for start in range(0, len(chunks), 32):
            batch = chunks[start:start + 32]
            vectors = encoder.encode([c.content for c in batch], normalize_embeddings=True, batch_size=16).tolist()
            collection.upsert(ids=[c.id for c in batch], documents=[c.content for c in batch],
                metadatas=[c.metadata for c in batch], embeddings=vectors)
            print(f'索引進度 {min(start + 32, len(chunks))}/{len(chunks)}', flush=True)
        expected = {c.id for c in chunks}
        stale = [id_ for id_ in collection.get(include=[])['ids'] if id_ not in expected]
        if stale:
            collection.delete(ids=stale)
        collection.modify(metadata=dict(metadata, ready=True))
        return {'records': len(records), 'chunks': collection.count(), 'changed': True}

    def search(self, query: str, top_k: int = 4, semester: str | None = None,
               source: str | None = None, teacher: str | None = None,
               course_codes: list[str] | None = None, name: str | None = None,
               keywords: list[str] | None = None) -> list[dict]:
        with self.lock:
            collection = self.collection()
            filters = [{key: value} for key, value in [('semester', semester), ('source', source), ('teacher', teacher)] if value]
            if course_codes:
                filters.append({'course_code': {'$in': course_codes}})
            if name:
                filters.append({'name': name})
            where = {'$and': filters} if len(filters) > 1 else filters[0] if filters else None
            if not collection.count():
                return []
            document_filter = None
            if keywords:
                clauses = [{'$contains': word} for word in keywords]
                proposed = {'$or': clauses} if len(clauses) > 1 else clauses[0]
                profile_filter = {'$and': [proposed, {'$contains': '研究領域'}]}
                if source == 'professor' and collection.get(where=where, where_document=profile_filter, include=[])['ids']:
                    proposed = profile_filter
                # Prefer direct evidence when available; keep semantic search
                # available for synonyms with no literal match in the corpus.
                if collection.get(where=where, where_document=proposed, include=[])['ids']:
                    document_filter = proposed
            vector = self.encoder.encode([QUERY_PREFIX + query], normalize_embeddings=True).tolist()
            result = collection.query(query_embeddings=vector, n_results=min(top_k * 5, collection.count()),
                where=where, where_document=document_filter, include=['documents', 'metadatas', 'distances'])
        hits, counts = [], {}
        candidates = list(zip(result['documents'][0], result['metadatas'][0], result['distances'][0]))
        candidates.sort(key=lambda row: 1 - row[2] + .15 * sum(word in row[0] for word in (keywords or [])), reverse=True)
        for text, metadata, distance in candidates:
            similarity = 1.0 - distance
            if similarity < self.settings.min_similarity:
                continue
            record_id = metadata['record_id']
            if counts.get(record_id, 0) >= 2:
                continue
            counts[record_id] = counts.get(record_id, 0) + 1
            hits.append({'content': text, 'metadata': metadata, 'similarity': round(similarity, 4)})
            if len(hits) == top_k:
                break
        return hits
