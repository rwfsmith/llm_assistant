"""Constants for the LLM Assistant integration."""

import logging

from homeassistant.const import CONF_LLM_HASS_API, CONF_PROMPT
from homeassistant.helpers import llm

DOMAIN = "llm_assistant"
LOGGER = logging.getLogger(__package__)

# ---------------------------------------------------------------------------
# Server configuration
# ---------------------------------------------------------------------------
CONF_SERVER_NAME = "server_name"
CONF_BASE_URL = "base_url"
CONF_USE_LMSTUDIO_API = "use_lmstudio_api"

# ---------------------------------------------------------------------------
# Agent configuration
# ---------------------------------------------------------------------------
CONF_TEMPERATURE = "temperature"
CONF_MAX_MESSAGE_HISTORY = "max_message_history"
CONF_STRIP_EMOJIS = "strip_emojis"
CONF_PARALLEL_TOOL_CALLS = "parallel_tool_calls"
CONF_CONTEXT_LENGTH = "context_length"

# ---------------------------------------------------------------------------
# MCP server configuration keys (stored per agent subentry)
# ---------------------------------------------------------------------------
CONF_MCP_SERVERS = "mcp_servers"

# Fields inside each MCP server object
CONF_MCP_TYPE = "type"          # "ephemeral_mcp" | "plugin"
CONF_MCP_LABEL = "label"        # server_label for ephemeral
CONF_MCP_URL = "url"            # server_url for ephemeral
CONF_MCP_PLUGIN_ID = "plugin_id"  # integration id for plugin (e.g. "mcp/playwright")
CONF_MCP_ALLOWED_TOOLS = "allowed_tools"  # comma-separated, optional
CONF_MCP_HEADERS = "headers"       # dict, optional auth headers for ephemeral

MCP_TYPE_EPHEMERAL = "ephemeral_mcp"
MCP_TYPE_PLUGIN = "plugin"

MCP_TYPE_OPTIONS = [
    {"label": "Ephemeral MCP (URL-based)", "value": MCP_TYPE_EPHEMERAL},
    {"label": "LM Studio Plugin (mcp.json)", "value": MCP_TYPE_PLUGIN},
]

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
RECOMMENDED_CONVERSATION_OPTIONS = {
    CONF_LLM_HASS_API: [llm.LLM_API_ASSIST],
    CONF_PROMPT: llm.DEFAULT_INSTRUCTIONS_PROMPT,
}

DEFAULT_TEMPERATURE = 0.6
DEFAULT_CONTEXT_LENGTH = 8000
DEFAULT_MAX_HISTORY = 0
