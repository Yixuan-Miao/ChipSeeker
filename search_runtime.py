import hashlib
import json
import os
import re
import shutil
import time

import numpy as np
from chipseeker.cloud_access import cloud_embed, is_cloud_token

EMBEDDING_TEXT_MODE = os.environ.get("CHIPSEEKER_EMBEDDING_TEXT_MODE", "title_abstract").strip().lower()


def _log(message):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [search] {message}", flush=True)


def _load_sentence_transformer(model_name):
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_name)


def _semantic_search(query_embedding, corpus_embeddings, top_k):
    query = np.asarray(query_embedding, dtype=np.float32)
    corpus = np.asarray(corpus_embeddings, dtype=np.float32)
    if query.ndim == 2:
        query = query[0]
    if corpus.ndim != 2 or corpus.shape[0] == 0:
        return []

    query_norm = float(np.linalg.norm(query))
    if query_norm <= 0:
        return []
    corpus_norms = np.linalg.norm(corpus, axis=1)
    denom = corpus_norms * query_norm
    scores = np.divide(corpus @ query, denom, out=np.zeros(corpus.shape[0], dtype=np.float32), where=denom > 0)
    top_k = max(0, min(int(top_k), scores.shape[0]))
    if top_k <= 0:
        return []
    if top_k == scores.shape[0]:
        indexes = np.argsort(-scores)
    else:
        indexes = np.argpartition(-scores, top_k - 1)[:top_k]
        indexes = indexes[np.argsort(-scores[indexes])]
    return [{"corpus_id": int(index), "score": float(scores[index])} for index in indexes]


