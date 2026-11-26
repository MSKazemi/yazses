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
llm_endpoint = "http://127.0.0.1:9931"   # llama-server's current default port
llm_endpoint_model = "my-model"          # whatever name your server expects
```

YazSes POSTs `{llm_endpoint}/v1/chat/completions` with your system prompt as a
`system` message, the dictated text as a `user` message, `temperature = 0`,
`max_tokens = llm_max_tokens` and `stream = false`, and reads
`choices[0].message.content`. Left empty, `llm_endpoint_model` sends `qwen2.5:1.5b`.

What each server expects, from its own documentation (checked November 2026):

| Server | Default address | What `llm_endpoint_model` must be |
|---|---|---|
| [llama-server](https://github.com/ggml-org/llama.cpp/tree/master/tools/server) (llama.cpp) | `127.0.0.1:9931`. Older releases and many guides used `8080`; check `--port` | In router mode the name picks the model, so give it. With a single model, the docs say only that a sibling endpoint ignores the name, so the default probably works but is unverified |
| [LM Studio](https://lmstudio.ai/docs/developer/openai-compat) | The docs' examples use `localhost:1234`; `lms server start` reuses the last port | The model identifier LM Studio shows. With just-in-time loading on, a request loads that model; with it off, load the model first |
| [vLLM](https://docs.vllm.ai/en/latest/serving/online_serving/openai_compatible_server/) | `localhost:8000` (`vllm serve --port`, [default 8000](https://docs.vllm.ai/en/latest/cli/serve/)) | The served model name (`--served-model-name`, else the `--model` argument). An unknown name gets a 404 |
| [Ollama](https://docs.ollama.com/api/openai-compatibility) | `localhost:11434` | A model you have pulled. Ollama's native API above is the simpler choice |

Not verified: the LM Studio pages do not state a fixed default port. The llama-server
docs do not say what its chat endpoint does with an unknown name in single-model mode. The Ollama
compatibility page's examples use only the `user` role. No real server of any of
these four has been tried with YazSes yet. Only an in-process fake server has.

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
