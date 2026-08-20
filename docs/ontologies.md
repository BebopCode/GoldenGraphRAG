# Ontologies

The ontology is the single biggest lever on extraction quality: it declares the
**only** legal node and relationship labels, the extractor injects them into every
prompt, and it validates the model's output against them; a closed label set is what
prevents messy, inconsistent graphs.

It's plain YAML, so a new domain is a new file, never a code change.

## Shape

```yaml
name: movies                      # required
description: A simple movie ontology.

node_types:                       # at least one, labels must be unique
  - label: Movie                  # the only legal entity labels
    description: A film.
    properties: [title, year]     # suggested properties (informational)
  - label: Person
    properties: [name]

relationship_types:               # labels must be unique; endpoints must exist
  - label: ACTED_IN
    source: Person                # allowed source node label
    target: Movie                 # allowed target node label
  - label: DIRECTED
    source: Person
    target: Movie
```

Validation is loud and immediate. At startup, an ontology is rejected if:

- it has no `node_types`,
- a node or relationship label is duplicated,
- a relationship's `source`/`target` references an undeclared node label.

At extraction time, anything the model emits that isn't declared here is **dropped and
logged**: check the `INFO` lines for `[chunk-id] dropping off-ontology ...` if a run
yields less than expected. Relationship endpoint *pairs* are also checked: an
`ACTED_IN` between two `Person` nodes is dropped even though both labels exist.

## Pointing the pipeline at it

```bash
# ad hoc, one run:
ONTOLOGY_PATH=config/ontologies/movies.yaml kg ingest my_movies.json

# or permanently, in .env:
# ONTOLOGY_PATH=config/ontologies/movies.yaml

# or as a separate profile:
kg ingest my_movies.json --env .env.movies
```

## Shipped examples

Two ontologies ship in
[`config/ontologies/`](https://github.com/BebopCode/GoldenGraphRAG/tree/main/config/ontologies):

- **`generic.yaml`**: the domain-agnostic starter: one `Entity` label and a
  `RELATED_TO` relationship. Good for first runs and for eyeballing extraction quality.
- **`constitution.yaml`**: a legal-domain ontology (Part / Article / Amendment /
  Institution, `PART_OF` / `REFERENCES` / `AMENDS`) built for the Constitution of
  India. Pair it with the [`.env.constitution`](configuration.md#multiple-configurations)
  profile and `data/samples/constitution_sample.md`.
