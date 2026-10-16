from langchain_openrouter import ChatOpenRouter

from hawkdive.agent.config import AgentConfig


def create_model(config: AgentConfig) -> ChatOpenRouter:
    return ChatOpenRouter(
        model=config.model, api_key=config.openrouter_api_key,
        reasoning={'effort': config.reasoning_effort}, max_tokens=32768,
        # ChatOpenRouter expresses this timeout in milliseconds.
        timeout=60000, max_retries=0,
    )
