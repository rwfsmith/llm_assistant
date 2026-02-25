# LLM Assistant – Home Assistant Custom Integration

[![HACS Badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/release/rwfsmith/llm_assistant.svg)](https://github.com/rwfsmith/llm_assistant/releases)

A Home Assistant custom integration that adds a **Voice Assistant Conversation Agent** powered by any OpenAI-compatible LLM endpoint (LM Studio, Ollama, llama.cpp, vLLM, OpenRouter, etc.) with full **MCP (Model Context Protocol)** server support.

---

## Features

- 🔌 **OpenAI-compatible endpoint** – works with any server exposing `/v1/chat/completions`
- 🤖 **Model selection** – fetches available models dynamically and lets you choose from a dropdown
- 🔧 **MCP server configuration** – supports both **ephemeral MCP** (URL-based) and **LM Studio plugin** references (`mcp/...`)  
- 🏠 **Home Assistant tool calling** – full integration with HA's LLM API (control lights, switches, etc.)
- 🎙️ **Voice/TTS streaming** – streamed responses for low-latency Assist pipelines
- 🧠 **LM Studio Native API** – optional mode that calls `/api/v1/chat` directly so LM Studio can orchestrate MCP tool execution end-to-end
- ⚙️ **Per-agent configuration** – multiple agents on the same server, each with its own model and MCP setup

---

## Installation

### Via HACS (recommended)

1. Open HACS → **Integrations**
2. Click the ⋮ menu → **Custom repositories**
3. Add `https://github.com/rwfsmith/llm_assistant` as type **Integration**
4. Search for **LLM Assistant** and click **Download**
5. Restart Home Assistant

### Manual

Copy the `custom_components/llm_assistant` folder to your HA `custom_components` directory and restart.

---

## Configuration

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **LLM Assistant**
3. Enter the **server URL** (e.g. `http://192.168.1.100:1234/v1`)  
   - For LM Studio: `http://localhost:1234/v1`  
   - For Ollama: `http://localhost:11434/v1`
4. Optionally enter an **API key** (leave blank for local servers)
5. Optionally enable **LM Studio Native API** to use LM Studio's `/api/v1/chat` endpoint for MCP orchestration

Once the server entry is saved, add one or more **Conversation Agents** via the subentry flow:

1. Click **Add Agent** on the integration card
2. Choose a **model** from the dropdown (fetched live from your server)
3. Configure the system prompt, temperature, HA LLM APIs, etc.
4. Add **MCP servers** (optional):

### MCP Server Types

| Type | When to use | Required fields |
|------|-------------|----------------|
| `ephemeral_mcp` | Remote/HTTP MCP servers, one-off requests | Label, URL |
| `plugin` | LM Studio pre-configured servers in `mcp.json` | Plugin ID (e.g. `mcp/playwright`) |

> **Note:** Ephemeral MCP requires "Allow per-request MCPs" enabled in LM Studio Server Settings.  
> Plugin MCP requires "Allow calling servers from mcp.json" enabled.

---

## LM Studio Native API Mode

When **Use LM Studio Native API** is enabled on the server entry, the integration switches from the standard OpenAI `/v1/chat/completions` endpoint to LM Studio's `/api/v1/chat` endpoint. In this mode:

- MCP servers are passed as `integrations` in the request body
- LM Studio **executes** MCP tool calls internally before returning the final response
- The response format uses LM Studio's `output` array (handled transparently by this integration)
- HA tool calling still works in parallel alongside MCP tools

---

## Example: LM Studio with Playwright MCP

1. Install [playwright-mcp](https://github.com/microsoft/playwright-mcp) and add it to LM Studio's `mcp.json`
2. Enable "Allow calling servers from mcp.json" in LM Studio settings
3. In the agent config, add an MCP server with:
   - Type: `plugin`
   - Plugin ID: `mcp/playwright`

The agent can now browse the web on behalf of the user.

---

## Acknowledgements

- Inspired by [hass_local_openai_llm](https://github.com/skye-harris/hass_local_openai_llm) by [@skye-harris](https://github.com/skye-harris)
- Forked from the [OpenRouter](https://github.com/home-assistant/core/tree/dev/homeassistant/components/open_router) integration
- MCP support based on the [LM Studio MCP API](https://lmstudio.ai/docs/developer/core/mcp)