def _format_eta(seconds):
    if seconds <= 0:
        return "0s"
    seconds = int(round(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def _cache_scope_key(scope_key):
    if EMBEDDING_TEXT_MODE in ("metadata", "metadata_enriched", "v2"):
        return f"{scope_key or 'all'}_metadata-v2"
    return scope_key or "all"


def get_cache_paths(db_file, model_name, scope_key="all"):
    db_name = os.path.splitext(os.path.basename(db_file))[0]
    db_safe = re.sub(r'[^A-Za-z0-9._-]+', '_', db_name)
    model_safe = re.sub(r'[^A-Za-z0-9._-]+', '_', model_name)
    scope_safe = re.sub(r'[^A-Za-z0-9._-]+', '_', _cache_scope_key(scope_key))
    cache_dir = os.path.join(os.path.dirname(os.path.abspath(db_file)), "cache")
    os.makedirs(cache_dir, exist_ok=True)
    cache_file = os.path.join(cache_dir, f"cache_{db_safe}_{model_safe}_{scope_safe}.npy")
    meta_file = os.path.join(cache_dir, f"cache_{db_safe}_{model_safe}_{scope_safe}.meta.json")
    return cache_file, meta_file


def _legacy_cache_candidates(db_file, model_name, scope_key="all"):
    db_name = os.path.splitext(os.path.basename(db_file))[0]
    db_safe = re.sub(r'[^A-Za-z0-9._-]+', '_', db_name)
    model_safe = re.sub(r'[^A-Za-z0-9._-]+', '_', model_name)
    scope_safe = re.sub(r'[^A-Za-z0-9._-]+', '_', _cache_scope_key(scope_key))
    cache_dir = os.path.join(os.path.dirname(os.path.abspath(db_file)), "cache")
    if not os.path.isdir(cache_dir):
        return []
    prefix = f"cache_{db_safe}_"
    suffix = f"_{model_safe}_{scope_safe}.npy"
    candidates = []
    for name in os.listdir(cache_dir):
        if not name.startswith(prefix) or not name.endswith(suffix):
            continue
        middle = name[len(prefix):-len(suffix)]
        if re.fullmatch(r"[0-9a-f]{8}", middle):
            cache_file = os.path.join(cache_dir, name)
            meta_file = cache_file[:-4] + ".meta.json"
            candidates.append((cache_file, meta_file))
    return sorted(candidates)


def _load_meta_file(meta_file):
    if not os.path.exists(meta_file):
        return {}
    with open(meta_file, 'r', encoding='utf-8') as f:
        payload = json.load(f)
    return payload if isinstance(payload, dict) else {}


def _db_signature(db_file):
    try:
        stat = os.stat(db_file)
    except OSError:
        return {}
    return {
        "path": os.path.abspath(db_file),
        "size": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "embedding_text_mode": EMBEDDING_TEXT_MODE,
    }


def _fast_exact_cache_match(cache_file, meta_file, db_file, model_name, scope_key):
    if not os.path.exists(cache_file):
        return "", 0
    try:
        meta = _load_meta_file(meta_file)
        if meta.get("db_signature") != _db_signature(db_file):
            return "", 0
        if meta.get("model_name") != model_name or meta.get("scope_key") != (scope_key or "all"):
            return "", 0
        fingerprints = meta.get("fingerprints", [])
        embeddings = np.load(cache_file, mmap_mode="r")
        if embeddings.shape[0] == len(fingerprints):
            return "exact", embeddings.shape[0]
    except Exception:
        return "", 0
    return "", 0


def _cache_matches_fingerprints(cache_file, meta_file, fingerprints):
    try:
        embeddings = np.load(cache_file, mmap_mode="r")
        meta = _load_meta_file(meta_file)
        old_fingerprints = meta.get("fingerprints", [])
        if embeddings.shape[0] == len(fingerprints) and old_fingerprints == fingerprints:
            return "exact", embeddings.shape[0]
        if (
            embeddings.shape[0] == len(old_fingerprints)
            and len(old_fingerprints) < len(fingerprints)
            and fingerprints[:len(old_fingerprints)] == old_fingerprints
        ):
            return "append_only", len(old_fingerprints)
        if embeddings.shape[0] == len(old_fingerprints):
            matched_count = _count_reusable_fingerprints(old_fingerprints, fingerprints)
            if matched_count:
                return "partial", matched_count
    except Exception:
        return "", 0
    return "", 0


def _count_reusable_fingerprints(old_fingerprints, fingerprints):
    available = {}
    for fingerprint in old_fingerprints:
        available[fingerprint] = available.get(fingerprint, 0) + 1
    matched_count = 0
    for fingerprint in fingerprints:
        count = available.get(fingerprint, 0)
        if count:
            available[fingerprint] = count - 1
            matched_count += 1
    return matched_count


def _partial_reuse_embeddings(cache_file, meta_file, fingerprints):
    old_embeddings = np.load(cache_file)
    meta = _load_meta_file(meta_file)
    old_fingerprints = meta.get("fingerprints", [])
    if old_embeddings.shape[0] != len(old_fingerprints):
        return None, []

    positions = {}
    for index, fingerprint in enumerate(old_fingerprints):
        positions.setdefault(fingerprint, []).append(index)

    reused = np.zeros((len(fingerprints), old_embeddings.shape[1]), dtype=np.float32)
    missing_indexes = []
    for index, fingerprint in enumerate(fingerprints):
        old_positions = positions.get(fingerprint)
        if old_positions:
            reused[index] = old_embeddings[old_positions.pop(0)]
        else:
            missing_indexes.append(index)
    return reused, missing_indexes


def _migrate_cache_if_needed(source_cache, source_meta, target_cache, target_meta):
    if os.path.abspath(source_cache) == os.path.abspath(target_cache):
        return source_cache, source_meta
    shutil.copy2(source_cache, target_cache)
    if os.path.exists(source_meta):
        shutil.copy2(source_meta, target_meta)
    return target_cache, target_meta


def _save_cache_meta(meta_file, db_file, model_name, scope_key, fingerprints):
    payload = {
        "cache_schema": 2,
        "embedding_text_mode": EMBEDDING_TEXT_MODE,
        "db_signature": _db_signature(db_file),
        "db_name": os.path.basename(db_file),
        "model_name": model_name,
        "scope_key": scope_key or "all",
        "fingerprints": fingerprints,
    }
    with open(meta_file, 'w', encoding='utf-8') as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def resolve_portable_cache(db_file, model_name, scope_key, fingerprints):
    primary_cache, primary_meta = get_cache_paths(db_file, model_name, scope_key)
    state, cached_count = _cache_matches_fingerprints(primary_cache, primary_meta, fingerprints) if os.path.exists(primary_cache) else ("", 0)
    if state:
        return primary_cache, primary_meta, state, cached_count
    best_partial = None
    for candidate_cache, candidate_meta in _legacy_cache_candidates(db_file, model_name, scope_key):
        state, cached_count = _cache_matches_fingerprints(candidate_cache, candidate_meta, fingerprints)
        if state in ("exact", "append_only"):
            cache_file, meta_file = _migrate_cache_if_needed(candidate_cache, candidate_meta, primary_cache, primary_meta)
            return cache_file, meta_file, state, cached_count
        if state == "partial" and (best_partial is None or cached_count > best_partial[3]):
            best_partial = (candidate_cache, candidate_meta, state, cached_count)
    if best_partial:
        cache_file, meta_file = _migrate_cache_if_needed(best_partial[0], best_partial[1], primary_cache, primary_meta)
        return cache_file, meta_file, best_partial[2], best_partial[3]
    return primary_cache, primary_meta, "", 0


def _list_text(value):
    if isinstance(value, (list, tuple)):
        return " ".join(str(item) for item in value if str(item).strip())
    return str(value or "")


def _paper_text(paper):
    title = paper.get("title", "")
    abstract = paper.get("abstract", "")
    if EMBEDDING_TEXT_MODE not in ("metadata", "metadata_enriched", "v2"):
        return f"{title} {abstract}".strip()
    parts = [
        f"Title: {title}",
        f"Abstract: {abstract}",
        f"Venue: {paper.get('venue', '')}",
        f"Author Keywords: {_list_text(paper.get('keywords'))}",
        f"IEEE Terms: {_list_text(paper.get('ieee_terms'))}",
    ]
    return "\n".join(part for part in parts if part.split(":", 1)[-1].strip())


def _dataset_fingerprints(papers):
    return [hashlib.sha1(_paper_text(paper).encode('utf-8')).hexdigest() for paper in papers]


def _paper_match_key(paper):
    doi = str((paper or {}).get("doi", "")).strip().upper()
    if doi:
        return f"doi:{doi}"
    title = re.sub(r"\s+", " ", str((paper or {}).get("title", "")).strip().lower())
    year = str((paper or {}).get("year", "")).strip()
    if title and year:
        return f"title_year:{title}|{year}"
    if title:
        return f"title:{title}"
    return f"fp:{hashlib.sha1(_paper_text(paper).encode('utf-8')).hexdigest()}"


def describe_cache_status(db_file, model_name, scope_key="all", papers_override=None):
    papers = papers_override
    if papers is None:
        with open(db_file, 'r', encoding='utf-8') as f:
            papers = json.load(f)
    cache_file, meta_file = get_cache_paths(db_file, model_name, scope_key)
    cache_state, cached_count = _fast_exact_cache_match(cache_file, meta_file, db_file, model_name, scope_key)
    resolved_cache, resolved_meta = cache_file, meta_file
    fingerprints = []
    if not cache_state:
        fingerprints = _dataset_fingerprints(papers)
        resolved_cache, resolved_meta, cache_state, cached_count = resolve_portable_cache(
            db_file, model_name, scope_key, fingerprints
        )
    status = {
        "cache_file": resolved_cache or cache_file,
        "meta_file": resolved_meta or meta_file,
        "total_papers": len(papers),
        "cached_papers": 0,
        "has_cache": bool(cache_state),
        "up_to_date": False,
        "needs_build": not bool(cache_state),
        "append_only": False,
        "new_papers": len(papers),
    }
    if cache_state == "exact":
        meta = _load_meta_file(resolved_meta)
        if not meta.get("db_signature"):
            _save_cache_meta(resolved_meta, db_file, model_name, scope_key, fingerprints)
        status["cached_papers"] = cached_count
        status["up_to_date"] = True
        status["needs_build"] = False
        status["new_papers"] = 0
        return status
    if cache_state == "append_only":
        status["append_only"] = True
        status["cached_papers"] = cached_count
        status["new_papers"] = max(0, len(fingerprints) - cached_count)
        return status
    if cache_state == "partial":
        status["cached_papers"] = cached_count
        status["new_papers"] = max(0, len(fingerprints) - cached_count)
        return status
    return status


class PaperSearcher:
    def __init__(self, db_file, model_name='BAAI/bge-large-en-v1.5', api_key="", papers_override=None, scope_key="all", progress_callback=None, log_callback=None):
        self.jp = db_file
        self.mn = model_name
        self.ak = api_key
        self.scope_key = scope_key or "all"
        self.progress_callback = progress_callback
        self.log_callback = log_callback
        self.mt = 'c' if is_cloud_token(self.ak) else ('v' if 'voyage' in self.mn else ('o' if 'text-embedding' in self.mn else 'l'))
        self.dt = papers_override if papers_override is not None else self._load_db()
        self.cf, self.mf = get_cache_paths(self.jp, self.mn, self.scope_key)

        self._log(f"init model={self.mn} mode={self.mt} scope={self.scope_key} cache={self.cf}")
        self.md = None
        self.eb = self._load_cache()

    def _init_model(self):
        if self.mt == 'c':
            return {"cloud_access": True}
        if self.mt == 'v':
            import voyageai
            return voyageai.Client(api_key=self.ak)
        if self.mt == 'o':
            from openai import OpenAI
            return OpenAI(api_key=self.ak)
        return _load_sentence_transformer(self.mn)

    def _ensure_model(self):
        if self.md is None:
            self._log(f"initializing embedding backend model={self.mn} mode={self.mt}")
            self.md = self._init_model()
        return self.md

    def _load_db(self):
        with open(self.jp, 'r', encoding='utf-8') as f:
            return json.load(f)

    def _paper_text(self, paper):
        return _paper_text(paper)

    def _dataset_fingerprints(self):
        return _dataset_fingerprints(self.dt)

    def _load_meta(self):
        if not os.path.exists(self.mf):
            return None
        try:
            with open(self.mf, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as exc:
            self._log(f"failed to load meta {self.mf}: {exc}")
            return None

    def _save_meta(self, fingerprints):
        _save_cache_meta(self.mf, self.jp, self.mn, self.scope_key, fingerprints)

    def _emit_progress(self, done, total, message):
        if self.progress_callback:
            self.progress_callback(done, total, message)

    def _log(self, message):
        _log(message)
        if self.log_callback:
            self.log_callback(message)

    def _remote_embed_batch(self, batch, batch_index, total_batches, stage_message, start_idx, total, max_attempts=3):
        batch_label = f"batch {batch_index}/{total_batches}"
        batch_range = f"{start_idx + 1}-{start_idx + len(batch)}/{total}"
        max_attempts = max(1, int(max_attempts or 1))
        for attempt in range(1, max_attempts + 1):
            batch_start = time.perf_counter()
            self._log(f"{stage_message}: starting {batch_label} items {batch_range} attempt {attempt}")
            try:
                if self.mt == 'c':
                    result = cloud_embed(self.ak, self.mn, batch)
                elif self.mt == 'v':
                    self._ensure_model()
                    result = self.md.embed(batch, model=self.mn).embeddings
                else:
                    self._ensure_model()
                    result = [x.embedding for x in self.md.embeddings.create(input=batch, model=self.mn).data]
            except Exception as exc:
                elapsed = time.perf_counter() - batch_start
                self._log(f"{stage_message}: failed {batch_label} attempt {attempt} after {elapsed:.1f}s error={exc}")
                if attempt >= max_attempts:
                    raise
                sleep_s = min(6.0, 1.5 * attempt)
                self._log(f"{stage_message}: retrying {batch_label} after {sleep_s:.1f}s")
                time.sleep(sleep_s)
                continue
            elapsed = time.perf_counter() - batch_start
            self._log(f"{stage_message}: finished {batch_label} items {batch_range} in {elapsed:.1f}s")
            return result
        raise RuntimeError(f"Unreachable retry state for {batch_label}")

    def _embed(self, texts, stage_message="Embedding papers", max_attempts=None):
        total = max(1, len(texts))
        overall_start = time.perf_counter()
        self._log(f"{stage_message}: total_items={len(texts)} scope={self.scope_key} model={self.mn}")
        # User-facing query searches should fail fast and fall back instead of
        # blocking the UI on repeated network retries. Cache build/repair stages
        # keep retries because they are long-running maintenance tasks.
        if max_attempts is None:
            max_attempts = 1 if stage_message == "Embedding query" else 3
        if self.mt == 'l':
            self._ensure_model()
            rows = []
            batch_size = 64
            total_batches = max(1, (len(texts) + batch_size - 1) // batch_size)
            for batch_index, i in enumerate(range(0, len(texts), batch_size), start=1):
                batch = texts[i:i + batch_size]
                batch_start = time.perf_counter()
                self._log(f"{stage_message}: starting batch {batch_index}/{total_batches} items {i + 1}-{i + len(batch)}/{total}")
                result = self.md.encode(batch, convert_to_numpy=True, show_progress_bar=False)
                rows.extend(result)
                done = min(i + len(batch), total)
                elapsed = time.perf_counter() - batch_start
                total_elapsed = time.perf_counter() - overall_start
                eta_seconds = (total_elapsed / done) * max(0, total - done) if done else 0.0
                eta_text = _format_eta(eta_seconds)
                self._log(f"{stage_message}: finished batch {batch_index}/{total_batches} in {elapsed:.1f}s cumulative={done}/{total} elapsed={total_elapsed:.1f}s eta={eta_text}")
                self._emit_progress(done, total, f"{stage_message}: batch {batch_index}/{total_batches} ({done}/{total}) elapsed {total_elapsed:.1f}s | ETA {eta_text}")
            self._log(f"{stage_message}: completed {total}/{total} in {time.perf_counter() - overall_start:.1f}s")
            return np.array(rows, dtype=np.float32)

        rows = []
        batch_size = 100 if self.mt == 'v' else 400
        total_batches = max(1, (len(texts) + batch_size - 1) // batch_size)
        for batch_index, i in enumerate(range(0, len(texts), batch_size), start=1):
            batch = texts[i:i + batch_size]
            result = self._remote_embed_batch(batch, batch_index, total_batches, stage_message, i, total, max_attempts=max_attempts)
            rows.extend(result)
            done = min(i + len(batch), total)
            total_elapsed = time.perf_counter() - overall_start
            eta_seconds = (total_elapsed / done) * max(0, total - done) if done else 0.0
            eta_text = _format_eta(eta_seconds)
            self._log(f"{stage_message}: progress batch {batch_index}/{total_batches} cumulative={done}/{total} elapsed={total_elapsed:.1f}s eta={eta_text}")
            self._emit_progress(done, total, f"{stage_message}: batch {batch_index}/{total_batches} ({done}/{total}) elapsed {total_elapsed:.1f}s | ETA {eta_text}")
            time.sleep(0.6)
        self._log(f"{stage_message}: completed {total}/{total} in {time.perf_counter() - overall_start:.1f}s")
        return np.array(rows, dtype=np.float32)

    def _load_cache(self):
        fast_state, fast_cached_count = _fast_exact_cache_match(self.cf, self.mf, self.jp, self.mn, self.scope_key)
        if fast_state == "exact":
            self._log(f"cache hit {self.cf}")
            return np.load(self.cf, mmap_mode="r")

        current_fingerprints = self._dataset_fingerprints()
        resolved_cache, resolved_meta, cache_state, cached_count = resolve_portable_cache(
            self.jp, self.mn, self.scope_key, current_fingerprints
        )
        self.cf, self.mf = resolved_cache, resolved_meta

        if cache_state:
            try:
                if cache_state == "exact":
                    embeddings = np.load(self.cf, mmap_mode="r")
                    self._log(f"cache hit {self.cf}")
                    self._save_meta(current_fingerprints)
                    return embeddings

                embeddings = np.load(self.cf)
                texts = [self._paper_text(paper) for paper in self.dt]

                if cache_state == "append_only":
                    self._log(f"append-only update {cached_count} -> {len(current_fingerprints)}")
                    new_embeddings = self._embed(texts[cached_count:], stage_message="Appending embeddings")
                    embeddings = np.vstack((embeddings, new_embeddings))
                    np.save(self.cf, embeddings)
                    self._save_meta(current_fingerprints)
                    return embeddings

                if cache_state == "partial":
                    self._log(f"partial cache reuse {cached_count}/{len(current_fingerprints)} from {self.cf}")
                    reused_embeddings, missing_indexes = _partial_reuse_embeddings(self.cf, self.mf, current_fingerprints)
                    if reused_embeddings is None:
                        raise RuntimeError("partial cache metadata does not match embedding rows")
                    if missing_indexes:
                        missing_texts = [texts[index] for index in missing_indexes]
                        new_embeddings = self._embed(missing_texts, stage_message="Repairing changed embeddings")
                        for row_index, embedding in zip(missing_indexes, new_embeddings):
                            reused_embeddings[row_index] = embedding
                    np.save(self.cf, reused_embeddings)
                    self._save_meta(current_fingerprints)
                    return reused_embeddings
            except Exception as exc:
                self._log(f"failed to load cache {self.cf}: {exc}")
                if cache_state in ("append_only", "partial"):
                    raise RuntimeError(
                        "Reusable embedding cache was found, but repairing the small changed subset failed. "
                        "Full-library rebuild was intentionally skipped; fix the network/API issue and retry."
                    ) from exc
        elif os.path.exists(self.cf):
            self._log("cache invalidated because paper order/content changed")

        texts = [self._paper_text(paper) for paper in self.dt]
        embeddings = self._embed(texts)
        np.save(self.cf, embeddings)
        self._save_meta(current_fingerprints)
        return embeddings

    def search(self, query, top_k=50):
        qe = np.array(self._embed([query], stage_message="Embedding query")).reshape(1, -1)
        hits = _semantic_search(qe, self.eb, top_k=top_k)
        return [{"similarity": x['score'], "paper": self.dt[x['corpus_id']]} for x in hits]

    def search_candidates(self, query, candidate_papers, top_k=50):
        candidate_papers = list(candidate_papers or [])
        if not candidate_papers:
            return []

        positions = {}
        for index, paper in enumerate(self.dt):
            positions.setdefault(_paper_match_key(paper), []).append(index)

        candidate_indexes = []
        seen_indexes = set()
        for paper in candidate_papers:
            indexes = positions.get(_paper_match_key(paper), [])
            for index in indexes:
                if index not in seen_indexes:
                    candidate_indexes.append(index)
                    seen_indexes.add(index)
                    break

        if not candidate_indexes:
            return []

        qe = np.array(self._embed([query], stage_message="Embedding query")).reshape(1, -1)
        subset_embeddings = self.eb[candidate_indexes]
        hits = _semantic_search(qe, subset_embeddings, top_k=min(int(top_k), len(candidate_indexes)))
        return [
            {"similarity": hit["score"], "paper": self.dt[candidate_indexes[hit["corpus_id"]]]}
            for hit in hits
        ]
