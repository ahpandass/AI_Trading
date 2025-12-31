"""Helper functions for LLM"""

import json, re
from pydantic import BaseModel
from src.llm.models import get_model, get_model_info
from src.utils.progress import progress
from src.graph.state import AgentState


def call_llm(
    prompt: any,
    pydantic_model: type[BaseModel],
    agent_name: str | None = None,
    state: AgentState | None = None,
    max_retries: int = 3,
    default_factory=None,
) -> BaseModel:
    """
    Makes an LLM call with retry logic, handling both JSON supported and non-JSON supported models.

    Args:
        prompt: The prompt to send to the LLM
        pydantic_model: The Pydantic model class to structure the output
        agent_name: Optional name of the agent for progress updates and model config extraction
        state: Optional state object to extract agent-specific model configuration
        max_retries: Maximum number of retries (default: 3)
        default_factory: Optional factory function to create default response on failure

    Returns:
        An instance of the specified Pydantic model
    """
    
    # Extract model configuration if state is provided and agent_name is available
    if state and agent_name:
        model_name, model_provider = get_agent_model_config(state, agent_name)
    else:
        # Use system defaults when no state or agent_name is provided
        model_name = "gpt-4.1"
        model_provider = "OPENAI"

    # Extract API keys from state if available
    api_keys = None
    if state:
        request = state.get("metadata", {}).get("request")
        if request and hasattr(request, 'api_keys'):
            api_keys = request.api_keys

    model_info = get_model_info(model_name, model_provider)
    llm = get_model(model_name, model_provider, api_keys)

    # For non-JSON support models, we can use structured output
    if not (model_info and not model_info.has_json_mode()):
        llm = llm.with_structured_output(
            pydantic_model,
            method="json_mode",
        )

    # Call the LLM with retries
    for attempt in range(max_retries):
        try:
            # Call the LLM
            result = llm.invoke(prompt)

            # For non-JSON support models, we need to extract and parse the JSON manually
            if model_info and not model_info.has_json_mode():
                parsed_result = extract_json_from_response(result.content)
                if parsed_result:
                    return pydantic_model(**parsed_result)
            else:
                return result

        except Exception as e:
            if agent_name:
                progress.update_status(agent_name, None, f"Error - retry {attempt + 1}/{max_retries}")

            if attempt == max_retries - 1:
                print(f"Error in LLM call after {max_retries} attempts: {e}")
                # Use default_factory if provided, otherwise create a basic default
                if default_factory:
                    return default_factory()
                return create_default_response(pydantic_model)

    # This should never be reached due to the retry logic above
    return create_default_response(pydantic_model)


def create_default_response(model_class: type[BaseModel]) -> BaseModel:
    """Creates a safe default response based on the model's fields."""
    default_values = {}
    for field_name, field in model_class.model_fields.items():
        if field.annotation == str:
            default_values[field_name] = "Error in analysis, using default"
        elif field.annotation == float:
            default_values[field_name] = 0.0
        elif field.annotation == int:
            default_values[field_name] = 0
        elif hasattr(field.annotation, "__origin__") and field.annotation.__origin__ == dict:
            default_values[field_name] = {}
        else:
            # For other types (like Literal), try to use the first allowed value
            if hasattr(field.annotation, "__args__"):
                default_values[field_name] = field.annotation.__args__[0]
            else:
                default_values[field_name] = None

    return model_class(**default_values)


def extract_json_from_response(content: str) -> dict | None:
    """Extracts JSON from markdown-formatted response."""
    """针对 R1 优化的 JSON 提取逻辑"""
    try:
        # 1. 预处理：去除前后空白
        content = content.strip()

        # 2. 尝试寻找最后一个 ```json ... ``` 块
        # R1 的结果通常在最后一个代码块里
        json_blocks = re.findall(r"```json\s*(.*?)\s*```", content, re.DOTALL)
        if json_blocks:
            # 尝试解析最后一个代码块
            try:
                return json.loads(json_blocks[-1].strip())
            except:
                pass

        # 3. 核心修复：从后往前定位最后一个完整的 { ... }
        # 错误 "Extra data" 往往是因为我们从前往后找，找早了。
        last_brace_index = content.rfind('}')
        if last_brace_index != -1:
            # 从最后一个 } 开始往前找对应的 {
            # 这里我们采用一种“贪婪但安全”的策略
            # 找到最后一个 { 
            first_brace_index = content.rfind('{', 0, last_brace_index)
            if first_brace_index != -1:
                potential_json = content[first_brace_index : last_brace_index + 1]
                try:
                    return json.loads(potential_json)
                except:
                    # 如果中间还有干扰，尝试找最前面一个 { 到最后一个 }
                    all_json_match = re.search(r"(\{.*\})", content, re.DOTALL)
                    if all_json_match:
                        return json.loads(all_json_match.group(1).strip())
            
    except Exception as e:
        print(f"Error extracting JSON from R1 massive output: {e}")
    return None


def get_agent_model_config(state, agent_name):
    """
    Get model configuration for a specific agent from the state.
    Falls back to global model configuration if agent-specific config is not available.
    Always returns valid model_name and model_provider values.
    """
    request = state.get("metadata", {}).get("request")

    # 策略：硬路由逻辑
    # 只有决策者使用 deepseek-reasoner (R1)
    #if agent_name == "portfolio_manager":
        #return "deepseek-reasoner", "DeepSeek"
    #    return "deepseek-chat", "DeepSeek"
    
    if request and hasattr(request, 'get_agent_model_config'):
        # Get agent-specific model configuration
        model_name, model_provider = request.get_agent_model_config(agent_name)
        # Ensure we have valid values
        if model_name and model_provider:
            return model_name, model_provider.value if hasattr(model_provider, 'value') else str(model_provider)
    
    # Fall back to global configuration (system defaults)
    model_name = state.get("metadata", {}).get("model_name") or "gpt-4.1"
    model_provider = state.get("metadata", {}).get("model_provider") or "OPENAI"
    
    # Convert enum to string if necessary
    if hasattr(model_provider, 'value'):
        model_provider = model_provider.value
    
    return model_name, model_provider
