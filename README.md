# ena-biosamples-mcp

An MCP server that lets LLM clients ask questions about public genomics data in the
[European Nucleotide Archive (ENA)](https://www.ebi.ac.uk/ena) and
[BioSamples](https://www.ebi.ac.uk/biosamples) in natural language.

> Work in progress. Full usage docs and example conversations coming soon.

## Tools

| Tool | What it answers |
|---|---|
| `count_records` | "How many cattle sequencing runs are in ENA?" |

## Run locally

```bash
uv sync
uv run pytest
uv run python scripts/smoke_live.py   # live check against ENA
uv run ena-mcp                        # start the MCP server (stdio)
```
