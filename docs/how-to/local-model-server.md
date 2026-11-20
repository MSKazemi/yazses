---
title: Use your own local model server for cleanup
description: Point YazSes's optional LLM cleanup at Ollama, llama-server, LM Studio or vLLM running on this machine, with the model you choose.
---

# Use your own local model server for cleanup

LLM cleanup is an optional pass that fixes capitalisation, punctuation and paragraph
breaks after dictation, before the text is typed. It is **off by default**. If you
already run a model server on this machine, YazSes can use it. No extra Python package
is needed.

Cleanup sends **the text you dictated** to the server. For that reason YazSes only
talks to a **loopback** address (`localhost`, `127.0.0.0/8`, `::1`). It refuses any
other host before opening a connection, and the API style you pick below does not
change that. See [Running fully air-gapped](air-gapped.md) for the opt-out and what it
means.

## Ollama

Ollama is the default API style, so you only name the model:

```toml
[filters.disfluency]
llm_enabled = true
llm_endpoint = "http://localhost:11434"
llm_endpoint_model = "qwen2.5:1.5b"   # any model you have pulled; empty means qwen2.5:1.5b
```

YazSes sends `"think": false`, so a thinking model answers without its reasoning
trace.

## An OpenAI-compatible server

llama-server (llama.cpp), LM Studio, vLLM and Ollama itself all serve
`/v1/chat/completions`. Set `llm_api = "openai"` and point `llm_endpoint` at the
server's base address, **without** the `/v1` suffix:

```toml
[filters.disfluency]
llm_enabled = true
llm_api = "openai"
llm_endpoint = "http://127.0.0.1:8080"   # llama-server's default port
llm_endpoint_model = "my-model"          # whatever name your server expects
```

Common default ports: llama-server `8080`, LM Studio `1234`, vLLM `8000`,
Ollama `11434`. YazSes POSTs `{llm_endpoint}/v1/chat/completions` with your
system prompt as a `system` message, the dictated text as a `user` message,
`temperature = 0`, `max_tokens = llm_max_tokens` and `stream = false`, and reads
`choices[0].message.content`. Left empty, `llm_endpoint_model` sends `qwen2.5:1.5b`.
llama-server serves whichever model it loaded and ignores the name, so you can leave
it empty there. vLLM and LM Studio match the name, so set it to what the server
lists under `/v1/models`.

If the model emits a `<think>…</think>` block before its answer, YazSes removes it.
An answer that is nothing but a thinking block counts as a failed cleanup.

## What happens when cleanup gets it wrong

Every answer passes two checks before it is typed. Its length must stay within
`llm_min_length_ratio` and `llm_max_length_ratio` of what you said. Every number,
identifier and proper noun you said must still be there. A rewrite that drops
"0900" or turns "100" into "1000" is rejected. On a rejection, a timeout
(`llm_timeout_ms`, 2 seconds by default) or a server error, YazSes types what you
said without cleanup.

## Check it

```sh
yazses doctor
```

The **LLM cleanup** row says whether the endpoint is loopback and therefore permitted.

## Which model?

No model is recommended yet. A measured comparison of small models on the reference
CPU is planned; until then, start with the smallest instruction-tuned model your
server offers and raise `llm_timeout_ms` if cleanup times out.

## See also

- [Configuration reference](../configuration.md) — every `llm_*` key, under `[filters]`.
- [Running fully air-gapped](air-gapped.md) — the loopback rule and its opt-out.
