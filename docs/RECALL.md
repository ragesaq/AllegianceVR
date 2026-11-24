# Recall: word search over the repository's notes

`tools/recall.py` finds the passages in this repository's notes that
answer a question, including questions worded differently from the notes.
It is the word floor of the design in
[`proposals/2026-11-22-recall-and-memory-direction.md`](proposals/2026-11-22-recall-and-memory-direction.md):
word search with a glossary, match labels and each memory entry's class,
and an optional vector index on the same passages
([Vectors](#vectors)), switched on per working tree.

```sh
python3 tools/recall.py search "how do I prove a search works"
python3 tools/recall.py search --json "who may approve a canonical entry"
python3 tools/recall.py search --no-vectors "..."   # words only, reads no model
python3 tools/recall.py index            # build or update the cache; report coverage
python3 tools/recall.py check-glossary   # every glossary target must be real
python3 tools/recall.py enable-vectors --model-from DIR   # optional (Vectors)
python3 tools/recall.py check-vectors    # the paraphrase canary
```

On native Windows the command is `python`. Word search needs only
Python's standard library and Git; vectors need more (see Vectors). It
runs from the working-tree root: a folder that is not the top of a Git
working tree is refused before anything is written.

## What a hit is

A hit is a lead, never evidence. Open the file at the path and line span
it prints, read it, and cite the file. A claim that rests on a hit carries
the file's class, as it would without the search.

An empty result means no word matched. It never means the answer is
absent. Before recording an absence, search for the canary token in
`memory/CANARY.md` by the same method and name the surface you searched
([`MEMORY_PROTOCOL.md`](MEMORY_PROTOCOL.md) rules 6 and 8).

Search in three passes when the first one misses:

1. the asker's words and the repository's own term for the thing;
2. a short list of keywords and paraphrases;
3. terms taken from the first hits.

## What it searches

The working-tree bytes of tracked Markdown files under `AGENTS.md`,
`memory/`, `knowledge/` and `docs/`, uncommitted edits included. It
follows no symlink or junction, skips files that are not valid UTF-8 and
says so, and reports two paths that differ only by case or Unicode form
as a collision. `RECALL_GLOSSARY.json` is never searched.

Every read, of a note, the glossary, the map or the catalog, refuses a
path that runs through a link. On Linux and macOS each folder on the path
is opened in turn with links refused; on Windows each folder and the file
are checked before the open. The people and tools that write the working
tree are trusted: the tool guards against a link that is in the tree, not
against someone swapping one in while a search runs. Someone who can do
that can edit the notes themselves.

Files are split into passages at headings, at most about 2,000 characters
each, on line boundaries. A single line longer than that is a passage of
its own, kept whole, so a locator is always a line span. That passage can
be larger than the cap; the page still shows at most eight lines and 480
characters of it (operator, 2026-11-22: accepted as an exception).

## Every hit says how it was found

Hits are grouped by **match label**, strongest first:

| Label | Evidence in the returned passage |
|---|---|
| `exact` | A registered identifier from the query as a whole token in the passage: a memory entry id, a work-map node id, a tracked path, a compound front-matter key such as `granted-by`, or an entity id or alias from `catalog/ENTITIES.json`. `mem-0070` is not an exact hit for `mem-007`. A one-word key such as `class` is an ordinary word too, so it is exact only when the query writes it as a key (`class:`). A tracked file at the root with no folder or extension counts only when its name has a capital (`LICENSE`, `Makefile`). A query that is a tracked path also returns that file. A tracked path that holds a space is recognized when it is the whole query or is written in double quotes or backticks (`"docs/two words.md"`). The query and each of its words are tried as written first: when `.github/config.md` is registered, that query names it, never `github/config.md`, and `github/config.md` is not an exact hit inside `.github/config.md`. A word that is not registered as written is tried again with its edge punctuation trimmed, so `.github/config.md` written where only `github/config.md` is registered finds the undotted path. Exact matches are found by reading every searched file as written, not through the index, so no limit and no difference in how the index splits words hides one. |
| `alias` | A glossary target for a word in the query. The output names the word and the target. When more than 500 passages hold a target, a note says how many. |
| `words` | At least one stemmed word of the query, other than common words such as "the" and "how". Ranking reads the 500 best matches; when more matched, a note says how many. |
| `meaning` | None of the above; the vectors returned it (only where [vectors](#vectors) are on). A passage a link also reaches is still `meaning`, and lists the link. |
| `linked` | None of the above; reached only by one typed link (`superseded-by`, `supersedes`, `contradicts`) from a memory-entry hit. The output names the source hit and the link. |

An `alias` or `words` match found only in the file's path or a heading
above the passage, not in the passage itself, says "path or heading
only" in its label. When the passage itself also holds a match of the
same label, the label names that one.

A passage that holds evidence of its own takes the label of that
evidence, however else it was reached. A hit that a typed link also
reaches keeps its own label and lists the link and its source, and a
linked lead reached from several hits lists each of them. `meaning` and
`linked` hits come after the others, headed as related context,
`meaning` first.

## Class, and where status lives

For a governed memory entry (`memory/mem-NNN-*.md`), each hit also shows
its **class**: the class its front matter declares, demoted to `inferred`
for an agent-store entry read in the repository (`effective_class()` in
`tools/check_tracking.py`). The front matter is read by `check_memory.py`'s
own parser (`split_front_matter()`). The class is `unknown` when that
parser reports any problem with the block (a field written twice, say),
when the entry declares no class `check_memory.py` knows (the line is
missing or blank, or holds another value), or when more than one tracked file uses the entry's id, counting files the
search had to skip. Then neither file's fields stand for the id, and no
link reaches either file through it. Every other file is `unclassed`; a
`class:` line in prose never counts.

Search does not say whether an entry is current, expired, superseded or
contradicted, and does not check its grant or evidence. That is
`python3 tools/check_memory.py`'s answer (with `tools/check_tracking.py`
for validity windows). Run it before relying on an entry a search found.

The label says how a hit was found. The class says what the entry claims
to be, not that its content holds. A link or a neighbour never lends a
class.

## What the output reports

Every answer reports three things apart:

- **capability**: the word index (SQLite FTS5 with Porter stemming), or
  the plain scan with lighter suffix stemming where the interpreter's
  SQLite lacks the exact FTS5 table this needs, and why; then whether
  vectors are on (the model, and how many passages are embedded) or off,
  and why;
- **coverage**: files and passages searched, files skipped and why,
  collisions, what the recheck after the walk saw, and the vector
  counts;
- **results**: hits by label, or none.

The page is bounded: at most 10 primary and 5 related passages, two
passages per file within a label, eight lines per passage, and about
2,500 tokens for the whole page, the query echo, coverage, notes and
footer included (long values there are shortened). Within a label, files
take turns in rank order. What the caps leave out is counted per label,
with up to five omitted paths named. No scores are printed. These caps
are development settings; the calibration run in an applied project may
change them.

`--json` returns the same passages as the page, in the same order, and
the coverage in full (every skipped file, every changed path).

## Keeping it current

There is no service. Each search walks the declared files, hashes each
one, updates the index for what changed, then lists and hashes them again.
If anything moved, including a skipped file that became readable, it
walks again, up to three walks, and then answers with the changed paths
named. The coverage line says "no change detected
on recheck" or names the changes; a recheck can miss an edit that lands
and is reverted between two reads.

A search reads the index in one read transaction, opened after its own
update and compared with the files it read. If another search changed
the index in between, at every one of the three walks, the answer comes
from a plain scan of the files this search read, and the capability line
says so.

## The cache

The index lives in `.hyperbench-recall/` at the working-tree root. It is
derived from the files, built only by this tool, and can be deleted and
rebuilt at any time. The tool itself never deletes it. A cache whose
schema objects are not exactly this release's (another schema, a table
or index missing or defined another way, an object the tool did not
create, or shadow tables another SQLite version laid out) is rebuilt in place
inside one write transaction, and the output says so. A cache that cannot
be read as this tool's database, or cannot be opened or written, is left
as it is: a search answers by a plain scan and says why, and `index`
fails with the reason. Damage SQLite finds only later, while syncing or
answering, is handled the same way: the search is answered once more by
a plain scan. A busy cache is retried for ten seconds, then
reported. One writer at a time, in SQLite transactions, so a reader sees
one whole generation. The tool refuses to write through the folder or any
of its files when it is a link or not a plain file, and refuses a cache
that Git tracks.

The word table is contentless: no column returns the text. That is not
the same as unreadable, because SQLite can still list each passage's
stemmed words in order. So the cache is treated as holding the
repository's content:

- `.gitignore` lists it, and the tool writes a `.gitignore` holding
  exactly `*` inside the folder, so Git ignores it even where the root
  file predates this tool. An existing inner file with anything else, or
  empty (an interrupted first run), is never rewritten; the search scans
  instead and says to remove the folder. Before SQLite opens anything,
  Git must report the database as ignored;
- `tools/export_program.sh` excludes it, and `tools/check_transfer.py`
  rejects an export that holds it;
- `tools/repo_copy.py` and `tools/make_distribution.py` skip it;
- `tools/check_memory.py` rejects any evidence path in it, anchored or
  not, however it is spelled, including one through a folder that is the
  cache under another name. A chain of links that reaches the cache only
  through a link placed inside it is not detected. Nothing writes links
  there, and the people and tools that write the working tree are
  trusted; if the cache is removed, the check reports that evidence as
  missing.

Where vectors are enabled the folder also holds the model (`model/`),
the record `vectors.json`, and the vectors in the same database. The
same rules cover all of them: they are ignored, never exported, never
committed, and never evidence.

It is never sent off the host.

## The glossary

`RECALL_GLOSSARY.json` maps everyday words to this repository's terms.
It only widens a search; it changes no fact. It is separate from the
catalog: `catalog/VOCABULARY.json` is the closed ontology of fact types
and predicates, and aliases in `catalog/ENTITIES.json` resolve facts
before they are compared, so an everyday word added there would change
how facts resolve.

```json
{"words": ["who may approve", "sign-off"], "terms": ["granted-by", "canonical"]}
```

A query containing one of the `words` (as a whole phrase, ignoring case
and simple plural or tense endings) also searches for each of the
`terms`, and those hits are labelled `alias`.

`check-glossary` passes a target only when it is a type or predicate name
in `catalog/VOCABULARY.json`, an entity id in `catalog/ENTITIES.json`, or
a whole search term, tokenized and stemmed as word search does it, in a
searchable source file. The glossary is never a source, so a typo that
occurs only there fails. Run it after editing the glossary, and record
the result in the PR.

A project owns its glossary. A seeded or updated repository takes the
hub's file as a seed and then adds the words its own people ask with
([`UPDATING.md`](UPDATING.md)).

## Vectors

Vectors are optional. They add hits that share no word with the question,
and they reorder hits that do. Word search works the same without them,
and every host must keep working without them.

### Switching them on

Vectors are switched on for one working tree, on purpose:

```sh
python3 tools/recall.py enable-vectors --model-from DIR   # DIR holds the model files
```

The tool installs nothing and makes no network access. The packages and
the model come first, from the person or from their assistant with the
person's go-ahead; the next two sections say how.

#### Installing the packages

Vectors need Python 3.10 or later with the packages `numpy` and
`model2vec` (which brings `tokenizers`, `safetensors` and
`huggingface-hub`; no `torch`). Installing those packages is installing a
new tool, so ask the program lead first
([`GROUND_RULES.md`](../GROUND_RULES.md) rule 7); without approval, stop
here and keep word search. With approval, install them into the Python
that runs the tool, for example a virtual environment. Each line below
is one command; VENV is a new folder outside every repository.

POSIX shell:

```sh
python3 -m venv VENV
VENV/bin/python -m pip install numpy model2vec
```

Windows PowerShell:

```powershell
python -m venv VENV
VENV\Scripts\python.exe -m pip install numpy model2vec
```

Then run every `recall.py` command with that environment's Python
(`VENV/bin/python`, or `VENV\Scripts\python.exe`). A Python without the
packages answers by words alone, and its capability line says why. They
were tested with Python 3.14, `numpy` 2.5 and `model2vec` 0.10 on
Windows.

#### Getting the model

The model is pinned: `minishlab/potion-base-8M` at revision
`bf8b056651a2c21b8d2565580b8569da283cab23`, a static embedding model of
about 30 MB with 256 dimensions. Only three of its files are used:
`config.json`, `model.safetensors` and `tokenizer.json`. They are public,
so no account or token is needed. Fetching them is a download from
huggingface.co, so it needs the same go-ahead as the packages.

Fetch them once into DIR, a new, empty folder outside every repository.
The hub's command-line tool, `hf`, comes with `huggingface-hub`, so it is
in the virtual environment above. Each block is one command.

POSIX shell:

```sh
VENV/bin/hf download minishlab/potion-base-8M config.json model.safetensors tokenizer.json --revision bf8b056651a2c21b8d2565580b8569da283cab23 --local-dir DIR
```

Windows PowerShell:

```powershell
VENV\Scripts\hf.exe download minishlab/potion-base-8M config.json model.safetensors tokenizer.json --revision bf8b056651a2c21b8d2565580b8569da283cab23 --local-dir DIR
```

Any HTTPS client that follows redirects works too, one file at a time,
from these addresses:

```text
https://huggingface.co/minishlab/potion-base-8M/resolve/bf8b056651a2c21b8d2565580b8569da283cab23/config.json
https://huggingface.co/minishlab/potion-base-8M/resolve/bf8b056651a2c21b8d2565580b8569da283cab23/model.safetensors
https://huggingface.co/minishlab/potion-base-8M/resolve/bf8b056651a2c21b8d2565580b8569da283cab23/tokenizer.json
```

For example, after `mkdir DIR`, run for each file
`curl -fL -o DIR/config.json <address>` (`curl.exe` in Windows
PowerShell), with that file's name and address.

Then run `enable-vectors --model-from DIR` with the environment's
Python, for example `VENV/bin/python tools/recall.py enable-vectors
--model-from DIR` (`VENV\Scripts\python.exe` on Windows). It checks each file's size
and SHA-256 against the pin (`MODEL_FILES` in `tools/recall_vectors.py`)
and refuses any file that differs, so a wrong revision, a partial
download or a changed file stops there. Other entries in DIR, such as
the `.cache/` folder that `hf` writes there, are ignored.

Do not point `--model-from` at the hub's own cache (a
`snapshots/<revision>/` folder): its files are usually links to the
cache's blobs, and `enable-vectors` refuses links. Use `--local-dir` as
above.

`enable-vectors` copies the files into this worktree's cache. Keep DIR to
enable other worktrees on the same host, or delete it once the command
has passed.

#### What `enable-vectors` does

In order, `enable-vectors --model-from DIR`:

1. checks the Python version and the packages;
2. places the pinned files in `.hyperbench-recall/model/` from DIR, and
   refuses any file whose size or SHA-256 differs from the pin. DIR and
   its three files must not be links; the folders above it, which the
   person names, are not checked, since what decides is the pinned size
   and hash of each file;
3. builds the word index and embeds every passage;
4. runs the paraphrase canary (below);
5. only when the canary passed, records the model, revision and file
   hashes in `.hyperbench-recall/vectors.json`. That record is what
   switches vectors on.

A run that fails at any step exits non-zero and writes no record: a
worktree without one stays off, and a record it already had is left as
it was. The command says only that; the next search says whether
vectors are on, since a failed run may already have put the pinned
files in place of a damaged model folder. The model line it prints names
the model, the revision and whether the files were copied from an
offline copy or were already in place, never a local path, so it can be
pasted into a pull request.

After that a search uses the vectors with no flag.
`search --no-vectors` and `index --no-vectors` switch them off for one
command and then touch no vector record and no model. A model folder found
anywhere else, or packages another project installed, never switch
vectors on. A model kept outside the working tree also needs the program
lead's approval first (rule 6).

Vectors are off, with the reason on the capability line, when:

- the worktree has no record (`not enabled in this worktree`);
- the record names another model or revision than this release pins;
- the packages are missing or the Python is older than 3.10;
- a model file is missing, a link, unreadable, or does not match the pin.
  Every search reads the three files once, checks their sizes and hashes,
  and builds the model from those same bytes; it opens no other file (no
  model card) and never reads them again by path;
- the search uses the plain scan: vectors are stored in the word index;
- the model fails while embedding passages or the query (the reason is
  named).

Word search still answers in every one of these cases. A stored vector
that is damaged (the wrong length, or a value that is not a number) is
not used, counts as not embedded, and is embedded again when the cache
is next written. A query or passage the model maps to the zero vector
has no direction, so it ranks nothing and is never ranked: an empty
query gets no `meaning` hits.

### How they rank

Each passage is embedded once, from its path and heading trail followed
by its text. A vector is stored under its **computation key**: the
SHA-256 of that exact text together with the model, revision, file
hashes, backend, prefixes, chunker version and length cap. A rename or
a changed heading changes what the model read, so it gets a new vector.
Two identical passages may share a vector, never a locator: every hit
still comes from the file's bytes as this search read them. Vectors are
a cache that can always be computed again. A search walks the files
once, or again when they or the index changed while it read them. A walk whose own
word sync changed nothing drops the vectors no passage of that walk
uses, while the index still holds its files. Until such a walk runs,
unused vectors stay: a walk that changes the word index adds vectors for
new passages, as far as the embedding budget reaches, and drops none,
and every walk with vectors on reads the whole vector table. This is
accepted as the cost of never dropping a vector during a change: the
next walk that changes nothing, in the same search or a later one,
brings the table back to the vectors its passages use. When searches
overlap, one can drop a vector
another search's newer files need. A later search that reads those
files and has budget left embeds it again; until then the capability
line counts that passage as not embedded and words answer for it. A
search that finds another search has moved the index writes no vectors
and walks again.

A query is embedded and compared with every embedded passage by cosine
similarity. The 30 nearest form the vector list. Then:

- a passage in the vector list that holds no evidence of its own is a
  `meaning` hit, shown as related context after the primary group and
  before `linked`. A passage a link also reaches is still `meaning`, and
  lists the link. For each passage in the vector list, evidence is also
  tested on the passage itself, by the index's own matcher, so one
  beyond the 500 best matches of a word or alias list is still labelled
  by its strongest evidence (alias before words, a body witness before
  metadata), never `meaning`. That test sets the label only: the hit's
  routes and its place in its group come from the lists that returned
  it. One the word list returned keeps the rank the word list gave it
  when its evidence moves it up to `alias`; one only the vector list
  returned has its vector rank and no word rank;
- a passage that holds evidence keeps its label. The page notes "found
  by words, vectors", and JSON lists each hit's `routes`;
- within the `alias` and `words` groups, the word order and the vector
  order merge by weighted reciprocal rank fusion: each list adds
  `weight / (60 + rank)` to the hits it returned, with both weights 1.
  A hit's word rank is the rank the group's own list (glossary for
  `alias`, words for `words`) gave it, or the word list's rank for a hit
  moved up from `words`; it is counted once. Scores are compared
  exactly, as fractions. Ties go to the lower word rank, then the lower
  vector rank, then the order the hits were found; a hit with no word
  rank follows the word hits it ties with.
  The `exact` group is never reordered, and no label changes;
- links start only from `exact`, `alias` and `words` hits, never from a
  vector neighbour.

The vector list is never empty while the query and at least one
embedded passage have a direction (a vector that is not zero): vectors
always return neighbours. So a `meaning` hit says only that the model
judged the passage close. It is the weakest lead, and the page says so.
No scores are printed.

The list size, the weights and the 60 are development settings. The
calibration run in an applied project sets them and freezes them
([`proposals/2026-11-22-recall-and-memory-direction.md`](proposals/2026-11-22-recall-and-memory-direction.md),
"Order"). No rule that favours words for identifier queries is applied;
the design keeps one only if calibration supports it.

### Cost

A search embeds only passages with no stored vector, in batches of 64,
and starts no new batch after 10 seconds; a batch already started
finishes, so the time spent can pass 10 seconds by up to one batch. What
it did not reach is answered by words, and the capability line says how
many passages are embedded ("412 of 664 passages embedded").
`index` and `enable-vectors` have no limit.

Measured on this repository's Windows development host (68 files, 661
passages, warm): a search took about 0.6 s with vectors and 0.28 s
without. Of the difference, about 0.2 s is importing numpy and model2vec,
0.02 s reading and hashing the model files, and 0.04 s building the model
from those bytes; embedding a query takes well under 1 ms.
`enable-vectors`, from an offline copy, took about 1 s, including the
canary. These are one host's
numbers, not a budget: the design sets budgets only after the applied
project measures them on Windows and POSIX.

Each vector is 512 bytes (256 16-bit floats), plus its key and SQLite's
own overhead in the cache. The model takes about 31 MB per working tree,
plus the person's own copy in DIR while they keep it.

### The paraphrase canary

`check-vectors` proves the vector path works on this worktree. Its
question lives in `tools/recall_vectors.py`, outside every searched
path. The fact it must find is the section below, which shares none of
the question's content words. It passes only when:

1. words alone do not find the fact (so the question cannot pass on its
   own words);
2. with vectors on, the fact is on the page as a `meaning` hit;
3. a related but wrong question leaves the fact in the related group,
   never as a primary hit.

A non-empty result is not a pass. Run it after enabling, after an
update, and whenever vectors look wrong. It fails while vectors are off.

## Paraphrase canary

Strawberries and blueberries taste sweetest in early summer.

The sentence above is the indexed half of the vector canary that
`check-vectors` runs. Keep it as written, in a section of its own.
