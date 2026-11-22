import { test } from 'node:test';
import assert from 'node:assert/strict';
import { appendFile, chmod, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createHash } from 'node:crypto';
import { SEMANTIC_CONFIG, chunkId, chunkSource, computeLinks, configFromEnv, decideSemanticStart, isChunkable, semanticConfigHash,
  semanticContentHash, type Chunk } from '../ingestion/chunks/chunker.ts';
import { EmbeddingReader, pythonEmbedder, readEmbeddingRows, validateEmbedding, type EmbeddingRow } from '../ingestion/embeddings/run-embedder.ts';
import { validateSearch } from '../retrieval/query/neo4j-search.ts';

const lines = (n: number, text = 'x = 1') => Array.from({ length: n }, () => text).join('\n');
const SNAP = '["repo","' + 'a'.repeat(40) + '"]';

test('chunk windows: boundaries, trailing newline, line numbers', () => {
  const at = (n: number) => chunkSource(SNAP, [{ path: 'a.py', text: lines(n) + '\n' }]).map(c => [c.startLine, c.endLine]);
  assert.deepEqual(at(150), [[1, 150]]);
  assert.deepEqual(at(151), [[1, 150], [151, 151]]);
  assert.deepEqual(at(300), [[1, 150], [151, 300]]);
  assert.deepEqual(at(301), [[1, 150], [151, 300], [301, 301]]);
  assert.deepEqual(chunkSource(SNAP, [{ path: 'a.py', text: 'a\r\nb\rc\n' }]).map(c => c.endLine), [3]);
});
test('whitespace-only windows are skipped without renumbering later windows', () => {
  const text = lines(150) + '\n' + Array.from({ length: 150 }, () => '   ').join('\n') + '\n' + lines(5);
  assert.deepEqual(chunkSource(SNAP, [{ path: 'a.py', text }]).map(c => c.startLine), [1, 301]);
  assert.deepEqual(chunkSource(SNAP, [{ path: 'a.py', text: '\n\n  \n' }, { path: 'b.py', text: '' }]), []);
});
test('only configured source files are chunked', () => {
  for (const ok of ['a.ts', 'a.tsx', 'a.js', 'a.jsx', 'a.py', 'src/deep/x.d.ts', 'a.go', 'A.java', 'a.c', 'a.h', 'a.cpp', 'a.rb', 'a.rs']) assert.ok(isChunkable(ok), ok);
  for (const no of ['a.md', 'a.json', 'a.min.js', 'node_modules/p/i.js', 'src/node_modules/p/i.js', 'a.yaml']) assert.ok(!isChunkable(no), no);
  const chunks = chunkSource(SNAP, [{ path: 'b.py', text: 'b' }, { path: 'a.py', text: 'a' }, { path: 'a.min.js', text: 'z' }]);
  assert.deepEqual(chunks.map(c => c.file), ['a.py', 'b.py']);
});
test('long chunks are cut and flagged, never split in a surrogate pair', () => {
  const [plain] = chunkSource(SNAP, [{ path: 'a.py', text: 'y'.repeat(9000) }]);
  assert.equal(plain.charCount, 9000); assert.equal(plain.embeddedChars, 8000);
  assert.ok(plain.truncated); assert.equal(plain.text.length, 8000);
  const [pair] = chunkSource(SNAP, [{ path: 'a.py', text: 'y'.repeat(7999) + '😀' + 'z' }]);
  assert.equal(pair.embeddedChars, 7999); assert.ok(pair.truncated);
  const [short] = chunkSource(SNAP, [{ path: 'a.py', text: 'short' }]);
  assert.equal(short.truncated, false); assert.equal(short.embeddedChars, short.charCount);
});
test('chunk count bound is enforced and chunk ids have the documented shape', () => {
  assert.throws(() => chunkSource(SNAP, [{ path: 'a.py', text: lines(400) }], SEMANTIC_CONFIG, { maxFiles: 10, maxFileBytes: 10, maxChunks: 2 }), /Chunk count/);
  assert.equal(chunkId('S', 'src/a.py', 151), 'S::chunk::src/a.py::151');
  assert.equal(chunkSource(SNAP, [{ path: 'a.py', text: lines(200) }])[1].id, `${SNAP}::chunk::a.py::151`);
});
test('semantic start decision: complete layers are immutable, incomplete ones may restart under a new config', () => {
  const config = semanticConfigHash(SEMANTIC_CONFIG);
  const other = semanticConfigHash({ ...SEMANTIC_CONFIG, chunkLines: 100 });
  assert.notEqual(config, other);
  assert.notEqual(config, semanticConfigHash({ ...SEMANTIC_CONFIG, modelRevision: 'b'.repeat(40) }));
  assert.equal(decideSemanticStart({ status: null, configHash: null, contentHash: null }, config, 'c1'), 'new');
  assert.equal(decideSemanticStart({ status: 'building', configHash: config, contentHash: 'c1' }, config, 'c1'), 'resume');
  assert.equal(decideSemanticStart({ status: 'ready', configHash: config, contentHash: 'c1' }, config, 'c1'), 'unchanged');
  assert.equal(decideSemanticStart({ status: 'building', configHash: other, contentHash: 'c1' }, config, 'c1'), 'restart');
  assert.throws(() => decideSemanticStart({ status: 'ready', configHash: other, contentHash: 'c1' }, config, 'c1'), /semantic config conflict/);
  assert.throws(() => decideSemanticStart({ status: 'ready', configHash: config, contentHash: 'c2' }, config, 'c1'), /semantic content conflict/);
  assert.throws(() => decideSemanticStart({ status: 'building', configHash: config, contentHash: 'c2' }, config, 'c1'), /semantic content conflict/);
});
test('token cap: default config hash is pinned, a lower cap changes it, env is validated', () => {
  const pinned = createHash('sha256').update(JSON.stringify([SEMANTIC_CONFIG.model, SEMANTIC_CONFIG.modelRevision, SEMANTIC_CONFIG.codeRevision,
    768, 150, 8000, 6000, [...SEMANTIC_CONFIG.extensions].sort()])).digest('hex');
  const legacy = pinned;
  assert.equal(semanticConfigHash(SEMANTIC_CONFIG), pinned);
  assert.notEqual(semanticConfigHash({ ...SEMANTIC_CONFIG, maxEmbedTokens: 2048 }), legacy);
  assert.notEqual(semanticConfigHash({ ...SEMANTIC_CONFIG, maxEmbedTokens: 2048 }), semanticConfigHash({ ...SEMANTIC_CONFIG, maxEmbedTokens: 1024 }));
  assert.equal(configFromEnv({}).maxEmbedTokens, 8192);
  assert.equal(configFromEnv({ EMBED_MAX_TOKENS: '2048' }).maxEmbedTokens, 2048);
  for (const bad of ['abc', '64', '8193', '20.5', '-1']) assert.throws(() => configFromEnv({ EMBED_MAX_TOKENS: bad }), /EMBED_MAX_TOKENS/, bad);
});
test('content hash depends on layout and links but not chunk order or text', () => {
  const chunks = chunkSource(SNAP, [{ path: 'a.py', text: lines(200) }, { path: 'b.py', text: 'b' }]);
  const links = computeLinks(chunks, [{ localId: 'f', sourceFile: 'a.py', sourceLocation: 'L3' }]);
  const base = semanticContentHash(SEMANTIC_CONFIG, chunks, links);
  assert.equal(semanticContentHash(SEMANTIC_CONFIG, [...chunks].reverse(), links), base);
  assert.notEqual(semanticContentHash(SEMANTIC_CONFIG, chunks, []), base);
  assert.notEqual(semanticContentHash(SEMANTIC_CONFIG, chunks.slice(1), links), base);
});
test('links: inside, boundaries, other file, malformed locations', () => {
  const chunks = chunkSource(SNAP, [{ path: 'a.py', text: lines(300) }, { path: 'b.py', text: lines(10) }]) as Chunk[];
  const entity = (localId: string, sourceFile: string, sourceLocation: string) => ({ localId, sourceFile, sourceLocation });
  const links = computeLinks(chunks, [entity('mid', 'a.py', 'L75'), entity('first', 'a.py', 'L1'), entity('end', 'a.py', 'L150'),
    entity('next', 'a.py', 'L151'), entity('last', 'a.py', 'L300'), entity('past', 'a.py', 'L301'), entity('zero', 'a.py', 'L0'),
    entity('other', 'b.py', 'L5'), entity('wrongfile', 'c.py', 'L5'), entity('range', 'a.py', 'L1-5'), entity('empty', 'a.py', ''),
    entity('nofile', '', 'L5')]);
  const where = (id: string) => links.filter(l => l.localId === id).map(l => l.chunkId.split('::').pop());
  assert.deepEqual(where('mid'), ['1']); assert.deepEqual(where('first'), ['1']); assert.deepEqual(where('end'), ['1']);
  assert.deepEqual(where('next'), ['151']); assert.deepEqual(where('last'), ['151']);
  assert.deepEqual(where('other'), ['1']);
  for (const none of ['past', 'zero', 'wrongfile', 'range', 'empty', 'nofile']) assert.deepEqual(where(none), [], none);
  assert.equal(links.filter(l => l.chunkId.includes('b.py')).length, 1);
});
test('embedding validation rejects wrong dimension, non-finite numbers and malformed rows', () => {
  const vec = (n: number, v = 0.5) => Array.from({ length: n }, () => v);
  assert.equal(validateEmbedding({ id: 'a', embedding: vec(768) }, 768).id, 'a');
  assert.throws(() => validateEmbedding({ id: 'a', embedding: vec(767) }, 768), /dimension 767/);
  assert.throws(() => validateEmbedding({ id: 'a', embedding: vec(768, NaN) }, 768), /non-finite/);
  assert.throws(() => validateEmbedding({ id: 'a', embedding: vec(768, Infinity) }, 768), /non-finite/);
  assert.throws(() => validateEmbedding({ id: 'a', embedding: [...vec(767), '1'] }, 768), /non-finite/);
  assert.throws(() => validateEmbedding({ embedding: vec(768) }, 768), /Malformed/);
  assert.deepEqual(validateEmbedding({ id: 'a', embedding: vec(3), tokens: 7, tokenTruncated: true }, 3), { id: 'a', embedding: vec(3), tokens: 7, tokenTruncated: true });
  assert.throws(() => validateEmbedding({ id: 'a', embedding: vec(3), tokenTruncated: 'yes' }, 3), /truncation flag/);
  assert.throws(() => validateEmbedding({ id: 'a', embedding: vec(3), tokens: -1 }, 3), /token count/);
  assert.throws(() => validateEmbedding(null, 768), /Malformed/);
});
test('embedding file: count mismatch, unknown and duplicate ids, partial last line', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'embed-test-'));
  const row = (id: string, n = 3) => JSON.stringify({ id, embedding: Array.from({ length: n }, () => 0.25) });
  const read = async (content: string, ids: string[], allowPartial: boolean) => {
    const file = join(dir, 'out.jsonl'); await writeFile(file, content);
    const got: string[] = [];
    const count = await readEmbeddingRows(file, new Set(ids), 3, { allowPartial }, async rows => { got.push(...rows.map(r => r.id)); });
    return { count, got };
  };
  try {
    assert.deepEqual(await read(row('a') + '\n' + row('b') + '\n', ['a', 'b'], false), { count: 2, got: ['a', 'b'] });
    await assert.rejects(read(row('a') + '\n', ['a', 'b'], false), /count mismatch: expected 2, got 1/);
    await assert.rejects(read(row('a') + '\n' + row('z') + '\n', ['a', 'b'], false), /unrequested/);
    await assert.rejects(read(row('a') + '\n' + row('a') + '\n', ['a', 'b'], false), /Duplicate/);
    await assert.rejects(read(row('a', 2) + '\n', ['a'], false), /dimension 2/);
    await assert.rejects(read('{"id":"a","embedding":[1e999,0,0]}\n', ['a'], false), /non-finite/);
    await assert.rejects(read(row('a') + '\n{"id":"b","emb', ['a', 'b'], false), SyntaxError);
    assert.deepEqual(await read(row('a') + '\n{"id":"b","emb', ['a', 'b'], true), { count: 1, got: ['a'] });
    await assert.rejects(read('{"id":"a","emb\n' + row('b') + '\n', ['a', 'b'], true), SyntaxError);
  } finally { await rm(dir, { recursive: true, force: true }); }
});
test('search validation bounds topK and query and rejects unknown arguments', () => {
  const ok = validateSearch({ repoId: 'r', query: 'where is auth' });
  assert.equal(ok.topK, 8);
  assert.throws(() => validateSearch({ repoId: 'r', query: 'q', topK: 0 }), /topK/);
  assert.throws(() => validateSearch({ repoId: 'r', query: 'q', topK: 26 }), /topK/);
  assert.throws(() => validateSearch({ repoId: 'r', query: 'q'.repeat(1001) }), /query/);
  assert.throws(() => validateSearch({ repoId: 'r', query: 'q', cypher: 'MATCH (n) RETURN n' }), /Unknown/);
  assert.throws(() => validateSearch({ repoId: 'r', query: 'q', commitSHA: 'abc' }), /commitSHA/);
});
test('the image bakes the same pinned revisions the code uses, and the embedder runs offline', async () => {
  const dockerfile = await readFile(new URL('../../Dockerfile.base', import.meta.url), 'utf8');
  assert.ok(dockerfile.includes(SEMANTIC_CONFIG.modelRevision)); assert.ok(dockerfile.includes(SEMANTIC_CONFIG.codeRevision));
  assert.ok(dockerfile.includes(SEMANTIC_CONFIG.model)); assert.match(dockerfile, /HF_HUB_OFFLINE=1/);
  const runner = await readFile(new URL('../ingestion/embeddings/run-embedder.ts', import.meta.url), 'utf8');
  assert.match(runner, /HF_HUB_OFFLINE: '1'/);
});
test('incremental reader hands over rows as lines complete and keeps a half-written line for later', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'embed-tail-'));
  const file = join(dir, 'out.jsonl');
  const row = (id: string) => JSON.stringify({ id, embedding: [0.1, 0.2, 0.3] });
  const got: string[] = [];
  try {
    await writeFile(file, '');
    const reader = new EmbeddingReader(file, new Set(['a', 'b', 'c']), 3, async rows => { got.push(...rows.map(r => r.id)); });
    await reader.drain({ final: false, allowPartial: true, minBatch: 1 });
    assert.deepEqual(got, []);
    await appendFile(file, row('a') + '\n' + row('b').slice(0, 10));
    await reader.drain({ final: false, allowPartial: true, minBatch: 1 });
    assert.deepEqual(got, ['a']);
    await appendFile(file, row('b').slice(10) + '\n' + row('c'));
    await reader.drain({ final: false, allowPartial: true, minBatch: 1 });
    assert.deepEqual(got, ['a', 'b']);
    await reader.drain({ final: true, allowPartial: false, minBatch: 1 });
    assert.deepEqual(got, ['a', 'b', 'c']); assert.equal(reader.count, 3);
  } finally { await rm(dir, { recursive: true, force: true }); }
});
test('embedder runner saves rows while the process runs and keeps completed rows when it fails', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'embed-run-'));
  const script = join(dir, 'fake-python.sh');
  const config = { ...SEMANTIC_CONFIG, dimension: 3 };
  const items = ['one', 'two', 'three', 'four'].map(id => ({ id, text: id }));
  const write = (fail: boolean) => writeFile(script, `#!/bin/sh
while [ $# -gt 0 ]; do case "$1" in --in) IN="$2";; --out) OUT="$2";; --meta) META="$2";; esac; shift; done
N=0
[ -n "$FAKE_COUNT" ] && echo run >> "$FAKE_COUNT"
for ID in $(grep -o '"id":"[a-z]*"' "$IN" | cut -d'"' -f4); do
  echo "{\\"id\\":\\"$ID\\",\\"embedding\\":[0.1,0.2,0.3]}" >> "$OUT"; N=$((N+1))
  [ "$N" = 2 ] && [ "${fail ? 'yes' : 'no'}" = yes ] && { sleep 1; exit 3; }
  sleep 1
done
echo '{"model":"m","modelRevision":"r","codeRevision":"c","dimension":3,"count":4,"loadSeconds":0,"embedSeconds":0,"torch":"t","transformers":"x","peakRssMb":1}' > "$META"
`);
  try {
    await write(false); await chmod(script, 0o755);
    const times: number[] = []; const ids: string[] = [];
    const started = Date.now();
    const meta = await pythonEmbedder({ python: script, config, saveIntervalMs: 200 })(items, async rows => { times.push(Date.now() - started); ids.push(...rows.map((r: EmbeddingRow) => r.id)); });
    assert.deepEqual(ids, ['one', 'two', 'three', 'four']); assert.equal(meta?.count, 4);
    assert.ok(times.length >= 3, `rows arrived in ${times.length} batches`);
    assert.ok(times[0] < 3000, 'first rows were saved before the process finished');
    process.env.FAKE_COUNT = join(dir, 'runs.txt');
    const segIds: string[] = [];
    await write(false);
    const segMeta = await pythonEmbedder({ python: script, config, saveIntervalMs: 200, segmentSize: 2 })(items, async rows => { segIds.push(...rows.map(r => r.id)); });
    assert.deepEqual(segIds, ['one', 'two', 'three', 'four']);
    assert.equal((await readFile(process.env.FAKE_COUNT, 'utf8')).trim().split('\n').length, 2, 'one child process per segment of 2');
    assert.equal(segMeta?.count, 8);
    delete process.env.FAKE_COUNT;
    await write(true);
    const kept: string[] = [];
    await assert.rejects(pythonEmbedder({ python: script, config, saveIntervalMs: 200 })(items, async rows => { kept.push(...rows.map(r => r.id)); }), /exited with code 3/);
    assert.deepEqual(kept, ['one', 'two']);
  } finally { await rm(dir, { recursive: true, force: true }); }
});
test('character budget: dense lines close a chunk before the budget, every line appears once, lines are never split', () => {
  const dense = Array.from({ length: 100 }, (_, i) => `${i}`.padEnd(200, 'x'));
  const chunks = chunkSource(SNAP, [{ path: 'a.py', text: dense.join('\n') + '\n' }]);
  assert.ok(chunks.length > 1);
  for (const c of chunks) assert.ok(c.charCount <= SEMANTIC_CONFIG.maxChunkChars, `chunk ${c.startLine}-${c.endLine} is ${c.charCount} chars`);
  assert.equal(chunks[0].startLine, 1);
  assert.equal(chunks[chunks.length - 1].endLine, 100);
  for (let k = 1; k < chunks.length; k++) assert.equal(chunks[k].startLine, chunks[k - 1].endLine + 1);
  assert.ok(chunks.every(c => !c.truncated));
});
test('languages: C, C++, Go, Java, Ruby and Rust are chunked', () => {
  for (const path of ['a.c', 'a.h', 'a.cpp', 'a.go', 'A.java', 'a.rb', 'a.rs']) {
    assert.equal(chunkSource(SNAP, [{ path, text: 'x = 1\n' }]).length, 1, path);
  }
});
