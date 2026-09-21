"""AGENTIC STAR Marketplace entrypoint — one-shot Pod process.

Referenced by this repo's Dockerfile as the image `CMD`. Compiles the agent,
provisions its secrets, then hands off to shared.bootstrap.marketplace_app for
the Marketplace lifecycle (identity, input, events, terminal delivery, exit).

`namespace=` here is the Marketplace secret-provisioning namespace — a different
concept from `config/agent.yaml`'s AgentRegistry `namespace:` key that happens
to share its value.
"""

from pathlib import Path

from framework.utils.config_loader import load_agent_config
from shared.bootstrap.marketplace_app import run_agent_marketplace
from src.graph.graph import Graph

# Add config overrides here to set values without touching config/config.yaml.
extend_config = {}

if __name__ == "__main__":
    run_agent_marketplace(
        Graph,
        agent_name="hcr-c2-048",
        namespace="hcr",
        config={**load_agent_config(Path(__file__).resolve().parent), **extend_config},
    )
