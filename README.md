# ena-biosamples-mcp

An MCP server that lets LLM clients ask questions about public genomics data in the
[European Nucleotide Archive (ENA)](https://www.ebi.ac.uk/ena) and
[BioSamples](https://www.ebi.ac.uk/biosamples) in natural language.

> Work in progress. Full usage docs and example conversations coming soon.

## Tools

| Tool | What it answers |
|---|---|
| `count_records` | "How many cattle sequencing runs are in ENA?" |
| `search_samples` | "Show me cattle samples collected in the United Kingdom" |
| `get_biosample` | "What tissue and breed is sample SAMEA7658521?" |
| `check_sample_metadata` | "Is this sample's metadata complete enough for FAANG?" |

## Run locally

```bash
uv sync
uv run pytest
uv run python scripts/smoke_live.py   # live check against ENA and BioSamples
uv run ena-mcp                        # start the MCP server (stdio)
```
